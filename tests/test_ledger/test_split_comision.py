"""
Tests para el servicio de Split de Comision.
Usa mocks para get_settings y dependencias de base de datos.
"""

from decimal import Decimal, ROUND_HALF_UP
from unittest.mock import MagicMock, patch

import pytest

from src.ledger.models import ComisionSplit
from src.ledger.split_comision import (
    CUENTA_BANCOS,
    CUENTA_INGRESO_COMISION,
    CUENTA_IVA_COBRADO,
    CUENTA_PASIVO_PROPIETARIO,
    ComisionSplitService,
    calcular_split_rapido,
)

# Porcentaje de comision como multiplicador decimal: 1.5% = 0.015
PCT_COMISION = Decimal("0.015")


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_dependencies():
    """
    Mockea get_settings, get_supabase_client y JournalService
    para poder instanciar ComisionSplitService sin DB real.
    """
    with (
        patch("src.ledger.split_comision.get_settings") as mock_settings,
        patch("src.ledger.split_comision.get_supabase_client") as mock_db,
        patch("src.ledger.split_comision.JournalService") as mock_journal_cls,
    ):
        settings = MagicMock()
        # El servicio hace Decimal(str(settings.comision_porcentaje)) y lo usa
        # como multiplicador directo: monto * porcentaje.
        # 0.015 => 1.5% del monto bruto
        settings.comision_porcentaje = 0.015
        settings.iva_porcentaje = 15.0
        mock_settings.return_value = settings

        mock_db.return_value = MagicMock()
        mock_journal_cls.return_value = MagicMock()

        yield {
            "settings": settings,
            "db": mock_db.return_value,
            "journal": mock_journal_cls.return_value,
        }


@pytest.fixture
def service(mock_dependencies):
    """Instancia del servicio con dependencias mockeadas."""
    return ComisionSplitService()


# ============================================================
# ComisionSplitService.calcular_split
# ============================================================


class TestCalcularSplit:
    """Tests para calcular_split con porcentaje default y custom."""

    def test_split_basico_1_5_porciento(self, service):
        """Split basico: 1.5% comision, 98.5% propietario."""
        split = service.calcular_split(Decimal("1000"))

        assert split.monto_bruto == Decimal("1000")
        assert split.monto_comision == Decimal("15.00")
        assert split.monto_propietario == Decimal("985.00")
        assert split.porcentaje_comision == PCT_COMISION

    def test_split_porcentaje_custom_2_5_porciento(self, service):
        """Split con porcentaje custom de 2.5% (0.025 como multiplicador)."""
        split = service.calcular_split(
            Decimal("2000"),
            porcentaje_comision=Decimal("0.025"),
        )

        # 2000 * 0.025 = 50.00
        assert split.monto_comision == Decimal("50.00")
        assert split.monto_propietario == Decimal("1950.00")

    def test_split_porcentaje_custom_5_porciento(self, service):
        """Split con porcentaje custom de 5% (0.05 como multiplicador)."""
        split = service.calcular_split(
            Decimal("1000"),
            porcentaje_comision=Decimal("0.05"),
        )

        # 1000 * 0.05 = 50.00
        assert split.monto_comision == Decimal("50.00")
        assert split.monto_propietario == Decimal("950.00")

    def test_split_monto_cero(self, service):
        """Split con monto cero."""
        split = service.calcular_split(Decimal("0"))

        assert split.monto_comision == Decimal("0.00")
        assert split.monto_propietario == Decimal("0.00")

    def test_split_monto_muy_pequeno(self, service):
        """Split con monto muy pequeno (centavos)."""
        split = service.calcular_split(Decimal("0.50"))

        # 0.50 * 0.015 = 0.0075 -> ROUND_HALF_UP -> 0.01
        expected_comision = (Decimal("0.50") * PCT_COMISION).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        assert split.monto_comision == expected_comision
        assert split.monto_propietario == Decimal("0.50") - expected_comision

    def test_split_monto_grande(self, service):
        """Split con monto grande."""
        split = service.calcular_split(Decimal("500000"))

        # 500000 * 0.015 = 7500.00
        expected_comision = (Decimal("500000") * PCT_COMISION).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        assert split.monto_comision == expected_comision
        assert split.monto_propietario == Decimal("500000") - expected_comision

    def test_split_suma_igual_bruto(self, service):
        """La suma de comision + propietario siempre es igual al bruto."""
        montos_prueba = [
            Decimal("100"),
            Decimal("333.33"),
            Decimal("777.77"),
            Decimal("1"),
            Decimal("99999.99"),
        ]
        for monto in montos_prueba:
            split = service.calcular_split(monto)
            total = split.monto_comision + split.monto_propietario
            assert total == split.monto_bruto, (
                f"Para monto {monto}: {split.monto_comision} + "
                f"{split.monto_propietario} != {split.monto_bruto}"
            )

    def test_split_redondeo_round_half_up(self, service):
        """Verifica que se usa ROUND_HALF_UP en el redondeo."""
        # 333.33 * 0.015 = 4.99995 -> ROUND_HALF_UP -> 5.00
        split = service.calcular_split(Decimal("333.33"))

        expected = (Decimal("333.33") * PCT_COMISION).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        assert split.monto_comision == expected
        assert split.monto_comision == Decimal("5.00")

    def test_split_redondeo_caso_medio(self, service):
        """Caso donde el redondeo importa: 0.005 -> 0.01."""
        # Buscar un monto donde 0.015 * monto tenga exactamente .005 en tercer decimal
        # monto * 0.015 = X.XX5 => monto = X.XX5 / 0.015
        # Por ejemplo: 100/3 = 33.333... * 0.015 = 0.50000...
        # Otro: 0.50 * 0.015 = 0.0075 -> 0.01 (ROUND_HALF_UP)
        split = service.calcular_split(Decimal("0.50"))
        assert split.monto_comision == Decimal("0.01")

    def test_split_retorna_comision_split_model(self, service):
        """El resultado es una instancia de ComisionSplit."""
        split = service.calcular_split(Decimal("100"))
        assert isinstance(split, ComisionSplit)


