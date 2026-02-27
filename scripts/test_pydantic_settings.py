#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

print(f"ENV_FILE: {ENV_FILE}")
print(f"Exists: {ENV_FILE.exists()}")

class TestSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    sri_ruc: str = "default"
    sri_cert_path: str = "default"

s = TestSettings()
print(f"\nsri_ruc: {s.sri_ruc}")
print(f"sri_cert_path: {s.sri_cert_path}")
