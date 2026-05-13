import os
from urllib.parse import quote, unquote
import requests
from flask import Flask, render_template, request, Response, stream_with_context, abort
from xml.etree import ElementTree as ET

app = Flask(__name__)

CWA_URL = os.environ.get('CWA_URL', 'http://localhost:8083').rstrip('/')
CWA_USER = os.environ.get('CWA_USERNAME', '')
CWA_PASS = os.environ.get('CWA_PASSWORD', '')
SHOW_COVERS = os.environ.get('SHOW_COVERS', 'true').lower() == 'true'

ATOM = '{http://www.w3.org/2005/Atom}'
MIME_TO_FORMAT = {
    'application/epub+zip': 'EPUB',
    'application/x-mobipocket-ebook': 'MOBI',
    'application/pdf': 'PDF',
    'application/x-cbz': 'CBZ',
    'application/vnd.amazon.ebook': 'AZW',
    'application/x-fictionbook+xml': 'FB2',
}


def cwa_auth():
    return (CWA_USER, CWA_PASS) if CWA_USER else None


def resolve_href(href):
    if href.startswith(('http://', 'https://')):
        return href
    return CWA_URL + href


def is_safe_href(href):
    """Only allow proxying resources from the configured CWA server."""
    url = resolve_href(href)
    return url.startswith(CWA_URL + '/') or url == CWA_URL


def is_safe_opds_path(path):
    return bool(path) and path.startswith('/opds/')


def encode_path(path):
    """Normalize a URL path that may be partially or fully decoded/encoded."""
    return quote(unquote(path), safe='/:@!$&\'()*+,;=')


def fetch_opds(path):
    url = CWA_URL + encode_path(path)
    try:
        r = requests.get(url, auth=cwa_auth(), timeout=15)
        r.raise_for_status()
        return ET.fromstring(r.content), None
    except requests.RequestException as e:
        return None, str(e)
    except ET.ParseError as e:
        return None, 'XML parse error: ' + str(e)


def parse_feed(root):
    """Return (entries, next_opds_path) from an OPDS Atom feed.

    Each entry is {'type': 'book', ...} or {'type': 'nav', ...}.
    """
    if root is None:
        return [], None

    entries = []
    for entry in root.findall(ATOM + 'entry'):
        title = entry.findtext(ATOM + 'title') or '(untitled)'
        downloads, cover_href, nav_href = [], None, None

        for link in entry.findall(ATOM + 'link'):
            rel = link.get('rel', '')
            href = link.get('href', '')
            ltype = link.get('type', '')

            if 'opds-spec.org/image/thumbnail' in rel and href:
                cover_href = href
            elif 'opds-spec.org/image' in rel and not cover_href and href:
                cover_href = href
            elif 'opds-spec.org/acquisition' in rel and href:
                fmt = MIME_TO_FORMAT.get(ltype)
                if fmt:
                    downloads.append({'format': fmt, 'href': href})
            elif rel == 'subsection' and href:
                nav_href = href

        if downloads:
            authors = [
                a.findtext(ATOM + 'name')
                for a in entry.findall(ATOM + 'author')
                if a.findtext(ATOM + 'name')
            ]
            entries.append({
                'type': 'book',
                'title': title,
                'authors': authors,
                'cover_href': cover_href,
                'downloads': downloads,
            })
        elif nav_href:
            entries.append({'type': 'nav', 'title': title, 'opds_path': nav_href})

    next_path = next(
        (lnk.get('href') for lnk in root.findall(ATOM + 'link')
         if lnk.get('rel') == 'next'),
        None
    )
    return entries, next_path


@app.route('/')
def index():
    query = request.args.get('q', '').strip()
    browse = request.args.get('browse', 'recent')
    path_param = request.args.get('path', '').strip()

    # Determine which OPDS feed to fetch
    if path_param and is_safe_opds_path(path_param):
        opds = path_param
    elif query:
        opds = '/opds/search/' + quote(query, safe='')
    elif browse == 'authors':
        opds = '/opds/author/'
    elif browse == 'series':
        opds = '/opds/series/'
    else:
        opds = '/opds/new'

    root, error = fetch_opds(opds)
    entries, next_path = parse_feed(root)

    return render_template('index.html',
                           entries=entries,
                           query=query,
                           browse=browse,
                           next_path=next_path,
                           show_covers=SHOW_COVERS,
                           error=error)


@app.route('/cover')
def cover():
    href = request.args.get('href', '')
    if not href or not is_safe_href(href):
        abort(400)
    try:
        r = requests.get(resolve_href(href), auth=cwa_auth(), timeout=10, stream=True)
        r.raise_for_status()
    except requests.RequestException:
        abort(404)
    return Response(
        stream_with_context(r.iter_content(8192)),
        content_type=r.headers.get('Content-Type', 'image/jpeg'),
        headers={'Cache-Control': 'public, max-age=86400'}
    )


@app.route('/dl')
def download():
    href = request.args.get('href', '')
    if not href or not is_safe_href(href):
        abort(400)
    try:
        r = requests.get(resolve_href(href), auth=cwa_auth(), timeout=120, stream=True)
        r.raise_for_status()
    except requests.RequestException:
        abort(502)
    headers = {
        'Content-Type': r.headers.get('Content-Type', 'application/octet-stream'),
    }
    for h in ('Content-Disposition', 'Content-Length'):
        if h in r.headers:
            headers[h] = r.headers[h]
    return Response(stream_with_context(r.iter_content(65536)), headers=headers)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
