# ECUCONDOR - Sistema de Contabilidad Automatizada
# Dockerfile para Python API con soporte SRI

FROM python:3.12-slim

# Evitar prompts interactivos
ENV DEBIAN_FRONTEND=noninteractive

# Variables de entorno Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema necesarias para:
# - lxml (libxml2, libxslt)
# - cryptography (libffi, openssl)
# - weasyprint (cairo, pango, gdk-pixbuf)
# - zeep SOAP client
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Compilación
    build-essential \
    gcc \
    # XML/XSLT para lxml
    libxml2-dev \
    libxslt1-dev \
    # Criptografía
    libffi-dev \
    libssl-dev \
    # WeasyPrint para PDF
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-xlib-2.0-0 \
    libffi-dev \
    shared-mime-info \
    # Fuentes para PDF
    fonts-liberation \
    fonts-dejavu-core \
    # Utilidades
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copiar requirements primero para cache de Docker
COPY requirements.txt .

# Instalar dependencias Python
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copiar código fuente
COPY src/ ./src/
COPY pyproject.toml ./

# Crear directorio para certificados (se monta como volumen)
RUN mkdir -p /app/certs && chmod 700 /app/certs

# Usuario no-root para seguridad
RUN useradd -m -u 1000 ecucondor && \
    chown -R ecucondor:ecucondor /app
USER ecucondor

# Puerto de la API
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Comando por defecto
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
