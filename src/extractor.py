"""DeepSeek API structured extraction for paper analysis."""

import json
import logging
import re

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    EXTRACTION_MAX_TOKENS,
    EXTRACTION_TEMPERATURE,
    MAX_RETRIES,
    MAX_TEXT_CHARS,
)
from .models import CSV_COLUMNS, FILL_NONE, PaperMeta

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a precise academic paper analyzer. Your task is to read a paper (full text or abstract) and extract structured information.

## Output Format
You MUST respond with ONLY valid JSON. No markdown, no code fences, no extra text.
The JSON object must have exactly these keys:

{
  "innovation": "string - the core novel contribution in 1-2 sentences",
  "method": "string - technical approach, architecture, or algorithm used",
  "experiments": "string - experimental setup, baselines, ablation design",
  "datasets": "string - datasets used for evaluation",
  "metrics": "string - evaluation metrics reported",
  "results": "string - key quantitative/qualitative findings",
  "limitations": "string - limitations, failure cases, or future work mentioned",
  "idea_tags": "string - semicolon-separated short hyphenated tags capturing the key technical ideas. Use lowercase-hyphenated format. Examples: retrieval-augmented-generation; efficient-finetuning; long-context; self-reflection; multi-agent-planning; synthetic-data; chain-of-thought; instruction-tuning; mixture-of-experts; knowledge-distillation",
  "evidence": "string - verbatim quotes or section references supporting the extraction",
  "confidence": "string - one of: high, medium, low"
}

## Tag Guidelines
- idea_tags is the MOST IMPORTANT field. Be specific and precise.
- Use lowercase-hyphenated format (e.g., retrieval-augmented-generation NOT RAG)
- Prefer specific over generic: use "rope-position-encoding" not "position-encoding"
- Include 3-8 tags that capture the paper's technical essence
- Each tag should be a well-known concept in ML/NLP/AI literature

## Rules
- If information is truly unavailable, use "none" for that field's value.
- For confidence: "high" = clearly stated in the paper, "medium" = reasonably inferred, "low" = largely guessed from abstract.
- evidence should contain direct quotes or section names where the information was found.
- Do NOT summarize the paper in general. Extract only the requested fields.
"""


def _build_client() -> OpenAI:
    return OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
    )


@retry(
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    reraise=True,
)
def _call_api(client: OpenAI, system: str, user: str) -> tuple[str, dict]:
    """Single API call with retry. Returns (content, usage_dict)."""
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=EXTRACTION_TEMPERATURE,
        max_tokens=EXTRACTION_MAX_TOKENS,
    )
    content = resp.choices[0].message.content
    usage = {}
    if resp.usage:
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens": resp.usage.total_tokens,
        }
    return (content.strip() if content else ""), usage


def _parse_json_response(raw: str) -> dict:
    """Try to parse JSON from API response, handling common failures."""
    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find JSON object with regex
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def _build_analysis_dict(
    meta: PaperMeta,
    extracted: dict,
) -> dict[str, str]:
    """Merge metadata with extracted fields into the CSV row format."""
    row: dict[str, str] = {
        "arxiv_id": meta.arxiv_id,
        "title": meta.title,
        "authors": "; ".join(meta.authors),
        "published": meta.published,
        "updated": meta.updated,
        "categories": "; ".join(meta.categories),
        "abstract": meta.abstract,
        "pdf_url": meta.pdf_url,
    }
    analysis_fields = [
        "innovation", "method", "experiments", "datasets",
        "metrics", "results", "limitations", "idea_tags",
        "evidence", "confidence",
    ]
    for f in analysis_fields:
        row[f] = extracted.get(f, FILL_NONE) or FILL_NONE

    return row


def _fallback_row(meta: PaperMeta) -> dict[str, str]:
    """Return a row with all analysis fields set to 'none'."""
    return _build_analysis_dict(meta, {})


def extract_from_paper(
    meta: PaperMeta,
    source_text: str,
    client: OpenAI | None = None,
) -> tuple[dict[str, str], dict]:
    """Analyse a single paper and return (CSV-ready row, usage_info).

    usage_info = {"total_tokens": int, ...} or {} on failure.
    """
    if client is None:
        client = _build_client()

    # Truncate long text
    if len(source_text) > MAX_TEXT_CHARS:
        truncated = source_text[:MAX_TEXT_CHARS]
        logger.debug(
            "Truncating text for %s: %d → %d chars",
            meta.arxiv_id, len(source_text), MAX_TEXT_CHARS,
        )
    else:
        truncated = source_text

    user_prompt = f"""## Paper Title
{meta.title}

## Paper Abstract
{meta.abstract}

## Paper Content
{truncated}"""

    try:
        raw, usage = _call_api(client, SYSTEM_PROMPT, user_prompt)
        extracted = _parse_json_response(raw)
        return _build_analysis_dict(meta, extracted), usage
    except json.JSONDecodeError:
        logger.warning(
            "JSON parse failed for %s, retrying with stricter prompt",
            meta.arxiv_id,
        )
        try:
            raw, usage = _call_api(
                client,
                SYSTEM_PROMPT
                + "\n\nCRITICAL: Output ONLY the JSON object. No other text.",
                user_prompt,
            )
            extracted = _parse_json_response(raw)
            return _build_analysis_dict(meta, extracted), usage
        except Exception:
            logger.error("Retry also failed for %s, filling none", meta.arxiv_id)
            return _fallback_row(meta), {}
    except Exception:
        logger.exception("Extraction failed for %s", meta.arxiv_id)
        return _fallback_row(meta), {}
