from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
EXPORT_DIR = ROOT_DIR / "exports"
CACHE_DIR = DATA_DIR / "cache"
RUNS_DIR = DATA_DIR / "runs"
TEMPLATES_DIR = DATA_DIR / "templates"


@dataclass(frozen=True)
class AppConfig:
    app_name: str = "Competitive AI Research Platform"
    data_dir: Path = DATA_DIR
    export_dir: Path = EXPORT_DIR
    cache_dir: Path = CACHE_DIR
    runs_dir: Path = RUNS_DIR
    templates_dir: Path = TEMPLATES_DIR
    request_timeout_seconds: int = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "25"))
    playwright_timeout_ms: int = int(os.getenv("PLAYWRIGHT_TIMEOUT_MS", "45000"))
    max_source_chars: int = int(os.getenv("MAX_SOURCE_CHARS", "120000"))
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "12000"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "800"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    llm_provider: str = os.getenv("LLM_PROVIDER", "auto")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    yandex_api_key: str = os.getenv("YANDEX_API_KEY", "")
    yandex_folder: str = os.getenv("YANDEX_FOLDER", "")
    yandex_model: str = os.getenv("YANDEX_MODEL", "gpt-oss-120b/latest")
    yandex_base_url: str = os.getenv("YANDEX_BASE_URL", "https://ai.api.cloud.yandex.net/v1")


def ensure_directories(config: AppConfig) -> None:
    for path in [config.data_dir, config.export_dir, config.cache_dir, config.runs_dir, config.templates_dir]:
        path.mkdir(parents=True, exist_ok=True)
