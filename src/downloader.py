"""PDF downloader with resume and retry."""

import time
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import ARXIV_RATE_LIMIT, ARXIV_TIMEOUT, MAX_RETRIES, PDF_DIR


@retry(
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=3, min=3, max=45),
    reraise=True,
)
def _do_download(url: str, dest: Path, timeout: int) -> None:
    """Single download with retry."""
    with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as resp:
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=65536):
                f.write(chunk)


def download_pdf(
    arxiv_id: str,
    pdf_url: str,
    output_dir: Path | None = None,
    timeout: int = ARXIV_TIMEOUT,
    skip_existing: bool = True,
) -> Path | None:
    """Download a paper PDF, returning the local path or ``None``.

    Args:
        arxiv_id: e.g. ``"2301.12345v1"``.
        pdf_url: The full PDF URL from arXiv metadata.
        output_dir: Directory to save the PDF.  Defaults to *PDF_DIR*.
        timeout: HTTP timeout in seconds.
        skip_existing: If ``True`` and the file already exists, skip
            download and return the existing path immediately.

    Returns:
        Path to the saved PDF, or ``None`` if *pdf_url* is empty or
        download failed.
    """
    if not pdf_url:
        return None

    dest_dir = output_dir or PDF_DIR
    dest = dest_dir / f"{arxiv_id}.pdf"

    if skip_existing and dest.exists():
        return dest

    try:
        _do_download(pdf_url, dest, timeout)
        return dest
    except Exception:
        # Remove partial file on failure
        if dest.exists():
            dest.unlink()
        return None
    finally:
        time.sleep(ARXIV_RATE_LIMIT)


def download_batch(
    papers: list[dict],
    output_dir: Path | None = None,
    skip_existing: bool = True,
) -> list[Path | None]:
    """Download PDFs for a list of paper dicts.

    Returns a list of local paths (or ``None`` for failures) in the
    same order as the input.
    """
    paths: list[Path | None] = []
    for p in papers:
        path = download_pdf(
            arxiv_id=p["arxiv_id"],
            pdf_url=p.get("pdf_url", ""),
            output_dir=output_dir,
            skip_existing=skip_existing,
        )
        paths.append(path)
    return paths
