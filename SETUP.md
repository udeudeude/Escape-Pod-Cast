# Set up Escape Pod Cast for $0

The default setup uses a **private Backblaze B2 bucket + a free Render web service**. Backblaze currently says no credit card is required to start B2, and the first 10 GB of storage is free.

The bucket stays private. Escape Pod Cast relays authenticated audio from B2 to your podcast application, so you do **not** need to pay to enable a public bucket.

## 1. Create a free Backblaze account

Go to:

**https://www.backblaze.com/sign-up/cloud-storage**

Create the account and verify your email address. No credit card is required to start.

If B2 Cloud Storage is not already enabled, open **My Settings → Enabled Products** and enable **B2 Cloud Storage**.

## 2. Create a private bucket

1. Open **B2 Cloud Storage → Buckets**.
2. Choose **Create a Bucket**.
3. Give it a globally unique name, for example `escape-pod-cast-yourname`.
4. Leave **Files in Bucket: Private**.
5. You do not need Object Lock.
6. Create the bucket.
7. Copy its **Endpoint**. It looks like:

```
s3.us-west-004.backblazeb2.com
```

For Escape Pod Cast:

- **STORAGE_ENDPOINT** = `https://` plus that endpoint
- **STORAGE_REGION** = the region embedded in it, e.g. `us-west-004`
- **STORAGE_BUCKET** = your bucket name

## 3. Create a bucket-specific application key

1. Open **B2 Cloud Storage → Application Keys**.
2. Choose **Add a New Application Key**.
3. Name it `escape-pod-cast`.
4. Restrict it to the bucket you just created.
5. Give it **Read and Write** access.
6. Enable **Allow List All Bucket Names** if Backblaze presents that option. Backblaze recommends this for S3-compatible bucket-restricted keys.
7. Create the key.
8. Copy both values immediately:
   - **keyID** → **STORAGE_ACCESS_KEY_ID**
   - **applicationKey** → **STORAGE_SECRET_ACCESS_KEY**

Backblaze displays the applicationKey only once.

## 4. Deploy the machine on Render

Use:

**https://render.com/deploy?repo=https://github.com/udeudeude/Escape-Pod-Cast**

The repository requests a **free** Render web service and **no persistent disk**.

When Render asks for variables, enter:

| Variable | Value |
| --- | --- |
| `ADMIN_PASSWORD` | A password you choose for your uploader |
| `STORAGE_ENDPOINT` | e.g. `https://s3.us-west-004.backblazeb2.com` |
| `STORAGE_REGION` | e.g. `us-west-004` |
| `STORAGE_ACCESS_KEY_ID` | Backblaze `keyID` |
| `STORAGE_SECRET_ACCESS_KEY` | Backblaze `applicationKey` |
| `STORAGE_BUCKET` | Your bucket name |

Render generates **FEED_TOKEN** automatically. Do not change it later unless you deliberately want a new feed URL.

You may also customize **SHOW_TITLE**, **SHOW_DESCRIPTION**, and **AUTHOR**.

## 5. Subscribe

Open your deployed Render URL.

Your browser will ask for a username and password. The username can be anything; the password is your **ADMIN_PASSWORD**.

The page shows your secret podcast feed URL. Add it to your podcast application using **Follow a Show by URL**, **Add Podcast by URL**, or equivalent.

## 6. Publish

Drop an audio file into Escape Pod Cast, edit its title or notes if desired, and tap **Publish**.

The file streams into your private B2 bucket. Escape Pod Cast updates the metadata object in the same bucket. Your podcast feed immediately contains the episode.

## Architecture

```
phone / Mac
    |
    | upload
    v
Escape Pod Cast on free Render
    |
    | authenticated S3-compatible API
    v
private Backblaze B2 bucket
    ^
    |
Escape Pod Cast relays audio with HTTP byte-range support
    |
podcast app
```

Render's filesystem is disposable. Your library survives because the audio and episode metadata live in B2.

## Other object-storage providers

Escape Pod Cast is intentionally provider-neutral. It uses the S3-compatible API. If you prefer Cloudflare R2 or another compatible provider, use its endpoint, region, access key, secret, and bucket in the same five `STORAGE_*` variables.

Cloudflare R2 works, but Cloudflare currently requires a billing method to activate R2 even when usage remains inside its free allowance. That is why Backblaze B2 is the default setup.
