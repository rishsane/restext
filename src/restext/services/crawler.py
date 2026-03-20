import re
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura


async def _render_with_playwright(url: str, timeout: int = 30) -> str | None:
    """Render a JS-heavy page with Playwright and return HTML."""
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-gpu'])
            page = await browser.new_page()
            await page.goto(url, wait_until='networkidle', timeout=timeout * 1000)
            html = await page.content()
            await browser.close()
            return html
    except Exception as e:
        print(f"[CRAWLER] Playwright render failed for {url}: {type(e).__name__}: {e}", flush=True)
        return None


# URL path patterns that indicate boilerplate/legal pages
_BOILERPLATE_PATTERNS = [
    r"/privacy", r"/terms", r"/legal", r"/cookie", r"/tos",
    r"/disclaimer", r"/gdpr", r"/ccpa", r"/imprint",
    r"/acceptable-use", r"/dmca", r"/copyright",
]
_BOILERPLATE_RE = re.compile("|".join(_BOILERPLATE_PATTERNS), re.IGNORECASE)


async def crawl_url(url: str, max_pages: int = 50, timeout: int = 10) -> list[dict]:
    """Crawl a URL and return extracted content for each page.

    Returns list of {"url": str, "title": str, "content": str}
    """
    pages = []
    visited = set()
    to_visit = [url]
    base_domain = urlparse(url).netloc

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "RestextBot/1.0"},
    ) as client:
        while to_visit and len(pages) < max_pages:
            current_url = to_visit.pop(0)
            if current_url in visited:
                continue
            visited.add(current_url)

            try:
                resp = await client.get(current_url)
                if resp.status_code != 200:
                    continue
                if "text/html" not in resp.headers.get("content-type", ""):
                    continue

                html = resp.text
                content = trafilatura.extract(
                    html,
                    include_comments=False,
                    include_tables=True,
                    favor_recall=True,
                )

                # Fallback: if trafilatura gets nothing, try Playwright (JS rendering)
                if (not content or len(content.strip()) < 50):
                    print(f"[CRAWLER] No content from trafilatura for {current_url}, trying Playwright...", flush=True)
                    rendered_html = await _render_with_playwright(current_url)
                    if rendered_html:
                        content = trafilatura.extract(
                            rendered_html,
                            include_comments=False,
                            include_tables=True,
                            favor_recall=True,
                        )
                        if content and len(content.strip()) >= 50:
                            # Also extract links from rendered HTML for SPA navigation
                            html = rendered_html
                            print(f"[CRAWLER] Playwright extracted {len(content)} chars from {current_url}", flush=True)

                if not content or len(content.strip()) < 50:
                    continue

                title = _extract_title(html) or current_url
                published_at = _extract_publish_date(html)
                is_boilerplate = _is_boilerplate_url(current_url)
                pages.append({
                    "url": current_url,
                    "title": title,
                    "content": content,
                    "published_at": published_at,
                    "is_boilerplate": is_boilerplate,
                })

                # Extract same-origin links for BFS (skip boilerplate URLs)
                if len(pages) < max_pages:
                    links = _extract_links(html, current_url, base_domain)
                    for link in links:
                        if link not in visited and not _is_boilerplate_url(link):
                            to_visit.append(link)

            except Exception:
                continue

    return pages


async def crawl_sitemap(sitemap_url: str, max_pages: int = 50, timeout: int = 10) -> list[dict]:
    """Parse a sitemap XML and crawl all listed URLs."""
    pages = []

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "RestextBot/1.0"},
    ) as client:
        try:
            resp = await client.get(sitemap_url)
            if resp.status_code != 200:
                return []

            urls = _parse_sitemap_xml(resp.text)

            for url in urls[:max_pages]:
                try:
                    page_resp = await client.get(url)
                    if page_resp.status_code != 200:
                        continue
                    html = page_resp.text
                    content = trafilatura.extract(
                        html,
                        include_comments=False,
                        include_tables=True,
                        favor_recall=True,
                    )
                    if not content or len(content.strip()) < 50:
                        continue

                    title = _extract_title(html) or url
                    published_at = _extract_publish_date(html)
                    is_boilerplate = _is_boilerplate_url(url)
                    pages.append({
                        "url": url,
                        "title": title,
                        "content": content,
                        "published_at": published_at,
                        "is_boilerplate": is_boilerplate,
                    })
                except Exception:
                    continue

        except Exception:
            return []

    return pages


def _extract_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def _extract_links(html: str, base_url: str, base_domain: str) -> list[str]:
    links = []
    for match in re.finditer(r'href=["\']([^"\']+)["\']', html):
        href = match.group(1)
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.netloc == base_domain and parsed.scheme in ("http", "https"):
            clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            links.append(clean)
    return list(set(links))


def _parse_sitemap_xml(xml_text: str) -> list[str]:
    urls = []
    try:
        root = ET.fromstring(xml_text)
        # Handle namespace
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"

        for url_elem in root.findall(f".//{ns}loc"):
            if url_elem.text:
                urls.append(url_elem.text.strip())
    except ET.ParseError:
        pass
    return urls


def _extract_publish_date(html: str) -> str | None:
    """Extract publication date from HTML using JSON-LD, Open Graph, and meta tags.

    Returns ISO 8601 date string or None.
    """
    # 1. JSON-LD datePublished
    match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
    if match:
        return _normalize_date(match.group(1))

    # 2. Open Graph article:published_time
    match = re.search(
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',
            html, re.IGNORECASE,
        )
    if match:
        return _normalize_date(match.group(1))

    # 3. Generic date meta tags
    for name in ("date", "pubdate", "publish_date", "DC.date.issued"):
        match = re.search(
            rf'<meta[^>]+name=["\'](?i:{re.escape(name)})["\'][^>]+content=["\']([^"\']+)["\']',
            html, re.IGNORECASE,
        )
        if match:
            return _normalize_date(match.group(1))

    # 4. <time> element with datetime attribute
    match = re.search(r'<time[^>]+datetime=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if match:
        return _normalize_date(match.group(1))

    return None


def _normalize_date(raw: str) -> str | None:
    """Try to parse a date string into ISO 8601 format."""
    raw = raw.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d", "%B %d, %Y", "%d %B %Y"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.isoformat()
        except ValueError:
            continue
    # Last resort: try to extract just a date
    match = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
    if match:
        return match.group(1) + "T00:00:00"
    return None


def _is_boilerplate_url(url: str) -> bool:
    """Check if a URL path matches known boilerplate patterns."""
    parsed = urlparse(url)
    return bool(_BOILERPLATE_RE.search(parsed.path))
