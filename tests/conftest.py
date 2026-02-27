"""
ECUCONDOR - Configuración de Pytest
Fixtures compartidos para todos los tests.
"""

import os
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


# Configurar variables de entorno para tests
@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """Configura variables de entorno para los tests."""
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
    os.environ.setdefault("SUPABASE_KEY", "test-key")
    os.environ.setdefault("SRI_RUC", "1792535500001")
    os.environ.setdefault("SRI_RAZON_SOCIAL", "EMPRESA TEST SAS")
    os.environ.setdefault("SRI_DIRECCION_MATRIZ", "Quito, Ecuador")
    os.environ.setdefault("SRI_CERT_PASSWORD", "test-password")
    os.environ.setdefault("SRI_AMBIENTE", "1")


@pytest.fixture
def sample_factura_data():
    """Datos de ejemplo para una factura."""
    return {
        "cliente": {
            "tipo_identificacion": "04",
            "identificacion": "1792535500001",
            "razon_social": "CLIENTE TEST",
            "direccion": "Av. Test 123",
            "email": "cliente@test.com",
        },
        "items": [
            {
                "codigo": "SERV001",
                "descripcion": "Servicio de comisión",
                "cantidad": Decimal("1"),
                "precio_unitario": Decimal("100.00"),
                "aplica_iva": True,
                "porcentaje_iva": Decimal("15"),
            }
        ],
        "forma_pago": "20",
    }


@pytest.fixture
def sample_clave_acceso():
    """Clave de acceso de ejemplo para tests."""
    from src.sri.access_key import generar_clave_acceso

    return generar_clave_acceso(
        fecha_emision=date(2024, 1, 15),
        tipo_comprobante="01",
        ruc="1792535500001",
        ambiente="1",
        establecimiento="001",
        punto_emision="001",
        secuencial=1,
        codigo_numerico="12345678",
    )


@pytest.fixture
def mock_sri_client():
    """Mock del cliente SRI para tests sin conexión real."""
    with patch("src.sri.client.SRIClient") as mock:
        client = MagicMock()

        # Mock respuesta de recepción exitosa
        client.enviar_comprobante.return_value = MagicMock(
            estado="RECIBIDA",
            comprobantes=None,
        )

        # Mock respuesta de autorización exitosa
        client.consultar_autorizacion.return_value = MagicMock(
            clave_acceso_consultada="test",
            numero_comprobantes=1,
            autorizaciones=[
                MagicMock(
                    estado="AUTORIZADO",
                    numero_autorizacion="1234567890",
                    fecha_autorizacion=None,
                    comprobante="<xml>test</xml>",
                    mensajes=[],
                )
            ],
        )

        mock.return_value = client
        yield client


@pytest.fixture
def mock_settings():
    """Mock de configuración para tests."""
    with patch("src.config.settings.get_settings") as mock:
        settings = MagicMock()
        settings.sri_ambiente = "1"
        settings.sri_ruc = "1792535500001"
        settings.sri_razon_social = "EMPRESA TEST SAS"
        settings.sri_nombre_comercial = "TEST"
        settings.sri_direccion_matriz = "Quito, Ecuador"
        settings.sri_obligado_contabilidad = "SI"
        settings.sri_establecimiento = "001"
        settings.sri_punto_emision = "001"
        settings.sri_cert_path = "/app/certs/test.p12"
        settings.sri_cert_password = "test"
        settings.comision_porcentaje = 1.5
        settings.iva_porcentaje = 15.0

        mock.return_value = settings
        yield settings