# ============================================================
# ComisionSplitService._generar_movimientos_cobro
# ============================================================


class TestGenerarMovimientosCobro:
    """Tests para _generar_movimientos_cobro sin y con IVA."""

    def _make_split(self, monto_bruto=Decimal("1000")):
        """Crea un ComisionSplit de prueba."""
        comision = (monto_bruto * PCT_COMISION).quantize(Decimal("0.01"))
        return ComisionSplit(
            monto_bruto=monto_bruto,
            porcentaje_comision=PCT_COMISION,
            monto_comision=comision,
            monto_propietario=monto_bruto - comision,
        )

    def test_sin_iva_genera_3_movimientos(self, service):
        """Sin IVA: 3 movimientos (bancos debe, ingreso haber, pasivo haber)."""
        split = self._make_split()
        movs = service._generar_movimientos_cobro(split, "Test cobro", incluye_iva=False)

        assert len(movs) == 3

    def test_sin_iva_primer_movimiento_bancos_debe(self, service):
        """Sin IVA: primer movimiento es bancos al debe por el total."""
        split = self._make_split(Decimal("1000"))
        movs = service._generar_movimientos_cobro(split, "Cobro", incluye_iva=False)

        assert movs[0]["cuenta"] == CUENTA_BANCOS
        assert movs[0]["debe"] == Decimal("1000")
        assert movs[0]["haber"] == Decimal("0")

    def test_sin_iva_segundo_movimiento_ingreso_haber(self, service):
        """Sin IVA: segundo movimiento es ingreso comision al haber."""
        split = self._make_split(Decimal("1000"))
        movs = service._generar_movimientos_cobro(split, "Cobro", incluye_iva=False)

        assert movs[1]["cuenta"] == CUENTA_INGRESO_COMISION
        assert movs[1]["haber"] == split.monto_comision
        assert movs[1]["debe"] == Decimal("0")

    def test_sin_iva_tercer_movimiento_pasivo_haber(self, service):
        """Sin IVA: tercer movimiento es pasivo propietario al haber."""
        split = self._make_split(Decimal("1000"))
        movs = service._generar_movimientos_cobro(split, "Cobro", incluye_iva=False)

        assert movs[2]["cuenta"] == CUENTA_PASIVO_PROPIETARIO
        assert movs[2]["haber"] == split.monto_propietario
        assert movs[2]["debe"] == Decimal("0")

    def test_sin_iva_movimientos_cuadran(self, service):
        """Sin IVA: la suma de debe == suma de haber."""
        split = self._make_split(Decimal("2500.50"))
        movs = service._generar_movimientos_cobro(split, "Cobro", incluye_iva=False)

        total_debe = sum(m["debe"] for m in movs)
        total_haber = sum(m["haber"] for m in movs)
        assert total_debe == total_haber, (
            f"Debe={total_debe} != Haber={total_haber}"
        )

    def test_con_iva_genera_4_movimientos(self, service):
        """Con IVA: 4 movimientos (bancos, ingreso base, iva, pasivo)."""
        split = self._make_split(Decimal("1000"))
        movs = service._generar_movimientos_cobro(split, "Cobro", incluye_iva=True)

        assert len(movs) == 4

    def test_con_iva_primer_movimiento_bancos_debe(self, service):
        """Con IVA: primer movimiento es bancos al debe por el total."""
        split = self._make_split(Decimal("1000"))
        movs = service._generar_movimientos_cobro(split, "Cobro", incluye_iva=True)

        assert movs[0]["cuenta"] == CUENTA_BANCOS
        assert movs[0]["debe"] == Decimal("1000")

    def test_con_iva_segundo_movimiento_ingreso_base_haber(self, service):
        """Con IVA: segundo movimiento es ingreso base (sin IVA) al haber."""
        split = self._make_split(Decimal("1000"))
        movs = service._generar_movimientos_cobro(split, "Cobro", incluye_iva=True)

        assert movs[1]["cuenta"] == CUENTA_INGRESO_COMISION
        assert movs[1]["debe"] == Decimal("0")
        # La logica usa: divisor = 1 + porcentaje_iva (que es 15.0)
        # base = comision / (1 + 15.0) = 15.00 / 16 = 0.94
        divisor = Decimal("1") + Decimal("15.0")
        expected_base = (split.monto_comision / divisor).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        assert movs[1]["haber"] == expected_base

    def test_con_iva_tercer_movimiento_iva_haber(self, service):
        """Con IVA: tercer movimiento es IVA cobrado al haber."""
        split = self._make_split(Decimal("1000"))
        movs = service._generar_movimientos_cobro(split, "Cobro", incluye_iva=True)

        assert movs[2]["cuenta"] == CUENTA_IVA_COBRADO
        assert movs[2]["debe"] == Decimal("0")
        # iva = comision - base
        divisor = Decimal("1") + Decimal("15.0")
        base = (split.monto_comision / divisor).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        expected_iva = split.monto_comision - base
        assert movs[2]["haber"] == expected_iva

    def test_con_iva_cuarto_movimiento_pasivo_haber(self, service):
        """Con IVA: cuarto movimiento es pasivo propietario al haber."""
        split = self._make_split(Decimal("1000"))
        movs = service._generar_movimientos_cobro(split, "Cobro", incluye_iva=True)

        assert movs[3]["cuenta"] == CUENTA_PASIVO_PROPIETARIO
        assert movs[3]["haber"] == split.monto_propietario

    def test_con_iva_movimientos_cuadran(self, service):
        """Con IVA: la suma de debe == suma de haber."""
        split = self._make_split(Decimal("5000"))
        movs = service._generar_movimientos_cobro(split, "Cobro", incluye_iva=True)

        total_debe = sum(m["debe"] for m in movs)
        total_haber = sum(m["haber"] for m in movs)
        assert total_debe == total_haber, (
            f"Debe={total_debe} != Haber={total_haber}"
        )

    def test_sin_iva_movimientos_cuadran_montos_variados(self, service):
        """Sin IVA: cuadran con diferentes montos."""
        for monto in [Decimal("1"), Decimal("99.99"), Decimal("12345.67")]:
            split = self._make_split(monto)
            movs = service._generar_movimientos_cobro(split, "Test", incluye_iva=False)
            total_debe = sum(m["debe"] for m in movs)
            total_haber = sum(m["haber"] for m in movs)
            assert total_debe == total_haber, f"Descuadre con monto {monto}"

    def test_con_iva_movimientos_cuadran_montos_variados(self, service):
        """Con IVA: cuadran con diferentes montos."""
        for monto in [Decimal("1"), Decimal("99.99"), Decimal("12345.67")]:
            split = self._make_split(monto)
            movs = service._generar_movimientos_cobro(split, "Test", incluye_iva=True)
            total_debe = sum(m["debe"] for m in movs)
            total_haber = sum(m["haber"] for m in movs)
            assert total_debe == total_haber, f"Descuadre con IVA y monto {monto}"


