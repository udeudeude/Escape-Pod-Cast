import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import Busboy from 'busboy';
import { S3Client, GetObjectCommand, PutObjectCommand, DeleteObjectCommand } from '@aws-sdk/client-s3';
import { Upload } from '@aws-sdk/lib-storage';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 3000);
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || '';
const FEED_TOKEN = process.env.FEED_TOKEN || '';
const SHOW_TITLE = process.env.SHOW_TITLE || 'Escape Pod Cast';
const SHOW_DESCRIPTION = process.env.SHOW_DESCRIPTION || 'My personal audio feed.';
const AUTHOR = process.env.AUTHOR || 'Personal';
const MAX_UPLOAD_MB = Number(process.env.MAX_UPLOAD_MB || 300);
const PUBLIC_URL = (process.env.PUBLIC_URL || '').replace(/\/$/, '');

const STORAGE_ENDPOINT = (process.env.STORAGE_ENDPOINT || '').replace(/\/$/, '');
const STORAGE_REGION = process.env.STORAGE_REGION || 'auto';
const STORAGE_ACCESS_KEY_ID = process.env.STORAGE_ACCESS_KEY_ID || '';
const STORAGE_SECRET_ACCESS_KEY = process.env.STORAGE_SECRET_ACCESS_KEY || '';
const STORAGE_BUCKET = process.env.STORAGE_BUCKET || '';

const storageReady = Boolean(
  STORAGE_ENDPOINT && STORAGE_ACCESS_KEY_ID && STORAGE_SECRET_ACCESS_KEY &&
  STORAGE_BUCKET && FEED_TOKEN
);

const s3 = storageReady ? new S3Client({
  region: STORAGE_REGION,
  endpoint: STORAGE_ENDPOINT,
  credentials: {
    accessKeyId: STORAGE_ACCESS_KEY_ID,
    secretAccessKey: STORAGE_SECRET_ACCESS_KEY
  }
}) : null;

const META_KEY = FEED_TOKEN ? `private/${FEED_TOKEN}/episodes.json` : '';
const MEDIA_PREFIX = FEED_TOKEN ? `media/${FEED_TOKEN}/` : '';

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
    const p = url.pathname;

    if (req.method === 'GET' && p === '/health') return json(res, 200, { ok: true, storage: storageReady });
    if (req.method === 'GET' && p.startsWith('/assets/')) return serveAsset(p.slice('/assets/'.length), req, res);

    if (req.method === 'GET' && p === '/') {
      if (!authorized(req)) return challenge(res);
      return home(req, res);
    }
    if (req.method === 'POST' && p === '/upload') {
      if (!authorized(req)) return challenge(res);
      if (!storageReady) return text(res, 503, 'Storage is not configured yet.');
      return upload(req, res);
    }
    const del = p.match(/^\/episodes\/([0-9a-f-]{36})\/delete$/i);
    if (req.method === 'POST' && del) {
      if (!authorized(req)) return challenge(res);
      if (!storageReady) return text(res, 503, 'Storage is not configured yet.');
      return deleteEpisode(del[1], res);
    }
    const feed = p.match(/^\/feed\/([^/]+)\.xml$/);
    if (req.method === 'GET' && feed) {
      if (!storageReady) return text(res, 503, 'Storage is not configured yet.');
      return podcastFeed(req, res, decodeURIComponent(feed[1]));
    }
    const media = p.match(/^\/media\/([^/]+)\/([0-9a-f-]{36}\.[a-z0-9]{2,5})$/i);
    if ((req.method === 'GET' || req.method === 'HEAD') && media) {
      if (!storageReady) return text(res, 503, 'Storage is not configured yet.');
      return serveMedia(req, res, decodeURIComponent(media[1]), media[2]);
    }

    text(res, 404, 'Not found');
  } catch (error) {
    console.error(error);
    text(res, 500, error?.message || 'Server error');
  }
});

server.listen(PORT, () => console.log(`Escape Pod Cast listening on :${PORT}`));

