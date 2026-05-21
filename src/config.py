"""Central configuration loaded from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ── DeepSeek API ──────────────────────────────────────────────
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# ── Translation API ──────────────────────────────────────────────
TRANSLATE_BACKEND: str = os.getenv("TRANSLATE_BACKEND", "google")
# LLM
TRANSLATE_API_KEY: str = os.getenv("TRANSLATE_API_KEY", "") or DEEPSEEK_API_KEY
TRANSLATE_BASE_URL: str = os.getenv("TRANSLATE_BASE_URL", "") or DEEPSEEK_BASE_URL
TRANSLATE_MODEL: str = os.getenv("TRANSLATE_MODEL", "deepseek-chat")
# Bing
BING_API_KEY: str = os.getenv("BING_API_KEY", "")
BING_REGION: str = os.getenv("BING_REGION", "global")
# DeepL
DEEPL_API_KEY: str = os.getenv("DEEPL_API_KEY", "")
# 百度
BAIDU_APPID: str = os.getenv("BAIDU_APPID", "")
BAIDU_SECRET_KEY: str = os.getenv("BAIDU_SECRET_KEY", "")
# 腾讯
TENCENT_SECRET_ID: str = os.getenv("TENCENT_SECRET_ID", "")
TENCENT_SECRET_KEY: str = os.getenv("TENCENT_SECRET_KEY", "")
TENCENT_REGION: str = os.getenv("TENCENT_REGION", "ap-guangzhou")
# Custom
CUSTOM_TRANSLATE_URL: str = os.getenv("CUSTOM_TRANSLATE_URL", "")
CUSTOM_TRANSLATE_API_KEY: str = os.getenv("CUSTOM_TRANSLATE_API_KEY", "")

# ── arXiv API ─────────────────────────────────────────────────
ARXIV_API_URL: str = "http://export.arxiv.org/api/query"
ARXIV_RATE_LIMIT: float = 3.1       # seconds between requests
ARXIV_PAGE_SIZE: int = 100           # arXiv max per page
ARXIV_TIMEOUT: int = 60              # HTTP timeout seconds

# ── Paths ─────────────────────────────────────────────────────
PDF_DIR: Path = BASE_DIR / "outputs" / "pdfs"
CSV_PATH: Path = BASE_DIR / "outputs" / "arxiv_analysis.csv"
IDEA_FREQ_PATH: Path = BASE_DIR / "outputs" / "idea_frequency.csv"
IDEA_CLUSTER_PATH: Path = BASE_DIR / "outputs" / "idea_clusters.csv"
LOG_FILE: Path = BASE_DIR / "logs" / "pipeline.log"

# ── Processing ────────────────────────────────────────────────
MAX_RETRIES: int = 3
MAX_TEXT_CHARS: int = 24000          # ~6k tokens, leave room for response
EXTRACTION_TEMPERATURE: float = 0.0
EXTRACTION_MAX_TOKENS: int = 4096

# ── Clustering ────────────────────────────────────────────────
CLUSTER_SIMILARITY_THRESHOLD: float = 0.7


def validate() -> None:
    """Raise if required configuration is missing."""
    if not DEEPSEEK_API_KEY:
        raise RuntimeError(
            "DEEPSEEK_API_KEY is not set. "
            "Copy .env.example to .env and fill in your key."
        )
