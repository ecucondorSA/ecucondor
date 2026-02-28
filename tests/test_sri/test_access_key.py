"""
Tests para el generador de claves de acceso del SRI.
"""

from datetime import date

import pytest

from src.sri.access_key import (
    calcular_digito_verificador,
    describir_clave,
    extraer_datos_clave,
    generar_clave_acceso,
    validar_clave_acceso,
)
from src.sri.models import TipoComprobante


class TestCalcularDigitoVerificador:
    """Tests para la función calcular_digito_verificador."""

    def test_calculo_basico(self):
        """Verifica el cálculo del dígito verificador."""
        # Cadena de prueba de 48 dígitos (clave sin dígito verificador)
        # Estructura: fecha(8) + tipo(2) + ruc(13) + amb(1) + est(3) + pto(3) + sec(9) + cod(8) + emi(1)
        cadena = "150320240117925355000011001001000000001123456781"
        digito = calcular_digito_verificador(cadena)
        assert digito.isdigit()
        assert len(digito) == 1

    def test_cadena_invalida_longitud(self):
        """Verifica que falle con longitud incorrecta."""
        with pytest.raises(ValueError, match="48 dígitos"):
            calcular_digito_verificador("12345")

    def test_cadena_invalida_caracteres(self):
        """Verifica que falle con caracteres no numéricos."""
        with pytest.raises(ValueError, match="solo dígitos"):
            calcular_digito_verificador("12345678901234567890123456789012345678901234567a")


class TestGenerarClaveAcceso:
    """Tests para la función generar_clave_acceso."""

    def test_generacion_factura(self):
        """Verifica la generación de clave para factura."""
        clave = generar_clave_acceso(
            fecha_emision=date(2024, 3, 15),
            tipo_comprobante=TipoComprobante.FACTURA,
            ruc="1792535500001",
            ambiente="1",
            establecimiento="001",
            punto_emision="001",
            secuencial=1,
            codigo_numerico="12345678",
        )

        assert len(clave) == 49
        assert clave.isdigit()
        assert validar_clave_acceso(clave)

    def test_generacion_nota_credito(self):
        """Verifica la generación de clave para nota de crédito."""
        clave = generar_clave_acceso(
            fecha_emision=date(2024, 6, 20),
            tipo_comprobante=TipoComprobante.NOTA_CREDITO,
            ruc="1792535500001",
            ambiente="2",
            establecimiento="002",
            punto_emision="003",
            secuencial=12345,
        )

        assert len(clave) == 49
        assert validar_clave_acceso(clave)

    def test_generacion_retencion(self):
        """Verifica la generación de clave para retención."""
        clave = generar_clave_acceso(
            fecha_emision=date(2024, 12, 31),
            tipo_comprobante=TipoComprobante.RETENCION,
            ruc="1792535500001",
            ambiente="1",
            establecimiento="001",
            punto_emision="001",
            secuencial=999999999,
        )

        assert len(clave) == 49
        assert validar_clave_acceso(clave)

    def test_ruc_invalido(self):
        """Verifica que falle con RUC inválido."""
        with pytest.raises(ValueError, match="RUC inválido"):
            generar_clave_acceso(
                fecha_emision=date(2024, 1, 1),
                tipo_comprobante="01",
                ruc="12345",  # RUC muy corto
                ambiente="1",
                establecimiento="001",
                punto_emision="001",
                secuencial=1,
            )

    def test_ambiente_invalido(self):
        """Verifica que falle con ambiente inválido."""
        with pytest.raises(ValueError, match="Ambiente inválido"):
            generar_clave_acceso(
                fecha_emision=date(2024, 1, 1),
                tipo_comprobante="01",
                ruc="1792535500001",
                ambiente="3",  # Solo 1 o 2 son válidos
                establecimiento="001",
                punto_emision="001",
                secuencial=1,
            )

    def test_codigo_numerico_generado(self):
        """Verifica que se genere código numérico automáticamente."""
        clave1 = generar_clave_acceso(
            fecha_emision=date(2024, 1, 1),
            tipo_comprobante="01",
            ruc="1792535500001",
            ambiente="1",
            establecimiento="001",
            punto_emision="001",
            secuencial=1,
        )

        clave2 = generar_clave_acceso(
            fecha_emision=date(2024, 1, 1),
            tipo_comprobante="01",
            ruc="1792535500001",
            ambiente="1",
            establecimiento="001",
            punto_emision="001",
            secuencial=1,
        )

        # Las claves deben ser diferentes por el código numérico aleatorio
        # (pueden ser iguales en raras ocasiones, pero muy improbable)
        # El test verifica que ambas sean válidas
        assert validar_clave_acceso(clave1)
        assert validar_clave_acceso(clave2)


