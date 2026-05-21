"""arXiv API search: query building + Atom XML parsing."""

import re
import time
import urllib.parse
from typing import Literal

import httpx
from lxml import etree

from tenacity import retry, stop_after_attempt, wait_exponential

from .config import ARXIV_API_URL, ARXIV_PAGE_SIZE, ARXIV_RATE_LIMIT, ARXIV_TIMEOUT
from .models import PaperMeta

SearchField = Literal["ti", "abs", "au", "cat"]
BooleanOp = Literal["AND", "OR", "ANDNOT"]
SortBy = Literal["relevance", "lastUpdatedDate", "submittedDate"]

# Namespaces used in arXiv Atom responses
NSMAP: dict[str, str] = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}


def build_query(
    keywords: list[str],
    fields: list[SearchField] | None = None,
    date_range: tuple[str, str] | None = None,
    operator: BooleanOp = "AND",
) -> str:
    """Construct an arXiv API ``search_query`` string.

    Args:
        keywords: List of keyword phrases to search.
        fields: Fields to search within (ti, abs, au, cat).  Defaults to
            ``["ti", "abs"]``.
        date_range: Optional ``(from_yyyymmddhhmm, to_yyyymmddhhmm)``
            filter on ``submittedDate``.
        operator: Logical connective joining field:keyword terms.

    Returns:
        URL-encoded query string ready for the arXiv API.
    """
    if fields is None:
        fields = ["ti", "abs"]

    # Quote multi-word keywords so arXiv treats them as phrases
    def _escape(kw: str) -> str:
        kw = kw.strip()
        if " " in kw:
            return f'"{kw}"'
        return kw

    escaped = [_escape(k) for k in keywords]

    # Build per-field clause: ti:kw1+AND+ti:kw2+AND+...
    field_clauses: list[str] = []
    for f in fields:
        terms = [f"{f}:{kw}" for kw in escaped]
        field_clauses.append("+AND+".join(terms))

    # Combine fields with OR
    if len(field_clauses) == 1:
        query = field_clauses[0]
    else:
        query = f"({'+OR+'.join(field_clauses)})"

    # Append date range
    if date_range is not None:
        dfrom, dto = date_range
        query = f"({query})+AND+submittedDate:[{dfrom}+TO+{dto}]"

    return query


def _parse_atom_entry(entry: etree._Element, ns: dict) -> dict:
    """Extract metadata fields from a single ``<entry>`` element."""
    def _text(xpath: str) -> str:
        els = entry.xpath(xpath, namespaces=ns)
        if els and els[0].text:
            return " ".join(els[0].text.split())
        return ""

    def _texts(xpath: str) -> list[str]:
        return [
            " ".join(el.text.split())
            for el in entry.xpath(xpath, namespaces=ns)
            if el.text
        ]

    # arxiv_id from <id>http://arxiv.org/abs/XXXX.XXXXXvN</id>
    id_url = _text("atom:id")
    m = re.search(r"arxiv\.org/abs/([^/]+)$", id_url)
    arxiv_id = m.group(1) if m else id_url

    title = _text("atom:title")

    authors = _texts("atom:author/atom:name")

    published = _text("atom:published")
    updated = _text("atom:updated")

    categories = [
        el.get("term", "")
        for el in entry.xpath("atom:category", namespaces=ns)
        if el.get("term")
    ]

    abstract = _text("atom:summary")

    # pdf link: <link title="pdf" href="..."/>
    pdf_links = entry.xpath(
        'atom:link[@title="pdf"]/@href', namespaces=ns
    )
    pdf_url = str(pdf_links[0]) if pdf_links else ""

    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "authors": authors,
        "published": published,
        "updated": updated,
        "categories": categories,
        "abstract": abstract,
        "pdf_url": pdf_url,
    }


def _parse_atom_response(xml_text: str) -> list[dict]:
    """Parse the full Atom XML response into a list of paper dicts."""
    root = etree.fromstring(xml_text.encode("utf-8"))
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.xpath("//atom:entry", namespaces=ns)
    return [_parse_atom_entry(e, ns) for e in entries]


_HEADERS = {
    "User-Agent": "arXiv-Analyzer/1.0 (mailto:your@email.com)",
}


def _do_fetch(url: str) -> httpx.Response:
    """Single HTTP GET with status / Retry-After handling."""
    import time as _time
    resp = httpx.get(
        url, headers=_HEADERS, timeout=ARXIV_TIMEOUT,
        follow_redirects=True,
    )
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                delay = int(retry_after)
            except ValueError:
                delay = 30
            _time.sleep(delay)
    resp.raise_for_status()
    return resp


_fetch_with_retry = retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=5, min=5, max=60),
    reraise=True,
)(_do_fetch)


def search_arxiv(
    query: str,
    max_results: int = 50,
    start: int = 0,
    sort_by: SortBy = "relevance",
) -> list[PaperMeta]:
    """Search arXiv and return paper metadata, respecting rate limits.

    Handles pagination automatically when *max_results* exceeds the
    page size (100).
    """
    all_papers: list[PaperMeta] = []
    remaining = max_results

    while remaining > 0:
        page_size = min(remaining, ARXIV_PAGE_SIZE)

        # Build URL manually so '+' operators survive httpx's param encoding
        query_encoded = urllib.parse.quote(query, safe='+:()"')
        url = (
            f"{ARXIV_API_URL}?search_query={query_encoded}"
            f"&start={start + len(all_papers)}"
            f"&max_results={page_size}"
            f"&sortBy={sort_by}"
        )

        resp = _fetch_with_retry(url)
        resp.raise_for_status()

        entries = _parse_atom_response(resp.text)
        if not entries:
            break  # no more results

        for e in entries:
            all_papers.append(PaperMeta(**e))

        remaining -= len(entries)

        if len(entries) < page_size:
            break  # fewer returned than requested → last page

        if remaining > 0:
            time.sleep(ARXIV_RATE_LIMIT)

    return all_papers
