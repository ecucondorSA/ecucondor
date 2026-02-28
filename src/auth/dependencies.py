"""
ECUCONDOR - Dependencias de Autenticación para FastAPI
Implementa validación de API Key via header Authorization: Bearer <key>.
"""

import secrets

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.config.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> bool:
    """
    Valida el API Key del header Authorization: Bearer <key>.

    Si auth_enabled=False (development), permite acceso sin key.
    En producción requiere api_key_secret configurado y válido.

    Raises:
        HTTPException 401: Si el key es inválido o ausente
        HTTPException 500: Si auth está habilitado pero no configurado
    """
    if not settings.auth_enabled:
        return True

    if not settings.api_key_secret:
        logger.error("auth_enabled=True pero api_key_secret no configurado")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Autenticación habilitada pero API Key no configurado en el servidor",
        )

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key requerido. Usar header: Authorization: Bearer <api_key>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not secrets.compare_digest(credentials.credentials, settings.api_key_secret):
        logger.warning("Intento de acceso con API Key inválido")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return True
