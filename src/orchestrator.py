"""Pipeline orchestrator: wires search → download → parse → extract → stats."""

import argparse
import logging
import sys
import time
from pathlib import Path

from .config import (
    CSV_PATH,
    DEEPSEEK_MODEL,
    EXTRACTION_TEMPERATURE,
    PDF_DIR,
    validate,
)
from .csv_writer import append_row, init_csv, read_all_rows, read_existing_ids
from .downloader import download_pdf
from .extractor import _build_client, extract_from_paper
from .models import CSV_COLUMNS, FILL_NONE, PaperMeta
from .parser import parse_paper
from .searcher import build_query, search_arxiv
from .stats import write_stats

logger = logging.getLogger("arxiv_analyzer")


# ── CLI ────────────────────────────────────────────────────────

def _setup_logging(verbose: bool, log_file: Path) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(level)
    ch.setFormatter(fmt)

    root = logging.getLogger("arxiv_analyzer")
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    root.addHandler(fh)
    root.addHandler(ch)


def _make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="arxiv-analyzer",
        description="Search arXiv, download & parse PDFs, extract insights with DeepSeek.",
    )
    subs = p.add_subparsers(dest="command", help="Pipeline step to run")

    # ── run (full pipeline) ──
    run = subs.add_parser("run", help="Run the full pipeline")
    _add_common_args(run)
    run.add_argument("--no-download", action="store_true",
                     help="Skip PDF download, use abstracts only")
    run.add_argument("--no-resume", action="store_true",
                     help="Re-process papers already in CSV")

    # ── search only ──
    srch = subs.add_parser("search", help="Search arXiv and print metadata")
    _add_common_args(srch)

    # ── stats only ──
    st = subs.add_parser("stats", help="Compute stats from existing CSV")
    st.add_argument("-o", "--output", default=str(CSV_PATH),
                    help="CSV file to read")

    return p


def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("-q", "--query", nargs="+", required=True,
                   help="Search keywords (space-separated)")
    p.add_argument("-f", "--field", nargs="+",
                   choices=["ti", "abs", "au", "cat"],
                   default=["ti", "abs"],
                   help="Fields to search (default: ti abs)")
    p.add_argument("--operator", choices=["AND", "OR", "ANDNOT"], default="AND")
    p.add_argument("-d", "--date-range", nargs=2, metavar=("FROM", "TO"),
                   help="submittedDate range YYYYMMDD[HHMM] YYYYMMDD[HHMM]")
    p.add_argument("-n", "--max-results", type=int, default=50)
    p.add_argument("--sort-by", choices=["relevance", "lastUpdatedDate", "submittedDate"],
                   default="relevance")
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--pdf-dir", default=str(PDF_DIR))
    p.add_argument("-o", "--output", default=str(CSV_PATH),
                   help="CSV output path")
    p.add_argument("--model", default=DEEPSEEK_MODEL)
    p.add_argument("--temperature", type=float, default=EXTRACTION_TEMPERATURE)
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--dry-run", action="store_true",
                   help="Show query and exit without making API calls")


# ── Pipeline steps ─────────────────────────────────────────────

def _step_search(args: argparse.Namespace) -> list[PaperMeta]:
    query = build_query(
        keywords=args.query,
        fields=args.field,
        date_range=tuple(args.date_range) if args.date_range else None,
        operator=args.operator,
    )
    logger.info("arXiv query: %s", query)

    if args.dry_run:
        logger.info("[dry-run] Would search with max_results=%d, sort_by=%s",
                    args.max_results, args.sort_by)
        return []

    papers = search_arxiv(
        query=query,
        max_results=args.max_results,
        start=args.start,
        sort_by=args.sort_by,
    )
    logger.info("Found %d papers", len(papers))
    for p in papers:
        logger.debug("  %s  %s", p.arxiv_id, p.title[:80])
    return papers


def _step_download(
    papers: list[PaperMeta],
    pdf_dir: Path,
    no_download: bool,
) -> list[Path | None]:
    if no_download:
        logger.info("--no-download set, skipping PDF downloads")
        return [None] * len(papers)

    paths: list[Path | None] = []
    success = 0
    for p in papers:
        pp = download_pdf(p.arxiv_id, p.pdf_url, output_dir=pdf_dir)
        paths.append(pp)
        if pp:
            success += 1
    logger.info("PDF download: %d/%d succeeded", success, len(papers))
    return paths


