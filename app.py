import logging
import os
import re
from urllib.parse import quote, unquote, urlparse
import requests
from flask import Flask, render_template, request, Response, stream_with_context, abort, url_for
from xml.etree import ElementTree as ET

_log_level = getattr(logging, os.environ.get('LOG_LEVEL', 'WARNING').upper(), logging.WARNING)
logging.basicConfig(
    level=_log_level,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('ebookbrowser')

app = Flask(__name__)

CWA_URL = os.environ.get('CWA_URL', 'http://localhost:8083').rstrip('/')
CWA_USER = os.environ.get('CWA_USERNAME', '')
CWA_PASS = os.environ.get('CWA_PASSWORD', '')
SHOW_COVERS = os.environ.get('SHOW_COVERS', 'true').lower() == 'true'
PAGE_SIZE = int(os.environ.get('PAGE_SIZE', '20'))

ATOM = '{http://www.w3.org/2005/Atom}'
MIME_TO_FORMAT = {
    'application/epub+zip': 'EPUB',
    'application/kepub+zip': 'KEPUB',
    'application/x-mobipocket-ebook': 'MOBI',
    'application/pdf': 'PDF',
    'application/x-cbz': 'CBZ',
    'application/x-cbr': 'CBR',
    'application/vnd.amazon.ebook': 'AZW',
    'application/x-fictionbook+xml': 'FB2',
}
KNOWN_FORMATS = {'EPUB', 'KEPUB', 'MOBI', 'PDF', 'CBZ', 'CBR', 'AZW', 'FB2', 'DJVU', 'ZIP'}


def cwa_auth():
    return (CWA_USER, CWA_PASS) if CWA_USER else None


def extract_path(href):
    """Return just the path (and query string) from a relative or absolute href."""
    if href.startswith(('http://', 'https://')):
        p = urlparse(href)
        return p.path + ('?' + p.query if p.query else '')
    return href


def encode_path(path):
    """Normalize a URL path that may be partially decoded or encoded."""
    return quote(unquote(path), safe='/:@!$&\'()*+,;=?')


def cwa_url_for(href):
    """Build a CWA request URL from any href (relative or absolute).

    Absolute hrefs from the OPDS feed may carry a different hostname than
    CWA_URL (e.g. the Pi-hole name vs 127.0.0.1). We always discard the
    host and reconstruct via CWA_URL so requests route correctly.
    """
    return CWA_URL + encode_path(extract_path(href))


def is_valid_href(href):
    if not href:
        return False
    path = extract_path(href)
    return path.startswith('/') and '..' not in path


def detect_format(mimetype, href):
    """Detect book format by scanning URL path segments right-to-left.

    CWA uses the same MIME type for EPUB and KEPUB, so the URL path is the
    only reliable signal. urlparse correctly strips query strings for both
    relative and absolute hrefs. Scanning right-to-left handles trailing
    numeric IDs (e.g. /opds/download/123/kepub/0).
    """
    path = urlparse(href).path
    for seg in reversed(path.rstrip('/').split('/')):
        if seg.upper() in KNOWN_FORMATS:
            return seg.upper()
    return MIME_TO_FORMAT.get(mimetype)


def fetch_opds(path):
    try:
        r = requests.get(CWA_URL + encode_path(path), auth=cwa_auth(), timeout=15)
        r.raise_for_status()
        return ET.fromstring(r.content), None
    except requests.RequestException as e:
        return None, str(e)
    except ET.ParseError as e:
        return None, 'XML parse error: ' + str(e)


def parse_feed(root):
    """Return (entries, next_opds_path) from an OPDS Atom feed."""
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
                fmt = detect_format(ltype, href)
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
                'type': 'book', 'title': title,
                'authors': authors, 'cover_href': cover_href, 'downloads': downloads,
            })
        elif nav_href:
            entries.append({'type': 'nav', 'title': title, 'opds_path': nav_href})

    next_opds_path = next(
        (lnk.get('href') for lnk in root.findall(ATOM + 'link')
         if lnk.get('rel') == 'next'),
        None
    )
    return entries, next_opds_path


