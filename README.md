# Photo Album Frontend (Vanilla JS)

A minimal single-page app to **upload** images to your API Gateway (PUT `/photos`) and **search** them (GET `/search`).

## Quick start
1. Put these four files in a folder: `index.html`, `styles.css`, `config.js`, `app.js`.
2. Open `index.html` in Chrome (or host via any static server / S3 website).
3. Upload an image (optionally set labels like `Sam, Sally`) — watch the progress bar.
4. Search with `Sam` and you should see results.

### Notes
- Upload uses `PUT /photos?name=<filename>` with headers `x-api-key`, `Content-Type`, and optional `x-amz-meta-customlabels`.
- Search uses `GET /search?q=...` with `x-api-key`.
- If images aren’t public, make LF2 return **pre-signed URLs** or set a public-read policy on the bucket.