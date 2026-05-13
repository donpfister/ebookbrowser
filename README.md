# ebookbrowser

A lightweight web interface for browsing and downloading ebooks from [Calibre-Web Automated (CWA)](https://github.com/crocodilestick/Calibre-Web-Automated), designed for the **Kobo e-reader's built-in browser**.

Kobo's browser cannot render CWA's native web UI. This app consumes CWA's OPDS feed and serves plain HTML that the Kobo can display and interact with.

## Features

- Browse recently added books
- Browse by author or series
- Full-text search
- Paginated results (configurable page size)
- Download EPUB, KEPUB, MOBI, PDF, and other formats
- Cover thumbnails (optional)
- All requests proxied — the Kobo only talks to this app

## Requirements

- Docker and Docker Compose
- A running CWA instance accessible from the same machine
- CWA's OPDS feed enabled (Admin → Configuration → Feature Configuration → Enable OPDS)

## Setup

1. **Clone the repo**
   ```bash
   git clone https://github.com/donpfister/ebookbrowser.git
   cd ebookbrowser
   ```

2. **Create your `.env` file**
   ```bash
   cp .env.example .env
   ```
   Edit `.env`:
   ```env
   CWA_URL=http://127.0.0.1        # use 127.0.0.1 if CWA is on the same machine
   CWA_USERNAME=your_username
   CWA_PASSWORD=your_password
   SHOW_COVERS=true                 # set false for faster Kobo page loads
   PAGE_SIZE=20
   PORT=5000
   ```

3. **Start the container**
   ```bash
   docker compose up -d --build
   ```

4. **Open in your Kobo browser**

   Navigate to `http://YOUR-SERVER-IP:5000` in the Kobo's built-in browser.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CWA_URL` | `http://localhost:8083` | URL of your CWA instance. Use `http://127.0.0.1` if on the same host. |
| `CWA_USERNAME` | — | CWA username |
| `CWA_PASSWORD` | — | CWA password |
| `SHOW_COVERS` | `true` | Show cover thumbnails. Disable for faster loads. |
| `PAGE_SIZE` | `20` | Books shown per page. Lower values load faster on Kobo. |
| `PORT` | `5000` | Port this app listens on. |
| `LOG_LEVEL` | `WARNING` | Logging verbosity. See Troubleshooting below. |

## Troubleshooting

### Turning on detailed logs

Set `LOG_LEVEL=DEBUG` in your `.env` file, then rebuild:

```bash
docker compose down && docker compose up -d --build
```

Stream logs in real time while reproducing the problem:

```bash
docker compose logs -f
```

`DEBUG` logs every HTTP request the app makes to CWA (including covers, downloads, and OPDS fetches) plus the full request/response details for the `/dl` route. This is noisy during normal use, which is why the default is `WARNING`.

Log levels from quietest to loudest:

| Level | What you see |
|-------|-------------|
| `WARNING` | Errors and rejections only (default) |
| `INFO` | Download request summaries (remote IP, href, response size) |
| `DEBUG` | Every CWA HTTP call including covers and OPDS pages |

### Kobo downloads are slow to prompt

The Kobo browser (WebKit 538.1) can take 30–60 seconds to show the "download this file?" prompt after tapping a format button. This is normal — the browser is old. The file is transferred in the background; wait for the prompt before assuming it failed.

### Downloads work on desktop but not Kobo

1. Set `LOG_LEVEL=DEBUG` and watch `docker compose logs -f` while tapping the download link on the Kobo.
2. If you see a `DL request` line, the Kobo is reaching the server. Check the `DL sending` line for the response details.
3. If you see no `DL request` line at all, the Kobo browser is not reaching the app — check your network/IP configuration.

## Updating

```bash
git pull
docker compose down && docker compose up -d --build
```

> **Always use `--build`** when updating. Without it, Docker reuses the cached image and code changes won't take effect.

## Notes

- This app is **read-only** — it provides no ability to upload, edit, or delete books.
- `docker-compose.yml` uses `network_mode: host` so the container shares the host's DNS. This is required when CWA is on the same machine and served via a local DNS name (e.g. Pi-hole). The app binds to the host's port directly — no port mapping needed.
- KEPUB and EPUB are distinguished by URL path since CWA uses the same MIME type for both.
