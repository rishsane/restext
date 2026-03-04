import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura


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
                if not content or len(content.strip()) < 50:
                    continue

                title = _extract_title(html) or current_url
                pages.append({"url": current_url, "title": title, "content": content})

                # Extract same-origin links for BFS
                if len(pages) < max_pages:
                    links = _extract_links(html, current_url, base_domain)
                    for link in links:
                        if link not in visited:
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
                    pages.append({"url": url, "title": title, "content": content})
                except Exception:
                    continue

        except Exception:
            return []

    return pages


def _extract_title(html: str) -> str | None:
    import re
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def _extract_links(html: str, base_url: str, base_domain: str) -> list[str]:
    import re
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
