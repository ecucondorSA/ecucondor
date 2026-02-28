"""
Tests para los modelos del Ledger Contable.
Pruebas de logica pura, sin base de datos.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.ledger.models import (
    AsientoContable,
    ComisionSplit,
    EstadoAsiento,
    MovimientoContable,
    OrigenAsiento,
    TipoAsiento,
)


# ============================================================
# MovimientoContable
# ============================================================


class TestMovimientoContableValidacion:
    """Validacion de que debe O haber tenga valor, nunca ambos ni ninguno."""

    def test_debe_positivo_haber_cero_es_valido(self):
        """Movimiento al debe con haber en cero debe ser valido."""
        mov = MovimientoContable(
            cuenta_codigo="1.1.01",
            debe=Decimal("100.00"),
            haber=Decimal("0"),
        )
        assert mov.debe == Decimal("100.00")
        assert mov.haber == Decimal("0")

    def test_haber_positivo_debe_cero_es_valido(self):
        """Movimiento al haber con debe en cero debe ser valido."""
        mov = MovimientoContable(
            cuenta_codigo="4.1.01",
            debe=Decimal("0"),
            haber=Decimal("50.00"),
        )
        assert mov.haber == Decimal("50.00")
        assert mov.debe == Decimal("0")

    def test_ambos_positivos_falla(self):
        """Si debe Y haber son > 0, debe lanzar ValueError."""
        with pytest.raises(ValueError, match="debe O haber, no ambos"):
            MovimientoContable(
                cuenta_codigo="1.1.01",
                debe=Decimal("100"),
                haber=Decimal("50"),
            )

    def test_ambos_cero_falla(self):
        """Si debe Y haber son 0, debe lanzar ValueError."""
        with pytest.raises(ValueError, match="debe o haber con valor > 0"):
            MovimientoContable(
                cuenta_codigo="1.1.01",
                debe=Decimal("0"),
                haber=Decimal("0"),
            )

    def test_debe_negativo_falla(self):
        """Valor negativo en debe debe fallar por la restriccion ge=0."""
        with pytest.raises(Exception):
            MovimientoContable(
                cuenta_codigo="1.1.01",
                debe=Decimal("-10"),
                haber=Decimal("0"),
            )

    def test_haber_negativo_falla(self):
        """Valor negativo en haber debe fallar por la restriccion ge=0."""
        with pytest.raises(Exception):
            MovimientoContable(
                cuenta_codigo="1.1.01",
                debe=Decimal("0"),
                haber=Decimal("-10"),
            )

    def test_cuenta_codigo_vacio_falla(self):
        """Cuenta codigo vacio debe fallar (min_length=1)."""
        with pytest.raises(Exception):
            MovimientoContable(
                cuenta_codigo="",
                debe=Decimal("100"),
                haber=Decimal("0"),
            )


class TestMovimientoContablePropiedades:
    """Tests para es_debe, es_haber y monto."""

    def test_es_debe_verdadero(self):
        """es_debe retorna True cuando debe > 0."""
        mov = MovimientoContable(
            cuenta_codigo="1.1.01",
            debe=Decimal("200"),
        )
        assert mov.es_debe is True
        assert mov.es_haber is False

    def test_es_haber_verdadero(self):
        """es_haber retorna True cuando haber > 0."""
        mov = MovimientoContable(
            cuenta_codigo="4.1.01",
            haber=Decimal("300"),
        )
        assert mov.es_haber is True
        assert mov.es_debe is False

    def test_monto_retorna_debe(self):
        """monto retorna el valor de debe cuando es movimiento al debe."""
        mov = MovimientoContable(
            cuenta_codigo="1.1.01",
            debe=Decimal("150.75"),
        )
        assert mov.monto == Decimal("150.75")

    def test_monto_retorna_haber(self):
        """monto retorna el valor de haber cuando es movimiento al haber."""
        mov = MovimientoContable(
            cuenta_codigo="4.1.01",
            haber=Decimal("99.99"),
        )
        assert mov.monto == Decimal("99.99")

    def test_monto_con_decimales_precisos(self):
        """Verificar precision decimal en monto."""
        mov = MovimientoContable(
            cuenta_codigo="1.1.01",
            debe=Decimal("1234.56"),
        )
        assert mov.monto == Decimal("1234.56")


class TestMovimientoContableToDbDict:
    """Tests para to_db_dict de MovimientoContable."""

    def test_to_db_dict_basico(self):
        """Genera diccionario con los campos correctos."""
        mov = MovimientoContable(
            cuenta_codigo="1.1.03",
            debe=Decimal("500.00"),
            concepto="Cobro cliente",
            orden=0,
        )
        d = mov.to_db_dict()

        assert d["cuenta_codigo"] == "1.1.03"
        assert d["debe"] == 500.00
        assert d["haber"] == 0.0
        assert d["concepto"] == "Cobro cliente"
        assert d["orden"] == 0

    def test_to_db_dict_convierte_decimal_a_float(self):
        """Los montos deben convertirse a float para la base de datos."""
        mov = MovimientoContable(
            cuenta_codigo="4.1.01",
            haber=Decimal("123.45"),
        )
        d = mov.to_db_dict()

        assert isinstance(d["debe"], float)
        assert isinstance(d["haber"], float)
        assert d["debe"] == 0.0
        assert d["haber"] == 123.45

    def test_to_db_dict_campos_opcionales_nulos(self):
        """Los campos opcionales pueden ser None."""
        mov = MovimientoContable(
            cuenta_codigo="2.1.09",
            haber=Decimal("50"),
        )
        d = mov.to_db_dict()

        assert d["concepto"] is None
        assert d["centro_costo"] is None
        assert d["referencia"] is None

    def test_to_db_dict_con_todos_los_campos(self):
        """Diccionario con todos los campos opcionales."""
        mov = MovimientoContable(
            cuenta_codigo="1.1.03",
            debe=Decimal("1000"),
            concepto="Deposito bancario",
            centro_costo="CC001",
            referencia="REF-2025-001",
            orden=3,
        )
        d = mov.to_db_dict()

        assert d["centro_costo"] == "CC001"
        assert d["referencia"] == "REF-2025-001"
        assert d["orden"] == 3


# ============================================================
# AsientoContable
# ============================================================


class TestAsientoContableCalcularTotales:
    """Tests para el model_validator calcular_totales."""

    def test_totales_calculados_al_crear(self):
        """Los totales se calculan automaticamente al crear el asiento."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 15),
            concepto="Cobro servicio",
            movimientos=[
                MovimientoContable(cuenta_codigo="1.1.03", debe=Decimal("100")),
                MovimientoContable(cuenta_codigo="4.1.01", haber=Decimal("100")),
            ],
        )
        assert asiento.total_debe == Decimal("100")
        assert asiento.total_haber == Decimal("100")

    def test_totales_sin_movimientos(self):
        """Sin movimientos, los totales deben ser cero."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Asiento vacio",
            movimientos=[],
        )
        assert asiento.total_debe == Decimal("0")
        assert asiento.total_haber == Decimal("0")

    def test_totales_multiples_movimientos(self):
        """Totales con varios movimientos al debe y al haber."""
        asiento = AsientoContable(
            fecha=date(2025, 6, 1),
            concepto="Split comision",
            movimientos=[
                MovimientoContable(cuenta_codigo="1.1.03", debe=Decimal("1000")),
                MovimientoContable(cuenta_codigo="4.1.01", haber=Decimal("15")),
                MovimientoContable(cuenta_codigo="2.1.09", haber=Decimal("985")),
            ],
        )
        assert asiento.total_debe == Decimal("1000")
        assert asiento.total_haber == Decimal("1000")


class TestAsientoContableEstaCuadrado:
    """Tests para la propiedad esta_cuadrado."""

    def test_cuadrado_cuando_debe_igual_haber(self):
        """El asiento cuadra cuando total debe == total haber."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Test cuadrado",
            movimientos=[
                MovimientoContable(cuenta_codigo="1.1.03", debe=Decimal("500")),
                MovimientoContable(cuenta_codigo="4.1.01", haber=Decimal("500")),
            ],
        )
        assert asiento.esta_cuadrado is True

    def test_no_cuadrado_cuando_difieren(self):
        """El asiento no cuadra cuando total debe != total haber."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Test descuadrado",
            movimientos=[
                MovimientoContable(cuenta_codigo="1.1.03", debe=Decimal("500")),
                MovimientoContable(cuenta_codigo="4.1.01", haber=Decimal("300")),
            ],
        )
        assert asiento.esta_cuadrado is False


class TestAsientoContableDiferencia:
    """Tests para la propiedad diferencia."""

    def test_diferencia_cero_cuadrado(self):
        """La diferencia es cero cuando el asiento cuadra."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Test",
            movimientos=[
                MovimientoContable(cuenta_codigo="1.1.03", debe=Decimal("250")),
                MovimientoContable(cuenta_codigo="4.1.01", haber=Decimal("250")),
            ],
        )
        assert asiento.diferencia == Decimal("0")

    def test_diferencia_positiva_mas_debe(self):
        """La diferencia es positiva cuando debe > haber."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Test",
            movimientos=[
                MovimientoContable(cuenta_codigo="1.1.03", debe=Decimal("300")),
                MovimientoContable(cuenta_codigo="4.1.01", haber=Decimal("200")),
            ],
        )
        assert asiento.diferencia == Decimal("100")

    def test_diferencia_negativa_mas_haber(self):
        """La diferencia es negativa cuando haber > debe."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Test",
            movimientos=[
                MovimientoContable(cuenta_codigo="1.1.03", debe=Decimal("100")),
                MovimientoContable(cuenta_codigo="4.1.01", haber=Decimal("400")),
            ],
        )
        assert asiento.diferencia == Decimal("-300")