def _step_parse(
    papers: list[PaperMeta],
    pdf_dir: Path,
) -> list[tuple[str | None, str]]:
    """Returns list of (full_text_or_None, source_text)."""
    results: list[tuple[str | None, str]] = []
    full_ok = 0
    for p in papers:
        ft, st = parse_paper(p, pdf_dir=pdf_dir)
        results.append((ft, st))
        if ft:
            full_ok += 1
    logger.info("PDF parse: %d/%d have full text", full_ok, len(papers))
    return results


def _step_extract(
    papers: list[PaperMeta],
    source_texts: list[tuple[str | None, str]],
    csv_path: Path,
    args: argparse.Namespace,
) -> int:
    """Extract analysis for each paper, writing incrementally to CSV.

    Returns the number of newly-processed papers.
    """
    init_csv(csv_path)

    if not args.no_resume:
        existing = read_existing_ids(csv_path)
        logger.info("Resume: %d papers already in CSV, will skip", len(existing))
    else:
        existing = set()

    client = _build_client()
    processed = 0

    for meta, (full_text, source) in zip(papers, source_texts):
        if meta.arxiv_id in existing:
            logger.debug("Skipping %s (already in CSV)", meta.arxiv_id)
            continue

        # Throttle before each API call
        time.sleep(1.0)

        logger.info("Analysing %s ...", meta.arxiv_id)
        row, usage = extract_from_paper(meta, source, client=client)
        append_row(csv_path, row)

        confidence = row.get("confidence", FILL_NONE)
        has_full = "fulltext" if full_text else "abstract"
        logger.info(
            "  → %s  confidence=%s  source=%s  tags=%s",
            meta.arxiv_id, confidence, has_full,
            row.get("idea_tags", "")[:80],
        )
        processed += 1

    return processed


def _step_stats(csv_path: Path) -> None:
    rows = read_all_rows(csv_path)
    if not rows:
        logger.warning("No rows in CSV, skipping stats")
        return
    freq_df, cluster_df = write_stats(rows)
    logger.info(
        "Stats written: %d unique tags, %d clusters",
        len(freq_df), len(cluster_df),
    )


# ── Main entry ─────────────────────────────────────────────────

def run_pipeline(args: argparse.Namespace) -> int:
    """Execute the pipeline as specified by CLI args."""
    from .config import LOG_FILE

    log_file = Path(args.output).parent.parent / "logs" / "pipeline.log"
    _setup_logging(args.verbose, log_file)

    dry_run = getattr(args, "dry_run", False)
    pdf_dir = Path(args.pdf_dir)

    if args.command == "stats":
        _step_stats(Path(args.output))
        return 0

    if args.command == "search":
        # Search doesn't need DeepSeek key
        papers = _step_search(args)
        if not papers:
            return 1 if not dry_run else 0
        print(f"\nFound {len(papers)} papers:\n")
        for p in papers:
            print(f"  {p.arxiv_id}  {p.published[:10]}  {p.title[:100]}")
            print(f"    authors: {', '.join(p.authors[:3])}")
            print(f"    categories: {', '.join(p.categories)}")
            print()
        return 0

    # For 'run' command, validate API key
    if not dry_run:
        try:
            validate()
        except RuntimeError as e:
            logger.error("Configuration error: %s", e)
            return 2

    # ── Search ──
    papers = _step_search(args)
    if not papers:
        if not dry_run:
            logger.warning("No papers found. Try broader keywords.")
        return 1 if not dry_run else 0

    # ── Download ──
    pdf_paths = _step_download(papers, pdf_dir, getattr(args, "no_download", False))

    # ── Parse ──
    source_texts = _step_parse(papers, pdf_dir)

    # ── Extract ──
    csv_path = Path(args.output)
    processed = _step_extract(papers, source_texts, csv_path, args)

    # ── Stats ──
    _step_stats(csv_path)

    # ── Summary ──
    full_count = sum(1 for ft, _ in source_texts if ft)
    print(f"\n{'='*60}")
    print(f"Pipeline complete.")
    print(f"  Papers found:    {len(papers)}")
    print(f"  Full-text:       {full_count}")
    print(f"  Abstract-only:   {len(papers) - full_count}")
    print(f"  Newly analysed:  {processed}")
    print(f"  CSV:             {csv_path}")
    print(f"{'='*60}")

    return 0


def main() -> None:
    # Fix Unicode on Windows consoles
    import codecs
    if sys.platform == "win32":
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")

    parser = _make_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)
    sys.exit(run_pipeline(args))


if __name__ == "__main__":
    main()
