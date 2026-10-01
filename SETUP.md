# Setup Escape Pod Cast

This setup gives you your own uploader, your own Cloudflare R2 storage, and your own secret podcast feed.

## 1. Make the R2 bucket

1. Sign in to Cloudflare.
2. Open **Storage & databases → R2 → Overview**.
3. Choose **Create bucket**.
4. Name it something like `escape-pod-cast`.
5. Use the **Standard** storage class.

Keep this tab open.

## 2. Give the bucket a public media address

The easiest personal setup does not require buying a domain:

1. Open your new bucket.
2. Open **Settings**.
3. Under **Public Development URL**, choose **Enable**.
4. Cloudflare asks you to type `allow`.
5. Copy the resulting URL. It looks approximately like:

```
https://pub-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.r2.dev
```

This becomes **R2_PUBLIC_BASE_URL**.

Cloudflare calls `r2.dev` a development endpoint and rate-limits it. It is convenient for a personal/light-use installation. If you later want a more production-oriented setup, connect a custom domain to the bucket and replace only `R2_PUBLIC_BASE_URL`.

## 3. Create credentials for only this bucket

From **R2 → Overview**:

1. Open **Manage API Tokens**.
2. Choose **Create Account API token** or **Create User API token**.
3. Grant **Object Read & Write** permission.
4. Restrict the token to **this bucket only**.
5. Create the token.
6. Copy:
   - **Access Key ID**
   - **Secret Access Key**
   - your R2 **S3 endpoint**, which contains your Cloudflare Account ID.

The endpoint looks like:

```
https://<ACCOUNT_ID>.r2.cloudflarestorage.com
```

The part before `.r2.cloudflarestorage.com` is **R2_ACCOUNT_ID**.

Cloudflare only shows the secret access key when the token is created. Store it somewhere safe until the Render setup is complete.

## 4. Deploy your copy on Render

Use:

**https://render.com/deploy?repo=https://github.com/udeudeude/Escape-Pod-Cast**

The repository's `render.yaml` requests a **free** web service and no Render disk.

When Render asks for environment variables, enter:

| Variable | What to enter |
| --- | --- |
| `ADMIN_PASSWORD` | A password you choose for the uploader |
| `R2_ACCOUNT_ID` | Cloudflare Account ID from the R2 S3 endpoint |
| `R2_ACCESS_KEY_ID` | R2 token's Access Key ID |
| `R2_SECRET_ACCESS_KEY` | R2 token's Secret Access Key |
| `R2_BUCKET` | Your bucket name, for example `escape-pod-cast` |
| `R2_PUBLIC_BASE_URL` | Your `https://pub-….r2.dev` URL or custom R2 domain |

Render generates **FEED_TOKEN** automatically. Do not replace it unless you deliberately want to invalidate your old feed URL.

You can also edit **SHOW_TITLE**, **SHOW_DESCRIPTION**, and **AUTHOR**.

## 5. Open the uploader

After the deploy finishes, open the Render URL.

Your browser will ask for a username and password. The username does not matter; enter anything. The password is the **ADMIN_PASSWORD** you chose.

The page will show **Subscribe once** and your unique feed address.

Copy that feed address into your podcast application using **Follow a Show by URL**, **Add Podcast by URL**, or the equivalent option.

## 6. Publish something

Drop an audio file onto the uploader.

You can edit its title or add notes, then choose **Publish**. Escape Pod Cast streams the file into your R2 bucket and updates the metadata stored there. The next refresh of your podcast application should see it as a new episode.

## What is stored where?

Render stores no podcast library on disk.

Your bucket contains objects like:

```
media/<long-random-feed-token>/<random-id>.mp3
private/<long-random-feed-token>/episodes.json
```

The feed itself is generated on demand from `episodes.json`.

## Moving away from Render

Render is not fundamental to Escape Pod Cast. It is only the small web server running the machine. Because the library lives in your R2 bucket, you can move the server to another Node-compatible host later and reconnect the same environment variables.

Keep the same **FEED_TOKEN** and public hostname if you need the exact existing feed URL to remain unchanged.