class TestAsientoContableAgregarMethods:
    """Tests para agregar_debe y agregar_haber."""

    def test_agregar_debe(self):
        """agregar_debe anade un movimiento al debe y actualiza totales."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Test agregar",
        )
        asiento.agregar_debe("1.1.03", Decimal("100"), "Cobro")

        assert len(asiento.movimientos) == 1
        assert asiento.movimientos[0].es_debe is True
        assert asiento.movimientos[0].debe == Decimal("100")
        assert asiento.movimientos[0].concepto == "Cobro"
        assert asiento.total_debe == Decimal("100")

    def test_agregar_haber(self):
        """agregar_haber anade un movimiento al haber y actualiza totales."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Test agregar",
        )
        asiento.agregar_haber("4.1.01", Decimal("75.50"), "Comision")

        assert len(asiento.movimientos) == 1
        assert asiento.movimientos[0].es_haber is True
        assert asiento.movimientos[0].haber == Decimal("75.50")
        assert asiento.total_haber == Decimal("75.50")

    def test_agregar_multiples_y_cuadrar(self):
        """Agregar movimientos al debe y haber que cuadren."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Test multiple",
        )
        asiento.agregar_debe("1.1.03", Decimal("1000"))
        asiento.agregar_haber("4.1.01", Decimal("15"))
        asiento.agregar_haber("2.1.09", Decimal("985"))

        assert asiento.esta_cuadrado is True
        assert len(asiento.movimientos) == 3

    def test_agregar_retorna_self(self):
        """Los metodos agregar deben retornar el asiento para encadenamiento."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Test chaining",
        )
        result = asiento.agregar_debe("1.1.03", Decimal("100"))
        assert result is asiento

        result2 = asiento.agregar_haber("4.1.01", Decimal("100"))
        assert result2 is asiento

    def test_orden_incrementa(self):
        """El orden de los movimientos se incrementa automaticamente."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Test orden",
        )
        asiento.agregar_debe("1.1.03", Decimal("100"))
        asiento.agregar_haber("4.1.01", Decimal("50"))
        asiento.agregar_haber("2.1.09", Decimal("50"))

        assert asiento.movimientos[0].orden == 0
        assert asiento.movimientos[1].orden == 1
        assert asiento.movimientos[2].orden == 2


class TestAsientoContableValidar:
    """Tests para el metodo validar()."""

    def test_sin_movimientos(self):
        """Asiento sin movimientos debe reportar dos errores."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Sin movimientos",
        )
        errores = asiento.validar()

        assert len(errores) == 2
        assert any("no tiene movimientos" in e for e in errores)
        assert any("al menos 2" in e for e in errores)

    def test_un_solo_movimiento(self):
        """Asiento con un solo movimiento debe reportar error."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Un movimiento",
            movimientos=[
                MovimientoContable(cuenta_codigo="1.1.03", debe=Decimal("100")),
            ],
        )
        errores = asiento.validar()

        assert len(errores) >= 1
        assert any("al menos 2" in e for e in errores)
        # Tambien debe reportar descuadre
        assert any("no cuadra" in e for e in errores)

    def test_descuadrado(self):
        """Asiento con 2 movimientos que no cuadran."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Descuadrado",
            movimientos=[
                MovimientoContable(cuenta_codigo="1.1.03", debe=Decimal("100")),
                MovimientoContable(cuenta_codigo="4.1.01", haber=Decimal("80")),
            ],
        )
        errores = asiento.validar()

        assert len(errores) == 1
        assert "no cuadra" in errores[0]
        assert "Diferencia" in errores[0]

    def test_valido_sin_errores(self):
        """Asiento valido no tiene errores."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Valido",
            movimientos=[
                MovimientoContable(cuenta_codigo="1.1.03", debe=Decimal("100")),
                MovimientoContable(cuenta_codigo="4.1.01", haber=Decimal("100")),
            ],
        )
        errores = asiento.validar()

        assert errores == []

    def test_valido_multiples_movimientos(self):
        """Asiento valido con tres movimientos que cuadran."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Split comision",
            movimientos=[
                MovimientoContable(cuenta_codigo="1.1.03", debe=Decimal("1000")),
                MovimientoContable(cuenta_codigo="4.1.01", haber=Decimal("15")),
                MovimientoContable(cuenta_codigo="2.1.09", haber=Decimal("985")),
            ],
        )
        errores = asiento.validar()

        assert errores == []