function authorized(req) {
  if (!ADMIN_PASSWORD) return false;
  const h = req.headers.authorization || '';
  if (!h.startsWith('Basic ')) return false;
  let decoded = '';
  try { decoded = Buffer.from(h.slice(6), 'base64').toString('utf8'); } catch { return false; }
  const password = decoded.includes(':') ? decoded.slice(decoded.indexOf(':') + 1) : '';
  const a = Buffer.from(password), b = Buffer.from(ADMIN_PASSWORD);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

function challenge(res) {
  res.writeHead(401, {
    'WWW-Authenticate': 'Basic realm="Escape Pod Cast"',
    'Content-Type': 'text/plain; charset=utf-8'
  });
  res.end('Authentication required');
}

function origin(req) {
  if (PUBLIC_URL) return PUBLIC_URL;
  const proto = String(req.headers['x-forwarded-proto'] || 'http').split(',')[0].trim();
  return `${proto}://${req.headers.host}`;
}

function feedUrl(req) {
  return `${origin(req)}/feed/${encodeURIComponent(FEED_TOKEN)}.xml`;
}


async function loadEpisodes() {
  if (!storageReady) return [];
  try {
    const response = await s3.send(new GetObjectCommand({ Bucket: STORAGE_BUCKET, Key: META_KEY }));
    const textBody = await response.Body.transformToString();
    const parsed = JSON.parse(textBody);
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    if (error?.name === 'NoSuchKey' || error?.$metadata?.httpStatusCode === 404) return [];
    throw error;
  }
}

async function saveEpisodes(episodes) {
  await s3.send(new PutObjectCommand({
    Bucket: STORAGE_BUCKET,
    Key: META_KEY,
    Body: JSON.stringify(episodes, null, 2),
    ContentType: 'application/json',
    CacheControl: 'no-store'
  }));
}

function safeText(value, max = 5000) { return String(value ?? '').trim().slice(0, max); }

function fileTitle(filename) {
  return path.basename(filename, path.extname(filename))
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function allowedExt(filename) {
  const ext = path.extname(filename).toLowerCase();
  return ['.mp3','.m4a','.mp4','.aac','.wav','.flac','.ogg','.opus'].includes(ext) ? ext : null;
}

function mimeFor(filename) {
  return ({
    '.mp3':'audio/mpeg',
    '.m4a':'audio/mp4',
    '.mp4':'audio/mp4',
    '.aac':'audio/aac',
    '.wav':'audio/wav',
    '.flac':'audio/flac',
    '.ogg':'audio/ogg',
    '.opus':'audio/ogg'
  })[path.extname(filename).toLowerCase()] || 'application/octet-stream';
}

async function home(req, res) {
  const episodes = storageReady
    ? (await loadEpisodes()).sort((a,b) => new Date(b.publishedAt) - new Date(a.publishedAt))
    : [];

  const rows = episodes.map(e => `
    <article class="episode">
      <div>
        <strong>${html(e.title)}</strong>
        <div class="meta">${html(new Date(e.publishedAt).toLocaleString())} · ${e.duration ? html(formatDuration(e.duration))+' · ' : ''}${html(formatBytes(e.size))}</div>
      </div>
      <audio controls preload="none" src="/media/${encodeURIComponent(FEED_TOKEN)}/${encodeURIComponent(path.basename(e.key))}"></audio>
      <form method="post" action="/episodes/${e.id}/delete" onsubmit="return confirm('Delete this episode and its audio file?')">
        <button class="danger" type="submit">Delete</button>
      </form>
    </article>`).join('');

  const setup = !storageReady ? `
    <section class="card">
      <h2>Setup required</h2>
      <p>This instance is running, but it still needs your Cloudflare R2 bucket credentials.</p>
      <p class="meta">Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, STORAGE_BUCKET, R2_PUBLIC_BASE_URL, FEED_TOKEN, and ADMIN_PASSWORD in the host environment.</p>
      <p><a href="https://github.com/udeudeude/Escape-Pod-Cast/blob/main/SETUP.md">Open the setup guide</a></p>
    </section>` : '';

  htmlResponse(res, 200, page(`
    <header>
      <p class="kicker">PERSONAL PODCAST</p>
      <h1>${html(SHOW_TITLE)}</h1>
      <p>${html(SHOW_DESCRIPTION)}</p>
    </header>
    ${setup}
    <section class="card">
      <h2>Drop audio here</h2>
      <form id="uploadForm" action="/upload" method="post" enctype="multipart/form-data">
        <label id="dropzone" class="dropzone">
          <input id="files" type="file" name="audio" accept="audio/*,.m4a,.mp3,.wav,.flac,.ogg,.opus,.aac,.mp4" multiple required ${storageReady ? '' : 'disabled'}>
          <span><b>Choose files</b> or drop them here</span>
          <small>MP3, M4A, AAC, WAV, FLAC, OGG, OPUS · up to ${MAX_UPLOAD_MB} MB each</small>
        </label>
        <div id="queue"></div>
        <button id="publish" class="primary" type="submit" disabled>Publish episode</button>
        <p id="status" class="meta"></p>
      </form>
    </section>
    ${storageReady ? `
    <section class="card">
      <h2>Subscribe once</h2>
      <p>Add this address in your podcast app using “Follow a Show by URL” or “Add podcast by URL.”</p>
      <div class="feedrow">
        <code id="feed">${html(feedUrl(req))}</code>
        <button type="button" onclick="navigator.clipboard.writeText(document.getElementById('feed').textContent);this.textContent='Copied'">Copy</button>
      </div>
      <p class="meta">Treat this feed address as a password. Anyone who has it can discover the episode audio URLs.</p>
    </section>` : ''}
    <section>
      <h2>Episodes <span class="count">${episodes.length}</span></h2>
      ${rows || '<p class="empty">Nothing published yet.</p>'}
    </section>
  `));
}

async function upload(req, res) {
  const contentLength = Number(req.headers['content-length'] || 0);
  if (contentLength && contentLength > (MAX_UPLOAD_MB * 1024 * 1024 * 8)) {
    return text(res, 413, 'Upload request is too large.');
  }

  const bb = Busboy({
    headers: req.headers,
    limits: {
      fileSize: MAX_UPLOAD_MB * 1024 * 1024,
      files: 20,
      fields: 100
    }
  });

  const uploads = [];
  const titles = [];
  const descriptions = [];
  const durations = [];
  const uploadedKeys = [];
  let index = 0;
  let parseError = null;

  bb.on('field', (name, value) => {
    if (name === 'title') titles.push(value);
    if (name === 'description') descriptions.push(value);
    if (name === 'duration') durations.push(value);
  });

  bb.on('file', (name, stream, info) => {
    if (name !== 'audio') {
      stream.resume();
      return;
    }

    const fileIndex = index++;
    const ext = allowedExt(info.filename || '');
    if (!ext) {
      parseError = new Error(`Not a supported audio file: ${info.filename || 'upload'}`);
      stream.resume();
      return;
    }

    const id = crypto.randomUUID();
    const key = `${MEDIA_PREFIX}${id}${ext}`;
    const mime = mimeFor(info.filename || key);
    let bytes = 0;

    stream.on('data', chunk => { bytes += chunk.length; });
    stream.on('limit', () => { parseError = new Error(`${info.filename || 'File'} exceeds ${MAX_UPLOAD_MB} MB.`); });

    const task = new Upload({
      client: s3,
      params: {
        Bucket: STORAGE_BUCKET,
        Key: key,
        Body: stream,
        ContentType: mime,
        CacheControl: 'public, max-age=31536000, immutable'
      },
      queueSize: 2,
      partSize: 8 * 1024 * 1024,
      leavePartsOnError: false
    });

    uploads.push(
      task.done().then(() => {
        uploadedKeys.push(key);
        return {
          fileIndex,
          id,
          key,
          mime,
          bytes,
          originalName: safeText(info.filename, 500)
        };
      })
    );
  });

  const finished = new Promise((resolve, reject) => {
    bb.on('error', reject);
    bb.on('finish', resolve);
  });

  req.pipe(bb);

  try {
    await finished;
    if (parseError) throw parseError;
    const completed = await Promise.all(uploads);
    if (!completed.length) throw new Error('No audio files uploaded.');

    const episodes = await loadEpisodes();
    const now = Date.now();

    completed.sort((a,b) => a.fileIndex - b.fileIndex).forEach((f, i) => {
      episodes.push({
        id: f.id,
        title: safeText(titles[i] || fileTitle(f.originalName), 300) || 'Untitled episode',
        description: safeText(descriptions[i] || '', 5000),
        originalName: f.originalName,
        key: f.key,
        mime: f.mime,
        size: f.bytes,
        duration: Math.max(0, Number(durations[i]) || 0),
        publishedAt: new Date(now + i).toISOString()
      });
    });

    await saveEpisodes(episodes);
    redirect(res, '/');
  } catch (error) {
    await Promise.allSettled(uploadedKeys.map(key =>
      s3.send(new DeleteObjectCommand({ Bucket: STORAGE_BUCKET, Key: key }))
    ));
    text(res, 400, error?.message || 'Upload failed');
  }
}

async function deleteEpisode(id, res) {
  const episodes = await loadEpisodes();
  const target = episodes.find(e => e.id === id);
  if (!target) return text(res, 404, 'Episode not found');

  await s3.send(new DeleteObjectCommand({ Bucket: STORAGE_BUCKET, Key: target.key }));
  await saveEpisodes(episodes.filter(e => e.id !== id));
  redirect(res, '/');
}

async function podcastFeed(req, res, token) {
  if (token !== FEED_TOKEN) return text(res, 404, 'Not found');

  const base = origin(req);
  const episodes = (await loadEpisodes()).sort((a,b) => new Date(b.publishedAt) - new Date(a.publishedAt));

  const items = episodes.map(e => `
    <item>
      <title>${xml(e.title)}</title>
      <guid isPermaLink="false">${xml(e.id)}</guid>
      <pubDate>${new Date(e.publishedAt).toUTCString()}</pubDate>
      <description>${xml(e.description || e.originalName || e.title)}</description>
      <enclosure url="${xml(`${base}/media/${encodeURIComponent(FEED_TOKEN)}/${encodeURIComponent(path.basename(e.key))}`)}" length="${Number(e.size)||0}" type="${xml(e.mime || mimeFor(e.key))}"/>
      ${e.duration ? `<itunes:duration>${Math.round(e.duration)}</itunes:duration>` : ''}
    </item>`).join('\n');

  const body = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel>
<title>${xml(SHOW_TITLE)}</title>
<link>${xml(base)}</link>
<description>${xml(SHOW_DESCRIPTION)}</description>
<language>en-us</language>
<itunes:author>${xml(AUTHOR)}</itunes:author>
<itunes:explicit>false</itunes:explicit>
<itunes:type>episodic</itunes:type>
<itunes:category text="Society &amp; Culture"/>
<itunes:image href="${xml(`${base}/assets/cover.png`)}"/>
<atom:link href="${xml(feedUrl(req))}" rel="self" type="application/rss+xml"/>
${items}
</channel>
</rss>`;

  res.writeHead(200, {
    'Content-Type':'application/rss+xml; charset=utf-8',
    'Content-Length':Buffer.byteLength(body),
    'Cache-Control':'no-store'
  });
  res.end(body);
}

async function serveMedia(req, res, token, filename) {
  if (token !== FEED_TOKEN) return text(res, 404, 'Not found');
  const key = `${MEDIA_PREFIX}${filename}`;
  const range = req.headers.range;

  try {
    const response = await s3.send(new GetObjectCommand({
      Bucket: STORAGE_BUCKET,
      Key: key,
      ...(range ? { Range: range } : {})
    }));

    const size = Number(response.ContentLength || 0);
    const total = response.ContentRange
      ? Number(String(response.ContentRange).split('/').pop())
      : size;

    const headers = {
      'Content-Type': response.ContentType || mimeFor(filename),
      'Accept-Ranges': 'bytes',
      'Cache-Control': 'private, max-age=3600'
    };

    if (response.ContentRange) {
      headers['Content-Range'] = response.ContentRange;
      headers['Content-Length'] = String(size);
      res.writeHead(206, headers);
    } else {
      headers['Content-Length'] = String(size);
      res.writeHead(200, headers);
    }

    if (req.method === 'HEAD') {
      if (response.Body?.destroy) response.Body.destroy();
      return res.end();
    }

    if (!response.Body) return res.end();
    response.Body.on('error', error => res.destroy(error));
    response.Body.pipe(res);
  } catch (error) {
    if (error?.name === 'NoSuchKey' || error?.$metadata?.httpStatusCode === 404) {
      return text(res, 404, 'Not found');
    }
    if (error?.$metadata?.httpStatusCode === 416) {
      res.writeHead(416);
      return res.end();
    }
    throw error;
  }
}

async function serveAsset(name, req, res) {
  if (!['app.css','app.js','favicon.svg','cover.png'].includes(name)) return text(res,404,'Not found');
  const full = path.join(__dirname,'public',name);
  let stat;
  try { stat = await fs.stat(full); } catch { return text(res,404,'Not found'); }

  const type = name.endsWith('.css') ? 'text/css; charset=utf-8'
    : name.endsWith('.js') ? 'text/javascript; charset=utf-8'
    : name.endsWith('.png') ? 'image/png'
    : 'image/svg+xml';

  res.writeHead(200, {
    'Content-Type': type,
    'Content-Length': stat.size,
    'Cache-Control':'public, max-age=86400'
  });
  if (req.method === 'HEAD') return res.end();
  const file = await fs.readFile(full);
  res.end(file);
}

function redirect(res, location){ res.writeHead(303,{Location:location}); res.end(); }
function text(res,status,body){ body=String(body); res.writeHead(status,{'Content-Type':'text/plain; charset=utf-8','Content-Length':Buffer.byteLength(body)}); res.end(body); }
function json(res,status,obj){ const body=JSON.stringify(obj); res.writeHead(status,{'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}); res.end(body); }
function htmlResponse(res,status,body){ res.writeHead(status,{'Content-Type':'text/html; charset=utf-8','Content-Length':Buffer.byteLength(body)}); res.end(body); }

function xml(v=''){
  return String(v).replace(/[<>&"']/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&apos;'}[c]));
}

function html(v=''){
  return String(v).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

function formatBytes(n=0){
  return n < 1048576 ? `${Math.max(1,Math.round(n/1024))} KB` : `${(n/1048576).toFixed(1)} MB`;
}

function formatDuration(s=0){
  s=Math.round(s);
  const h=Math.floor(s/3600),m=Math.floor((s%3600)/60);
  return h ? `${h}h ${m}m` : `${m} min`;
}

function page(body){
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>${html(SHOW_TITLE)}</title>
<link rel="stylesheet" href="/assets/app.css">
<link rel="icon" href="/assets/favicon.svg">
</head>
<body>
<main>${body}</main>
<script src="/assets/app.js"></script>
</body>
</html>`;
}
