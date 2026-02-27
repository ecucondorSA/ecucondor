#!/usr/bin/env python3
from pathlib import Path

# Verificar archivo .env
base_dir = Path(__file__).resolve().parent.parent
env_file = base_dir / ".env"

print(f"BASE_DIR: {base_dir}")
print(f"ENV_FILE: {env_file}")
print(f"Exists: {env_file.exists()}")
print(f"Is file: {env_file.is_file()}")
print(f"Readable: {env_file.exists() and env_file.is_file()}")

if env_file.exists():
    with open(env_file) as f:
        lines = f.readlines()
        sri_lines = [l for l in lines if l.startswith('SRI')]
        print("\nVariables SRI en .env:")
        for line in sri_lines[:10]:
            print(f"  {line.strip()}")