class TestAsientoContableToDbDict:
    """Tests para to_db_dict de AsientoContable."""

    def test_to_db_dict_campos_basicos(self):
        """Genera diccionario con los campos requeridos."""
        asiento = AsientoContable(
            fecha=date(2025, 3, 15),
            concepto="Test DB dict",
            movimientos=[
                MovimientoContable(cuenta_codigo="1.1.03", debe=Decimal("100")),
                MovimientoContable(cuenta_codigo="4.1.01", haber=Decimal("100")),
            ],
        )
        d = asiento.to_db_dict()

        assert d["fecha"] == "2025-03-15"
        assert d["concepto"] == "Test DB dict"
        assert d["tipo"] == "normal"
        assert d["total_debe"] == 100.0
        assert d["total_haber"] == 100.0
        assert d["estado"] == "borrador"

    def test_to_db_dict_sin_campos_opcionales(self):
        """Los campos opcionales no aparecen si son None."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Test",
        )
        d = asiento.to_db_dict()

        assert "referencia" not in d
        assert "origen_tipo" not in d
        assert "origen_id" not in d
        assert "created_by" not in d

    def test_to_db_dict_con_campos_opcionales(self):
        """Los campos opcionales aparecen cuando estan establecidos."""
        uid = uuid4()
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Test",
            referencia="REF-001",
            origen_tipo=OrigenAsiento.COMISION,
            origen_id=uid,
            created_by=uid,
        )
        d = asiento.to_db_dict()

        assert d["referencia"] == "REF-001"
        assert d["origen_tipo"] == "comision"
        assert d["origen_id"] == str(uid)
        assert d["created_by"] == str(uid)

    def test_to_db_dict_tipo_asiento(self):
        """El tipo de asiento se serializa como string."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Cierre",
            tipo=TipoAsiento.CIERRE,
        )
        d = asiento.to_db_dict()

        assert d["tipo"] == "cierre"

    def test_to_db_dict_estado_contabilizado(self):
        """El estado contabilizado se serializa correctamente."""
        asiento = AsientoContable(
            fecha=date(2025, 1, 1),
            concepto="Contabilizado",
            estado=EstadoAsiento.CONTABILIZADO,
        )
        d = asiento.to_db_dict()

        assert d["estado"] == "contabilizado"


