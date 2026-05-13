# CLAUDE.md — ebookbrowser

## What this is
A lightweight read-only ebook browser that proxies CWA's (Calibre-Web Automated) OPDS feed and renders it as simple HTML. Built specifically for the Kobo e-reader's built-in browser, which cannot render CWA's native web UI.

## Stack
- Python 3.11 / Flask
- Deployed as a Docker container with `network_mode: host` (required so the container can resolve LAN hostnames via Pi-hole DNS on the same machine)
- No JavaScript. No CSS Grid/Flexbox. HTML tables for layout. All CSS is inline in the template.

## File structure
```
app.py                  # Flask app — all routes and OPDS parsing
templates/index.html    # Single Jinja2 template (inline CSS, no JS)
Dockerfile
docker-compose.yml      # network_mode: host — do not change without understanding the DNS setup
requirements.txt
.env.example            # Copy to .env and fill in before running
```

## Running locally (development)
```bash
pip install -r requirements.txt
cp .env.example .env   # fill in CWA_URL, CWA_USERNAME, CWA_PASSWORD
python app.py
```

## Running in Docker (production)
```bash
cp .env.example .env   # fill in values
docker compose up -d --build   # always use --build to pick up code changes
```

## Key environment variables
| Variable | Default | Notes |
|----------|---------|-------|
| `CWA_URL` | `http://localhost:8083` | Use `http://127.0.0.1` if CWA is on the same machine |
| `CWA_USERNAME` | — | CWA login |
| `CWA_PASSWORD` | — | CWA login |
| `SHOW_COVERS` | `true` | Set false for faster page loads on Kobo |
| `PAGE_SIZE` | `20` | Books per page; keep low for Kobo |
| `PORT` | `5000` | Listening port |

## OPDS endpoints used
| View | OPDS path |
|------|-----------|
| Recent books | `/opds/new` |
| Search | `/opds/search/<query>` |
| Author list | `/opds/author/` |
| Series list | `/opds/series/` |
| Pagination | Via `<link rel="next">` href (CWA uses `?offset=N`) |

## Routes
| Route | Purpose |
|-------|---------|
| `GET /` | Main page — browse, search, paginate |
| `GET /cover?href=...` | Proxies cover images from CWA |
| `GET /dl?href=...` | Proxies book file downloads from CWA |

## Important design constraints
- **No JS**: the Kobo browser may not support modern JavaScript at all.
- **No external CSS**: styles are in a `<style>` block in the template to avoid a second HTTP request.
- **No flexbox/grid/CSS variables**: use `<table>` and basic CSS2.1 only.
- **Proxy everything**: covers and downloads go through `/cover` and `/dl` so the Kobo only authenticates with this app, not directly with CWA.
- **KEPUB detection**: CWA uses `application/epub+zip` MIME type for both EPUB and KEPUB. Format is detected from the URL path segment (`/opds/download/ID/kepub/`).
- **Hostname mismatch**: CWA_URL uses `127.0.0.1` but OPDS hrefs may carry the Pi-hole hostname. `cwa_url_for()` always strips the host from hrefs and reconstructs via CWA_URL.
- **network_mode: host**: required because CWA is on the same machine and served via a Pi-hole local DNS hostname. Do not revert to bridge networking without changing CWA_URL to an IP address.