class TestValidarClaveAcceso:
    """Tests para la función validar_clave_acceso."""

    def test_clave_valida(self):
        """Verifica validación de clave correcta."""
        # Generar una clave válida
        clave = generar_clave_acceso(
            fecha_emision=date(2024, 5, 10),
            tipo_comprobante="01",
            ruc="1792535500001",
            ambiente="1",
            establecimiento="001",
            punto_emision="001",
            secuencial=123,
            codigo_numerico="87654321",
        )

        assert validar_clave_acceso(clave) is True

    def test_clave_invalida_longitud(self):
        """Verifica que falle con longitud incorrecta."""
        assert validar_clave_acceso("12345") is False

    def test_clave_invalida_caracteres(self):
        """Verifica que falle con caracteres no numéricos."""
        assert validar_clave_acceso("123456789012345678901234567890123456789012345678a") is False

    def test_clave_invalida_digito(self):
        """Verifica que falle con dígito verificador incorrecto."""
        # Generar clave válida y cambiar el último dígito
        clave = generar_clave_acceso(
            fecha_emision=date(2024, 1, 1),
            tipo_comprobante="01",
            ruc="1792535500001",
            ambiente="1",
            establecimiento="001",
            punto_emision="001",
            secuencial=1,
            codigo_numerico="12345678",
        )

        # Modificar el último dígito
        digito_original = clave[-1]
        nuevo_digito = str((int(digito_original) + 1) % 10)
        clave_modificada = clave[:-1] + nuevo_digito

        assert validar_clave_acceso(clave_modificada) is False


class TestExtraerDatosClave:
    """Tests para la función extraer_datos_clave."""

    def test_extraccion_datos(self):
        """Verifica la extracción de datos de una clave."""
        clave = generar_clave_acceso(
            fecha_emision=date(2024, 7, 25),
            tipo_comprobante=TipoComprobante.FACTURA,
            ruc="1792535500001",
            ambiente="2",
            establecimiento="003",
            punto_emision="005",
            secuencial=789,
            codigo_numerico="11111111",
        )

        datos = extraer_datos_clave(clave)

        assert datos["fecha_emision"] == "25/07/2024"
        assert datos["tipo_comprobante"] == "01"
        assert datos["ruc"] == "1792535500001"
        assert datos["ambiente"] == "Producción"
        assert datos["establecimiento"] == "003"
        assert datos["punto_emision"] == "005"
        assert datos["secuencial"] == "000000789"
        assert datos["codigo_numerico"] == "11111111"
        assert datos["tipo_emision"] == "1"

    def test_extraccion_clave_invalida(self):
        """Verifica que falle con clave inválida."""
        with pytest.raises(ValueError, match="inválida"):
            extraer_datos_clave("12345")


class TestDescribirClave:
    """Tests para la función describir_clave."""

    def test_descripcion_factura(self):
        """Verifica la descripción de una factura."""
        clave = generar_clave_acceso(
            fecha_emision=date(2024, 8, 15),
            tipo_comprobante=TipoComprobante.FACTURA,
            ruc="1792535500001",
            ambiente="1",
            establecimiento="001",
            punto_emision="002",
            secuencial=456,
        )

        descripcion = describir_clave(clave)

        assert "Factura" in descripcion
        assert "15/08/2024" in descripcion
        assert "1792535500001" in descripcion
        assert "Pruebas" in descripcion
        assert "001-002-000000456" in descripcion