# ============================================================
# ComisionSplit
# ============================================================


class TestComisionSplitCalcularMontos:
    """Tests para el model_validator calcular_montos."""

    def test_calculo_automatico_default_1_5_porciento(self):
        """Con porcentaje default de 1.5%, calcula comision y propietario."""
        split = ComisionSplit(monto_bruto=Decimal("1000"))

        assert split.monto_comision == Decimal("15.00")
        assert split.monto_propietario == Decimal("985.00")

    def test_calculo_con_porcentaje_custom(self):
        """Con porcentaje custom, calcula correctamente."""
        split = ComisionSplit(
            monto_bruto=Decimal("1000"),
            porcentaje_comision=Decimal("0.02"),  # 2%
        )
        assert split.monto_comision == Decimal("20.00")
        assert split.monto_propietario == Decimal("980.00")

    def test_no_sobrescribe_montos_explicitios(self):
        """Si se proporcionan montos explicitamente, no los recalcula."""
        split = ComisionSplit(
            monto_bruto=Decimal("1000"),
            monto_comision=Decimal("25.00"),
            monto_propietario=Decimal("975.00"),
        )
        # Los montos explicitos se mantienen
        assert split.monto_comision == Decimal("25.00")
        assert split.monto_propietario == Decimal("975.00")

    def test_calculo_con_monto_pequeno(self):
        """Con montos pequenos, el redondeo funciona correctamente."""
        split = ComisionSplit(monto_bruto=Decimal("10"))

        # 10 * 0.015 = 0.15
        assert split.monto_comision == Decimal("0.15")
        assert split.monto_propietario == Decimal("9.85")

    def test_calculo_con_monto_grande(self):
        """Con montos grandes, el calculo es correcto."""
        split = ComisionSplit(monto_bruto=Decimal("100000"))

        assert split.monto_comision == Decimal("1500.00")
        assert split.monto_propietario == Decimal("98500.00")

    def test_suma_comision_mas_propietario_igual_bruto(self):
        """La suma de comision + propietario debe ser igual al bruto."""
        split = ComisionSplit(monto_bruto=Decimal("777.77"))

        total = split.monto_comision + split.monto_propietario
        assert total == split.monto_bruto


