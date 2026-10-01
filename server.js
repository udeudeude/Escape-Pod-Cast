import http from 'node:http';
import fsSync from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 3000);
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, 'data');
const MEDIA_DIR = path.join(DATA_DIR, 'media');
const DB_PATH = path.join(DATA_DIR, 'episodes.json');
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'change-me';
const FEED_TOKEN = process.env.FEED_TOKEN || 'change-this-feed-token';
const SHOW_TITLE = process.env.SHOW_TITLE || 'Escape Pod Cast';
const SHOW_DESCRIPTION = process.env.SHOW_DESCRIPTION || 'My personal audio feed.';
const AUTHOR = process.env.AUTHOR || 'Personal';
const MAX_UPLOAD_MB = Number(process.env.MAX_UPLOAD_MB || 300);
const PUBLIC_URL = (process.env.PUBLIC_URL || '').replace(/\/$/, '');

await fs.mkdir(MEDIA_DIR, { recursive: true });
try { await fs.access(DB_PATH); } catch { await atomicWrite([]); }

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
    const p = url.pathname;

    if (req.method === 'GET' && p === '/health') return json(res, 200, { ok: true });
    if (req.method === 'GET' && p.startsWith('/assets/')) return serveAsset(p.slice('/assets/'.length), req, res);

    if (req.method === 'GET' && p === '/') {
      if (!authorized(req)) return challenge(res);
      return home(req, res);
    }
    if (req.method === 'POST' && p === '/upload') {
      if (!authorized(req)) return challenge(res);
      return upload(req, res);
    }
    const del = p.match(/^\/episodes\/([0-9a-f-]{36})\/delete$/i);
    if (req.method === 'POST' && del) {
      if (!authorized(req)) return challenge(res);
      return deleteEpisode(del[1], res);
    }
    const feed = p.match(/^\/feed\/([^/]+)\.xml$/);
    if (req.method === 'GET' && feed) return podcastFeed(req, res, decodeURIComponent(feed[1]));
    const media = p.match(/^\/media\/([^/]+)\/([^/]+)$/);
    if ((req.method === 'GET' || req.method === 'HEAD') && media) return serveMedia(req, res, decodeURIComponent(media[1]), decodeURIComponent(media[2]));

    text(res, 404, 'Not found');
  } catch (error) {
    console.error(error);
    text(res, 500, error?.message || 'Server error');
  }
});

server.listen(PORT, () => console.log(`Escape Pod Cast listening on :${PORT}`));

function authorized(req) {
  const h = req.headers.authorization || '';
  if (!h.startsWith('Basic ')) return false;
  let decoded = '';
  try { decoded = Buffer.from(h.slice(6), 'base64').toString('utf8'); } catch { return false; }
  const password = decoded.includes(':') ? decoded.slice(decoded.indexOf(':') + 1) : '';
  const a = Buffer.from(password), b = Buffer.from(ADMIN_PASSWORD);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}
