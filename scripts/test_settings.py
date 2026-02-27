#!/usr/bin/env python3
import sys
from pathlib import Path

# Agregar src al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config.settings import get_settings

settings = get_settings()
print(f"Directorio actual: {Path.cwd()}")
print(f"SRI_CERT_PATH: {settings.sri_cert_path}")
print(f"SRI_RUC: {settings.sri_ruc}")
print(f"SUPABASE_URL: {settings.supabase_url}")