@app.route('/')
def index():
    query = request.args.get('q', '').strip()
    browse = request.args.get('browse', 'recent')
    path_param = request.args.get('path', '').strip()
    try:
        offset = max(0, int(request.args.get('offset', 0)))
    except ValueError:
        offset = 0

    # Determine OPDS path to fetch
    if path_param and path_param.startswith('/opds/'):
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
    all_entries, next_opds_path = parse_feed(root)

    # Slice to current page
    page_entries = all_entries[offset:offset + PAGE_SIZE]

    # Build next-page URL
    next_url = None
    if offset + PAGE_SIZE < len(all_entries):
        # More entries remain in this OPDS page
        next_url = url_for('index', path=opds, offset=offset + PAGE_SIZE,
                           q=query or None)
    elif next_opds_path:
        # Advance to the next OPDS page (offset resets to 0)
        next_url = url_for('index', path=next_opds_path, q=query or None)

    return render_template('index.html',
                           entries=page_entries,
                           query=query,
                           browse=browse,
                           next_url=next_url,
                           show_covers=SHOW_COVERS,
                           error=error)


@app.route('/cover')
def cover():
    href = request.args.get('href', '')
    if not is_valid_href(href):
        abort(400)
    try:
        r = requests.get(cwa_url_for(href), auth=cwa_auth(), timeout=10, stream=True)
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
    log.info('DL request | remote=%s ua=%s href=%s',
             request.remote_addr,
             request.headers.get('User-Agent', '-'),
             href)

    if not is_valid_href(href):
        log.warning('DL rejected invalid href: %r', href)
        abort(400)

    cwa_url = cwa_url_for(href)
    log.info('DL fetching CWA url: %s', cwa_url)

    try:
        r = requests.get(cwa_url, auth=cwa_auth(), timeout=120)
        r.raise_for_status()
    except requests.RequestException as e:
        log.error('DL CWA fetch failed: %s', e)
        abort(502)

    log.info('DL CWA response: status=%s content-type=%s content-length=%s',
             r.status_code,
             r.headers.get('Content-Type'),
             r.headers.get('Content-Length', f'{len(r.content)}B (buffered)'))

    content_type = r.headers.get('Content-Type', 'application/octet-stream')

    # Determine correct file extension from the URL format segment.
    # Kobo requires .kepub.epub (not .kepub) to auto-import KEPUB files.
    url_path = urlparse(href).path.rstrip('/')
    fmt = url_path.rsplit('/', 1)[-1].lower()
    ext = 'kepub.epub' if fmt == 'kepub' else (fmt if fmt else 'epub')

    # Parse the book title from CWA's Content-Disposition (preferred over a
    # bare book-ID filename). CWA sends filename*=UTF-8''... (RFC 5987) and/or
    # filename=URL-encoded-title.ext — try the RFC 5987 form first.
    cwa_disp = r.headers.get('Content-Disposition', '')
    basename = None
    m = re.search(r"filename\*=UTF-8''([^;\s]+)", cwa_disp, re.IGNORECASE)
    if m:
        basename = unquote(m.group(1)).rsplit('.', 1)[0]
    else:
        m = re.search(r'filename=["\']?([^"\';\r\n]+)', cwa_disp)
        if m:
            basename = unquote(m.group(1).strip().strip('\'"')).rsplit('.', 1)[0]

    if not basename:
        book_id = next((p for p in reversed(url_path.split('/')) if p.isdigit()), 'book')
        basename = f'book-{book_id}'

    disposition = f'attachment; filename="{basename}.{ext}"'

    log.info('DL sending to client: content-type=%s disposition=%s size=%d bytes',
             content_type, disposition, len(r.content))

    return Response(
        r.content,
        content_type=content_type,
        headers={
            'Content-Disposition': disposition,
            'Content-Length': str(len(r.content)),
        }
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
