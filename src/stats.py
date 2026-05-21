"""Idea tag frequency statistics and clustering."""

import re
from collections import Counter
from pathlib import Path

import pandas as pd
import textdistance

from .config import CLUSTER_SIMILARITY_THRESHOLD, IDEA_CLUSTER_PATH, IDEA_FREQ_PATH

TAG_SEP = re.compile(r"\s*;\s*")


def _parse_tags(raw: str) -> list[str]:
    """Split a semicolon-separated tag string into clean individual tags."""
    tags = TAG_SEP.split(str(raw))
    return [t.strip().lower() for t in tags if t.strip() and t.strip().lower() != "none"]


def compute_frequency(rows: list[dict]) -> pd.DataFrame:
    """Compute tag frequency from analysis rows.

    Returns a DataFrame with columns: tag, count, paper_ids.
    """
    tag_papers: dict[str, list[str]] = {}
    for row in rows:
        arxiv_id = row.get("arxiv_id", "")
        for tag in _parse_tags(row.get("idea_tags", "")):
            tag_papers.setdefault(tag, []).append(arxiv_id)

    counts = Counter({t: len(ids) for t, ids in tag_papers.items()})
    freq = pd.DataFrame(
        [
            {"tag": tag, "count": cnt, "paper_ids": "; ".join(tag_papers[tag])}
            for tag, cnt in counts.most_common()
        ]
    )
    return freq


def cluster_tags(rows: list[dict]) -> pd.DataFrame:
    """Group similar idea tags using edit-distance-based greedy clustering.

    Returns a DataFrame with columns: cluster_id, canonical_tag,
    member_tags, total_count.
    """
    freq_df = compute_frequency(rows)
    if freq_df.empty:
        return pd.DataFrame(columns=["cluster_id", "canonical_tag", "member_tags", "total_count"])

    # Sort tags by count descending so most frequent becomes canonical
    tags_sorted: list[tuple[str, int]] = list(
        zip(freq_df["tag"].tolist(), freq_df["count"].tolist())
    )

    clusters: list[dict] = []
    assigned: set[str] = set()
    cluster_id = 0

    for tag, count in tags_sorted:
        if tag in assigned:
            continue

        cluster_id += 1
        members: list[tuple[str, int]] = [(tag, count)]
        assigned.add(tag)

        for other_tag, other_count in tags_sorted:
            if other_tag in assigned:
                continue
            # Check similarity against all current members
            if any(
                textdistance.jaccard.normalized_similarity(m[0], other_tag)
                >= CLUSTER_SIMILARITY_THRESHOLD
                for m in members
            ):
                members.append((other_tag, other_count))
                assigned.add(other_tag)

        total = sum(c for _, c in members)
        clusters.append({
            "cluster_id": cluster_id,
            "canonical_tag": tag,
            "member_tags": "; ".join(m[0] for m in members),
            "total_count": total,
        })

    return pd.DataFrame(clusters)


def write_stats(
    rows: list[dict],
    freq_path: Path | None = None,
    cluster_path: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute stats and write CSV files.

    Returns ``(freq_df, cluster_df)``.
    """
    freq_path = freq_path or IDEA_FREQ_PATH
    cluster_path = cluster_path or IDEA_CLUSTER_PATH

    freq_df = compute_frequency(rows)
    cluster_df = cluster_tags(rows)

    freq_path.parent.mkdir(parents=True, exist_ok=True)
    freq_df.to_csv(freq_path, index=False, quoting=1)  # QUOTE_ALL
    cluster_df.to_csv(cluster_path, index=False, quoting=1)

    return freq_df, cluster_df