class TestComisionSplitToDbDict:
    """Tests para to_db_dict de ComisionSplit."""

    def test_to_db_dict_campos_basicos(self):
        """Genera diccionario con los campos basicos."""
        split = ComisionSplit(monto_bruto=Decimal("1000"))
        d = split.to_db_dict()

        assert d["monto_bruto"] == 1000.0
        assert d["porcentaje_comision"] == 0.015
        assert d["monto_comision"] == 15.0
        assert d["monto_propietario"] == 985.0
        assert d["estado"] == "pendiente"

    def test_to_db_dict_sin_ids_opcionales(self):
        """Los IDs opcionales no aparecen si son None."""
        split = ComisionSplit(monto_bruto=Decimal("100"))
        d = split.to_db_dict()

        assert "transaccion_id" not in d
        assert "comprobante_id" not in d
        assert "asiento_id" not in d
        assert "propietario_id" not in d
        assert "vehiculo_id" not in d

    def test_to_db_dict_con_ids_opcionales(self):
        """Los IDs opcionales aparecen cuando estan establecidos."""
        tx_id = uuid4()
        prop_id = uuid4()
        split = ComisionSplit(
            monto_bruto=Decimal("500"),
            transaccion_id=tx_id,
            propietario_id=prop_id,
        )
        d = split.to_db_dict()

        assert d["transaccion_id"] == str(tx_id)
        assert d["propietario_id"] == str(prop_id)

    def test_to_db_dict_convierte_decimal_a_float(self):
        """Los montos se convierten a float."""
        split = ComisionSplit(monto_bruto=Decimal("333.33"))
        d = split.to_db_dict()

        assert isinstance(d["monto_bruto"], float)
        assert isinstance(d["monto_comision"], float)
        assert isinstance(d["monto_propietario"], float)
        assert isinstance(d["porcentaje_comision"], float)
