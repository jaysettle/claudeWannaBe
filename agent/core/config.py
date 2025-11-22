"""
Configuration loader for the local agent.
Loads settings from settings.toml, environment overrides, and defaults.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


DEFAULT_BASE_URL = "http://192.168.3.142:11434/v1"
DEFAULT_MODEL = "gpt-oss:20b"


@dataclass
class Settings:
    base_url: str = DEFAULT_BASE_URL
    api_key: str = "ollama"  # placeholder required by OpenAI client
    model: str = DEFAULT_MODEL
    embed_model: str = "gpt-oss:20b"
    workspace: Path = Path.cwd()
    safety_strict: bool = True
    data_dir: Path = Path("data")
    log_level: str = "INFO"


def load_settings(config_path: Path | None = None) -> Settings:
    config_file = config_path or Path("config/settings.toml")
    data = {}
    if config_file.exists():
        with config_file.open("rb") as f:
            data = tomllib.load(f)

    base_url = os.getenv("JAY_BASE_URL", data.get("base_url", DEFAULT_BASE_URL))
    model = os.getenv("JAY_MODEL", data.get("model", DEFAULT_MODEL))
    embed_model = os.getenv("JAY_EMBED_MODEL", data.get("embed_model", "gpt-oss:20b"))
    safety_strict = os.getenv("JAY_SAFETY_STRICT", str(data.get("safety_strict", "true"))).lower() == "true"
    workspace = Path(os.getenv("JAY_WORKSPACE", data.get("workspace", Path.cwd())))
    data_dir = Path(os.getenv("JAY_DATA_DIR", data.get("data_dir", "data")))
    log_level = os.getenv("JAY_LOG_LEVEL", data.get("log_level", "INFO"))

    return Settings(
        base_url=base_url,
        api_key=os.getenv("JAY_API_KEY", data.get("api_key", "ollama")),
        model=model,
        embed_model=embed_model,
        workspace=workspace,
        safety_strict=safety_strict,
        data_dir=data_dir,
        log_level=log_level,
    )