function challenge(res) {
  res.writeHead(401, { 'WWW-Authenticate': 'Basic realm="Escape Pod Cast"', 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('Authentication required');
}
function origin(req) {
  if (PUBLIC_URL) return PUBLIC_URL;
  const proto = String(req.headers['x-forwarded-proto'] || 'http').split(',')[0].trim();
  return `${proto}://${req.headers.host}`;
}
function feedUrl(req) { return `${origin(req)}/feed/${encodeURIComponent(FEED_TOKEN)}.xml`; }
async function loadEpisodes() {
  try { return JSON.parse(await fs.readFile(DB_PATH, 'utf8')); } catch { return []; }
}
async function atomicWrite(episodes) {
  const tmp = `${DB_PATH}.${process.pid}.${Date.now()}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(episodes, null, 2));
  await fs.rename(tmp, DB_PATH);
}
function safeText(value, max = 5000) { return String(value ?? '').trim().slice(0, max); }
function fileTitle(filename) { return path.basename(filename, path.extname(filename)).replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim(); }
function allowedExt(filename) {
  const ext = path.extname(filename).toLowerCase();
  return ['.mp3','.m4a','.mp4','.aac','.wav','.flac','.ogg','.opus'].includes(ext) ? ext : null;
}
function mimeFor(filename) {
  return ({'.mp3':'audio/mpeg','.m4a':'audio/mp4','.mp4':'audio/mp4','.aac':'audio/aac','.wav':'audio/wav','.flac':'audio/flac','.ogg':'audio/ogg','.opus':'audio/ogg'})[path.extname(filename).toLowerCase()] || 'application/octet-stream';
}

async function home(req, res) {
  const episodes = (await loadEpisodes()).sort((a,b) => new Date(b.publishedAt) - new Date(a.publishedAt));
  const rows = episodes.map(e => `<article class="episode"><div><strong>${html(e.title)}</strong><div class="meta">${html(new Date(e.publishedAt).toLocaleString())} · ${e.duration ? html(formatDuration(e.duration))+' · ' : ''}${html(formatBytes(e.size))}</div></div><audio controls preload="none" src="/media/${encodeURIComponent(FEED_TOKEN)}/${encodeURIComponent(e.file)}"></audio><form method="post" action="/episodes/${e.id}/delete" onsubmit="return confirm('Delete this episode and its audio file?')"><button class="danger" type="submit">Delete</button></form></article>`).join('');
  htmlResponse(res, 200, page(`<header><p class="kicker">PERSONAL PODCAST</p><h1>${html(SHOW_TITLE)}</h1><p>${html(SHOW_DESCRIPTION)}</p></header>
<section class="card"><h2>Drop audio here</h2><form id="uploadForm" action="/upload" method="post" enctype="multipart/form-data"><label id="dropzone" class="dropzone"><input id="files" type="file" name="audio" accept="audio/*,.m4a,.mp3,.wav,.flac,.ogg,.opus,.aac,.mp4" multiple required><span><b>Choose files</b> or drop them here</span><small>MP3, M4A, AAC, WAV, FLAC, OGG, OPUS · up to ${MAX_UPLOAD_MB} MB per request</small></label><div id="queue"></div><button id="publish" class="primary" type="submit" disabled>Publish episode</button><p id="status" class="meta"></p></form></section>
<section class="card"><h2>Subscribe once</h2><p>Add this address in your podcast app using “Follow a Show by URL” or “Add podcast by URL.”</p><div class="feedrow"><code id="feed">${html(feedUrl(req))}</code><button type="button" onclick="navigator.clipboard.writeText(document.getElementById('feed').textContent);this.textContent='Copied'">Copy</button></div><p class="meta">Anyone who has this long secret address can fetch the feed and audio. Keep it private.</p></section>
<section><h2>Episodes <span class="count">${episodes.length}</span></h2>${rows || '<p class="empty">Nothing published yet.</p>'}</section>`));
}

async function upload(req, res) {
  const contentLength = Number(req.headers['content-length'] || 0);
  if (contentLength && contentLength > MAX_UPLOAD_MB * 1024 * 1024) return text(res, 413, `Upload exceeds ${MAX_UPLOAD_MB} MB.`);
  const webRequest = new Request('http://localhost/upload', { method: 'POST', headers: req.headers, body: Readable.toWeb(req), duplex: 'half' });
  let form;
  try { form = await webRequest.formData(); } catch { return text(res, 400, 'Could not read upload.'); }
  const files = form.getAll('audio').filter(v => typeof v === 'object' && v && typeof v.stream === 'function');
  if (!files.length) return text(res, 400, 'No audio files uploaded.');
  const titles = form.getAll('title');
  const descriptions = form.getAll('description');
  const durations = form.getAll('duration');
  const episodes = await loadEpisodes();
  const created = [];
  try {
    for (let i=0;i<files.length;i++) {
      const f = files[i];
      const ext = allowedExt(f.name || '');
      if (!ext || (!String(f.type || '').startsWith('audio/') && ext !== '.mp4')) throw new Error(`Not a supported audio file: ${f.name || 'upload'}`);
      const id = crypto.randomUUID();
      const stored = `${id}${ext}`;
      const destination = path.join(MEDIA_DIR, stored);
      await pipeline(Readable.fromWeb(f.stream()), fsSync.createWriteStream(destination));
      created.push(destination);
      const size = Number(f.size || (await fs.stat(destination)).size);
      episodes.push({ id, title: safeText(titles[i] || fileTitle(f.name), 300) || 'Untitled episode', description: safeText(descriptions[i] || '', 5000), originalName: safeText(f.name, 500), file: stored, mime: mimeFor(stored), size, duration: Math.max(0, Number(durations[i]) || 0), publishedAt: new Date().toISOString() });
    }
    await atomicWrite(episodes);
    redirect(res, '/');
  } catch (error) {
    for (const f of created) { try { await fs.rm(f, { force: true }); } catch {} }
    text(res, 400, error.message || 'Upload failed');
  }
}

async function deleteEpisode(id, res) {
  const episodes = await loadEpisodes();
  const target = episodes.find(e => e.id === id);
  if (!target) return text(res, 404, 'Episode not found');
  await fs.rm(path.join(MEDIA_DIR, target.file), { force: true });
  await atomicWrite(episodes.filter(e => e.id !== id));
  redirect(res, '/');
}

async function podcastFeed(req, res, token) {
  if (token !== FEED_TOKEN) return text(res, 404, 'Not found');
  const base = origin(req);
  const episodes = (await loadEpisodes()).sort((a,b) => new Date(b.publishedAt)-new Date(a.publishedAt));
  const items = episodes.map(e => `<item><title>${xml(e.title)}</title><guid isPermaLink="false">${xml(e.id)}</guid><pubDate>${new Date(e.publishedAt).toUTCString()}</pubDate><description>${xml(e.description || e.originalName || e.title)}</description><enclosure url="${xml(`${base}/media/${encodeURIComponent(FEED_TOKEN)}/${encodeURIComponent(e.file)}`)}" length="${Number(e.size)||0}" type="${xml(e.mime || mimeFor(e.file))}"/>${e.duration ? `<itunes:duration>${Math.round(e.duration)}</itunes:duration>` : ''}</item>`).join('\n');
  const body = `<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel><title>${xml(SHOW_TITLE)}</title><link>${xml(base)}</link><description>${xml(SHOW_DESCRIPTION)}</description><language>en-us</language><itunes:author>${xml(AUTHOR)}</itunes:author><itunes:explicit>false</itunes:explicit><itunes:type>episodic</itunes:type><itunes:category text="Society &amp; Culture"/><itunes:image href="${xml(`${base}/assets/cover.png`)}"/><atom:link href="${xml(feedUrl(req))}" rel="self" type="application/rss+xml"/>${items}</channel></rss>`;
  res.writeHead(200, { 'Content-Type':'application/rss+xml; charset=utf-8', 'Content-Length':Buffer.byteLength(body), 'Cache-Control':'no-store' }); res.end(body);
}

async function serveMedia(req, res, token, filename) {
  if (token !== FEED_TOKEN || !/^[0-9a-f-]{36}\.[a-z0-9]{2,5}$/i.test(filename)) return text(res, 404, 'Not found');
  const full = path.join(MEDIA_DIR, filename);
  let stat; try { stat = await fs.stat(full); } catch { return text(res, 404, 'Not found'); }
  const total = stat.size, range = req.headers.range;
  if (range) {
    const m = /^bytes=(\d*)-(\d*)$/.exec(range);
    if (!m) { res.writeHead(416, { 'Content-Range':`bytes */${total}` }); return res.end(); }
    let start = m[1] ? Number(m[1]) : 0, end = m[2] ? Number(m[2]) : total-1;
    if (!m[1] && m[2]) { const n=Number(m[2]); start=Math.max(0,total-n); end=total-1; }
    if (start > end || start >= total) { res.writeHead(416, { 'Content-Range':`bytes */${total}` }); return res.end(); }
    end = Math.min(end,total-1);
    res.writeHead(206, { 'Content-Type':mimeFor(filename), 'Content-Length':end-start+1, 'Content-Range':`bytes ${start}-${end}/${total}`, 'Accept-Ranges':'bytes', 'Cache-Control':'private, max-age=3600' });
    if (req.method === 'HEAD') return res.end();
    return fsSync.createReadStream(full,{start,end}).pipe(res);
  }
  res.writeHead(200, { 'Content-Type':mimeFor(filename), 'Content-Length':total, 'Accept-Ranges':'bytes', 'Cache-Control':'private, max-age=3600' });
  if (req.method === 'HEAD') return res.end();
  fsSync.createReadStream(full).pipe(res);
}

async function serveAsset(name, req, res) {
  if (!['app.css','app.js','favicon.svg','cover.png'].includes(name)) return text(res,404,'Not found');
  const full = path.join(__dirname,'public',name); let stat; try { stat=await fs.stat(full); } catch { return text(res,404,'Not found'); }
  const type = name.endsWith('.css')?'text/css; charset=utf-8':name.endsWith('.js')?'text/javascript; charset=utf-8':name.endsWith('.png')?'image/png':'image/svg+xml';
  res.writeHead(200,{'Content-Type':type,'Content-Length':stat.size,'Cache-Control':'public, max-age=86400'}); if(req.method==='HEAD') return res.end(); fsSync.createReadStream(full).pipe(res);
}
function redirect(res, location){ res.writeHead(303,{Location:location}); res.end(); }
function text(res,status,body){ body=String(body); res.writeHead(status,{'Content-Type':'text/plain; charset=utf-8','Content-Length':Buffer.byteLength(body)}); res.end(body); }
function json(res,status,obj){ const body=JSON.stringify(obj); res.writeHead(status,{'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}); res.end(body); }
function htmlResponse(res,status,body){ res.writeHead(status,{'Content-Type':'text/html; charset=utf-8','Content-Length':Buffer.byteLength(body)}); res.end(body); }
function xml(v=''){ return String(v).replace(/[<>&"']/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&apos;'}[c])); }
function html(v=''){ return String(v).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function formatBytes(n=0){ return n<1048576?`${Math.max(1,Math.round(n/1024))} KB`:`${(n/1048576).toFixed(1)} MB`; }
function formatDuration(s=0){ s=Math.round(s); const h=Math.floor(s/3600),m=Math.floor((s%3600)/60); return h?`${h}h ${m}m`:`${m} min`; }
function page(body){ return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>${html(SHOW_TITLE)}</title><link rel="stylesheet" href="/assets/app.css"><link rel="icon" href="/assets/favicon.svg"></head><body><main>${body}</main><script src="/assets/app.js"></script></body></html>`; }