# ============================================================
# calcular_split_rapido
# ============================================================


class TestCalcularSplitRapido:
    """Tests para la funcion de conveniencia calcular_split_rapido."""

    def test_retorna_diccionario(self, mock_dependencies):
        """Retorna un diccionario con las claves esperadas."""
        result = calcular_split_rapido(Decimal("1000"))

        assert isinstance(result, dict)
        assert "total" in result
        assert "comision" in result
        assert "propietario" in result
        assert "porcentaje" in result

    def test_valores_correctos(self, mock_dependencies):
        """Los valores del diccionario son correctos."""
        result = calcular_split_rapido(Decimal("2000"))

        # 2000 * 0.015 = 30.00
        expected_comision = (Decimal("2000") * PCT_COMISION).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        assert result["total"] == Decimal("2000")
        assert result["comision"] == expected_comision
        assert result["propietario"] == Decimal("2000") - expected_comision

    def test_suma_comision_propietario_igual_total(self, mock_dependencies):
        """comision + propietario == total."""
        result = calcular_split_rapido(Decimal("777.77"))

        assert result["comision"] + result["propietario"] == result["total"]


# ============================================================
# Constantes de cuentas contables
# ============================================================


class TestConstantesCuentas:
    """Verifica que las constantes de cuentas estan correctas."""

    def test_cuenta_bancos(self):
        assert CUENTA_BANCOS == "1.1.03"

    def test_cuenta_ingreso_comision(self):
        assert CUENTA_INGRESO_COMISION == "4.1.01"

    def test_cuenta_pasivo_propietario(self):
        assert CUENTA_PASIVO_PROPIETARIO == "2.1.09"

    def test_cuenta_iva_cobrado(self):
        assert CUENTA_IVA_COBRADO == "2.1.04"
