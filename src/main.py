"""
ECUCONDOR - Entry Point FastAPI
Sistema de Contabilidad Automatizada para SAS Unipersonal - Ecuador
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config.settings import get_settings

# Configurar logging estructurado
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestión del ciclo de vida de la aplicación."""
    settings = get_settings()

    logger.info(
        "Iniciando ECUCONDOR",
        environment=settings.environment,
        sri_ambiente="Pruebas" if settings.sri_ambiente == "1" else "Producción",
        ruc=settings.sri_ruc,
    )

    # Aquí se pueden inicializar conexiones, cargar cache, etc.

    yield

    # Cleanup al cerrar
    logger.info("Cerrando ECUCONDOR")


# Crear aplicación FastAPI
app = FastAPI(
    title="ECUCONDOR API",
    description="""
    Sistema de Contabilidad Automatizada para SAS Unipersonal - Ecuador.

    ## Funcionalidades

    * **Facturación Electrónica SRI** - Emisión de comprobantes con firma digital XAdES-BES
    * **Ledger Contable** - Libro mayor con partida doble y catálogo NIIF
    * **Cumplimiento UAFE** - Monitoreo y reportes anti-lavado (RESU/ROII)
    * **Gestión de Honorarios** - Control de pagos al administrador (IESS código 109)
    * **Conciliación Bancaria** - Procesamiento de extractos CSV
    """,
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, restringir a dominios específicos
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== MIDDLEWARE DE LOGGING =====
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log de todas las peticiones HTTP."""
    start_time = datetime.now(timezone.utc)

    response = await call_next(request)

    process_time = (datetime.now(timezone.utc) - start_time).total_seconds()

    logger.info(
        "HTTP Request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        process_time=f"{process_time:.3f}s",
    )

    return response


# ===== HANDLERS DE ERRORES =====
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Manejador global de excepciones."""
    logger.error(
        "Unhandled exception",
        path=request.url.path,
        error=str(exc),
        exc_info=True,
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": "Ha ocurrido un error interno. Por favor, intente más tarde.",
        },
    )


# ===== ENDPOINTS BASE =====
@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    """Endpoint raíz."""
    return {
        "service": "ECUCONDOR API",
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, Any]:
    """
    Health check para monitoreo y orquestadores.

    Verifica:
    - Estado de la aplicación
    - Conexión a Supabase (pendiente)
    - Certificado SRI disponible (pendiente)
    """
    settings = get_settings()

    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": settings.environment,
        "sri": {
            "ambiente": "pruebas" if settings.sri_ambiente == "1" else "produccion",
            "ruc": settings.sri_ruc,
        },
        "checks": {
            "api": True,
            "database": None,  # TODO: Verificar conexión Supabase
            "certificate": None,  # TODO: Verificar certificado .p12
        },
    }


@app.get("/info", tags=["Info"])
async def info() -> dict[str, Any]:
    """Información de configuración (solo datos no sensibles)."""
    settings = get_settings()

    return {
        "empresa": {
            "ruc": settings.sri_ruc,
            "razon_social": settings.sri_razon_social,
            "nombre_comercial": settings.sri_nombre_comercial,
            "obligado_contabilidad": settings.sri_obligado_contabilidad,
        },
        "sri": {
            "ambiente": "Pruebas" if settings.sri_ambiente == "1" else "Producción",
            "establecimiento": settings.sri_establecimiento,
            "punto_emision": settings.sri_punto_emision,
        },
        "modelo_negocio": {
            "comision_porcentaje": settings.comision_porcentaje,
            "iva_porcentaje": settings.iva_porcentaje,
        },
        "uafe": {
            "umbral_resu": settings.uafe_umbral_resu,
        },
    }


# ===== IMPORTAR ROUTERS =====
from src.api.v1.router import router as api_v1_router
from src.dashboard import router as dashboard_router

# Incluir router principal de la API v1
app.include_router(api_v1_router, prefix="/api/v1")

# Dashboard web
app.include_router(dashboard_router, prefix="/dashboard", tags=["Dashboard"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
