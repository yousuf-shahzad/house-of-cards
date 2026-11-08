"""Runtime settings, read once from environment variables (see backend/.env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_ORDER = ("tickerinside", "ishares", "sec_nport")
DEFAULT_USER_AGENT = "HouseOfCards-PoC/0.1 (hackathon prototype)"
DEFAULT_CORS = ("http://127.0.0.1:5173", "http://localhost:5173")
DEFAULT_EXTRACTOR_MODEL = "gemini-3.8-flash"
DEFAULT_ORCHESTRATOR_MODEL = "gemini-4-argon"
DEFAULT_DEPS_TOP_N = 15
DEFAULT_DEPS_REVERSE_LIMIT = 3


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int, *, low: int, high: int) -> int:
    try:
        number = int((value or "").strip())
    except ValueError:
        return default
    return number if low <= number <= high else default


def _csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    items = tuple(part.strip() for part in (value or "").split(",") if part.strip())
    return items or default


@dataclass(frozen=True)
class Settings:
    cache_dir: Path = BACKEND_DIR / ".cache"
    offline: bool = False
    source_order: tuple[str, ...] = DEFAULT_SOURCE_ORDER
    user_agent: str = DEFAULT_USER_AGENT
    sec_contact: str | None = None
    openfigi_key: str | None = None
    cors_origins: tuple[str, ...] = field(default=DEFAULT_CORS)
    # v2 AI dependency analysis. The key is a secret: never logged, never in a URL or cache entry.
    gemini_api_key: str | None = field(default=None, repr=False)
    gemini_extractor_model: str = DEFAULT_EXTRACTOR_MODEL
    gemini_orchestrator_model: str = DEFAULT_ORCHESTRATOR_MODEL
    deps_top_n: int = DEFAULT_DEPS_TOP_N
    deps_reverse_limit: int = DEFAULT_DEPS_REVERSE_LIMIT
    """Other filers' documents searched per company for reverse links (0 = reverse links off)."""

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ if env is None else env)
        cache = env.get("HOC_CACHE_DIR", "").strip()
        return cls(
            cache_dir=Path(cache).expanduser() if cache else BACKEND_DIR / ".cache",
            offline=_flag(env.get("HOC_OFFLINE")),
            source_order=_csv(env.get("HOC_SOURCE_ORDER"), DEFAULT_SOURCE_ORDER),
            user_agent=env.get("HOC_USER_AGENT", "").strip() or DEFAULT_USER_AGENT,
            sec_contact=env.get("HOC_SEC_CONTACT", "").strip() or None,
            openfigi_key=env.get("HOC_OPENFIGI_KEY", "").strip() or None,
            cors_origins=_csv(env.get("HOC_CORS_ORIGINS"), DEFAULT_CORS),
            gemini_api_key=(env.get("GEMINI_API_KEY", "").strip() or env.get("GOOGLE_API_KEY", "").strip()
                            or None),
            gemini_extractor_model=env.get("HOC_GEMINI_EXTRACTOR_MODEL", "").strip() or DEFAULT_EXTRACTOR_MODEL,
            gemini_orchestrator_model=(env.get("HOC_GEMINI_ORCHESTRATOR_MODEL", "").strip()
                                       or DEFAULT_ORCHESTRATOR_MODEL),
            deps_top_n=_int(env.get("HOC_DEPS_TOP_N"), DEFAULT_DEPS_TOP_N, low=1, high=30),
            deps_reverse_limit=_int(env.get("HOC_DEPS_REVERSE_LIMIT"), DEFAULT_DEPS_REVERSE_LIMIT,
                                    low=0, high=10),
        )
