"""Data structures shared across modules."""

from dataclasses import dataclass, field


@dataclass
class PaperMeta:
    """Raw metadata returned from arXiv search."""
    arxiv_id: str
    title: str
    authors: list[str]
    published: str
    updated: str
    categories: list[str]
    abstract: str
    pdf_url: str


# CSV columns in order
CSV_COLUMNS: list[str] = [
    "arxiv_id",
    "title",
    "authors",
    "published",
    "updated",
    "categories",
    "abstract",
    "pdf_url",
    "innovation",
    "method",
    "experiments",
    "datasets",
    "metrics",
    "results",
    "limitations",
    "idea_tags",
    "evidence",
    "confidence",
]

FILL_NONE = "none"
