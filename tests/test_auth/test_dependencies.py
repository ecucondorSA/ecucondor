"""
Tests para el módulo de autenticación API Key.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from src.auth.dependencies import verify_api_key


# ============================================================
# Helpers
# ============================================================


def _make_settings(auth_enabled: bool = True, api_key_secret: str = "test-key-32chars-mínimo-seguro!!"):
    """Crea un mock de Settings con los campos de auth."""
    settings = MagicMock()
    settings.auth_enabled = auth_enabled
    settings.api_key_secret = api_key_secret
    return settings


def _make_credentials(token: str) -> HTTPAuthorizationCredentials:
    """Crea credenciales Bearer de prueba."""
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


# ============================================================
# Auth deshabilitado
# ============================================================


class TestAuthDisabled:
    """Cuando auth_enabled=False, todo pasa sin validar."""

    @pytest.mark.anyio
    async def test_sin_credentials_permite_acceso(self):
        settings = _make_settings(auth_enabled=False)
        result = await verify_api_key(credentials=None, settings=settings)
        assert result is True

    @pytest.mark.anyio
    async def test_con_key_invalido_permite_acceso(self):
        settings = _make_settings(auth_enabled=False)
        creds = _make_credentials("cualquier-cosa")
        result = await verify_api_key(credentials=creds, settings=settings)
        assert result is True


# ============================================================
# Auth habilitado - API Key válido
# ============================================================


class TestAuthValidKey:
    """Con auth_enabled=True y API Key correcto."""

    @pytest.mark.anyio
    async def test_key_valido_permite_acceso(self):
        secret = "mi-api-key-super-seguro-de-32chars"
        settings = _make_settings(api_key_secret=secret)
        creds = _make_credentials(secret)
        result = await verify_api_key(credentials=creds, settings=settings)
        assert result is True


# ============================================================
# Auth habilitado - Errores
# ============================================================


class TestAuthErrors:
    """Con auth_enabled=True, errores de autenticación."""

    @pytest.mark.anyio
    async def test_sin_credentials_retorna_401(self):
        settings = _make_settings()
        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(credentials=None, settings=settings)
        assert exc_info.value.status_code == 401

    @pytest.mark.anyio
    async def test_key_invalido_retorna_401(self):
        settings = _make_settings(api_key_secret="clave-correcta-xxxxxxxxxxxxxxxxx")
        creds = _make_credentials("clave-incorrecta-xxxxxxxxxxxxxxx")
        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(credentials=creds, settings=settings)
        assert exc_info.value.status_code == 401

    @pytest.mark.anyio
    async def test_key_vacio_en_servidor_retorna_500(self):
        """Si auth está habilitado pero no se configuró api_key_secret."""
        settings = _make_settings(api_key_secret="")
        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(credentials=None, settings=settings)
        assert exc_info.value.status_code == 500

    @pytest.mark.anyio
    async def test_mensaje_401_incluye_instrucciones(self):
        settings = _make_settings()
        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(credentials=None, settings=settings)
        assert "Authorization" in exc_info.value.detail
        assert "Bearer" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_timing_safe_comparison(self):
        """Verifica que no acepta keys parcialmente correctos."""
        secret = "abcdefghijklmnopqrstuvwxyz123456"
        settings = _make_settings(api_key_secret=secret)
        # Key con un solo caracter diferente
        creds = _make_credentials("abcdefghijklmnopqrstuvwxyz123457")
        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(credentials=creds, settings=settings)
        assert exc_info.value.status_code == 401
