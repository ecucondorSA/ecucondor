"""
ECUCONDOR - Calculador de Declaración IVA
Genera datos para el Formulario 2011 del SRI.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


@dataclass
class DatosDeclaracionIVA:
    """
    Datos para la declaración mensual de IVA (Formulario 2011).

    Basado en la estructura del formulario SRI 2011 vigente.
    """
    # Identificación
    anio: int
    mes: int
    ruc: str
    razon_social: str

    # VENTAS (Casilleros 400)
    # 401 - Ventas locales (excluye activos fijos) gravadas tarifa diferente de 0%
    ventas_locales_gravadas: Decimal = Decimal("0")
    # 403 - Ventas de activos fijos gravadas tarifa diferente de 0%
    ventas_activos_fijos_gravadas: Decimal = Decimal("0")
    # 405 - Ventas locales (excluye activos fijos) gravadas tarifa 0%
    ventas_locales_0: Decimal = Decimal("0")
    # 407 - Ventas de activos fijos gravadas tarifa 0%
    ventas_activos_fijos_0: Decimal = Decimal("0")
    # 409 - Exportaciones de bienes
    exportaciones_bienes: Decimal = Decimal("0")
    # 411 - Exportaciones de servicios
    exportaciones_servicios: Decimal = Decimal("0")
    # 413 - Ventas a las que se aplicó retención de IVA
    ventas_con_retencion: Decimal = Decimal("0")

    # 415 - Total ventas y exportaciones netas (suma 401-413)
    @property
    def total_ventas_netas(self) -> Decimal:
        return (
            self.ventas_locales_gravadas +
            self.ventas_activos_fijos_gravadas +
            self.ventas_locales_0 +
            self.ventas_activos_fijos_0 +
            self.exportaciones_bienes +
            self.exportaciones_servicios +
            self.ventas_con_retencion
        )

    # COMPRAS (Casilleros 500)
    # 501 - Compras locales gravadas tarifa diferente 0% (excluye activos fijos)
    compras_locales_gravadas: Decimal = Decimal("0")
    # 503 - Compras de activos fijos gravadas tarifa diferente 0%
    compras_activos_fijos_gravadas: Decimal = Decimal("0")
    # 505 - Compras locales gravadas tarifa 0% (no da crédito)
    compras_locales_0: Decimal = Decimal("0")
    # 507 - Importaciones de bienes (excluye activos fijos)
    importaciones_bienes: Decimal = Decimal("0")
    # 509 - Importaciones de activos fijos
    importaciones_activos_fijos: Decimal = Decimal("0")
    # 511 - Importaciones de bienes gravados tarifa 0%
    importaciones_0: Decimal = Decimal("0")

    # 513 - Total adquisiciones y pagos (suma 501-511)
    @property
    def total_adquisiciones(self) -> Decimal:
        return (
            self.compras_locales_gravadas +
            self.compras_activos_fijos_gravadas +
            self.compras_locales_0 +
            self.importaciones_bienes +
            self.importaciones_activos_fijos +
            self.importaciones_0
        )

    # IMPUESTOS (Casilleros 600)
    tarifa_iva: Decimal = Decimal("0.15")  # 15% vigente 2025

    # 601 - IVA causado en ventas
    @property
    def iva_ventas(self) -> Decimal:
        base = self.ventas_locales_gravadas + self.ventas_activos_fijos_gravadas
        return (base * self.tarifa_iva).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # 602 - Liquidación IVA del período anterior
    liquidacion_periodo_anterior: Decimal = Decimal("0")

    # 605 - IVA pagado en compras
    @property
    def iva_compras(self) -> Decimal:
        base = self.compras_locales_gravadas + self.compras_activos_fijos_gravadas
        return (base * self.tarifa_iva).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # 609 - IVA pagado en importaciones
    @property
    def iva_importaciones(self) -> Decimal:
        base = self.importaciones_bienes + self.importaciones_activos_fijos
        return (base * self.tarifa_iva).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # Retenciones de IVA que le han efectuado
    retenciones_iva_recibidas: Decimal = Decimal("0")

    # RESUMEN
    # 699 - Total crédito tributario del mes
    @property
    def credito_tributario_mes(self) -> Decimal:
        return self.iva_compras + self.iva_importaciones + self.retenciones_iva_recibidas

    # 699 - Crédito tributario de meses anteriores
    credito_tributario_anterior: Decimal = Decimal("0")

    # 721 - IVA a pagar
    @property
    def iva_a_pagar(self) -> Decimal:
        impuesto = self.iva_ventas - self.credito_tributario_mes - self.credito_tributario_anterior
        return max(Decimal("0"), impuesto)

    # 723 - Crédito tributario para próximo mes
    @property
    def credito_proximo_mes(self) -> Decimal:
        impuesto = self.iva_ventas - self.credito_tributario_mes - self.credito_tributario_anterior
        if impuesto < 0:
            return abs(impuesto)
        return Decimal("0")

    # Datos adicionales
    total_facturas_emitidas: int = 0
    total_facturas_anuladas: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convierte a diccionario para serialización."""
        return {
            "anio": self.anio,
            "mes": self.mes,
            "ruc": self.ruc,
            "razon_social": self.razon_social,
            "ventas": {
                "401_ventas_locales_gravadas": float(self.ventas_locales_gravadas),
                "403_ventas_activos_fijos_gravadas": float(self.ventas_activos_fijos_gravadas),
                "405_ventas_locales_0": float(self.ventas_locales_0),
                "407_ventas_activos_fijos_0": float(self.ventas_activos_fijos_0),
                "409_exportaciones_bienes": float(self.exportaciones_bienes),
                "411_exportaciones_servicios": float(self.exportaciones_servicios),
                "413_ventas_con_retencion": float(self.ventas_con_retencion),
                "415_total_ventas_netas": float(self.total_ventas_netas),
            },
            "compras": {
                "501_compras_locales_gravadas": float(self.compras_locales_gravadas),
                "503_compras_activos_fijos_gravadas": float(self.compras_activos_fijos_gravadas),
                "505_compras_locales_0": float(self.compras_locales_0),
                "507_importaciones_bienes": float(self.importaciones_bienes),
                "509_importaciones_activos_fijos": float(self.importaciones_activos_fijos),
                "511_importaciones_0": float(self.importaciones_0),
                "513_total_adquisiciones": float(self.total_adquisiciones),
            },
            "impuestos": {
                "601_iva_ventas": float(self.iva_ventas),
                "605_iva_compras": float(self.iva_compras),
                "609_iva_importaciones": float(self.iva_importaciones),
                "credito_tributario_mes": float(self.credito_tributario_mes),
                "credito_tributario_anterior": float(self.credito_tributario_anterior),
                "721_iva_a_pagar": float(self.iva_a_pagar),
                "723_credito_proximo_mes": float(self.credito_proximo_mes),
            },
            "estadisticas": {
                "total_facturas_emitidas": self.total_facturas_emitidas,
                "total_facturas_anuladas": self.total_facturas_anuladas,
            }
        }

    def to_text(self) -> str:
        """Genera reporte en texto para llenado manual."""
        lineas = [
            "=" * 70,
            f"DATOS PARA DECLARACIÓN IVA - FORMULARIO 2011",
            f"Período: {self.mes:02d}/{self.anio}",
            "=" * 70,
            f"RUC: {self.ruc}",
            f"Razón Social: {self.razon_social}",
            "",
            "VENTAS Y OTRAS OPERACIONES",
            "-" * 70,
            f"401  Ventas locales gravadas (excl. activos fijos)   ${self.ventas_locales_gravadas:>12,.2f}",
            f"403  Ventas de activos fijos gravadas               ${self.ventas_activos_fijos_gravadas:>12,.2f}",
            f"405  Ventas locales tarifa 0%                       ${self.ventas_locales_0:>12,.2f}",
            f"407  Ventas activos fijos tarifa 0%                 ${self.ventas_activos_fijos_0:>12,.2f}",
            f"409  Exportaciones de bienes                        ${self.exportaciones_bienes:>12,.2f}",
            f"411  Exportaciones de servicios                     ${self.exportaciones_servicios:>12,.2f}",
            f"413  Ventas con retención IVA                       ${self.ventas_con_retencion:>12,.2f}",
            "-" * 70,
            f"415  TOTAL VENTAS NETAS                             ${self.total_ventas_netas:>12,.2f}",
            "",
            "ADQUISICIONES Y PAGOS",
            "-" * 70,
            f"501  Compras locales gravadas (excl. activos fijos) ${self.compras_locales_gravadas:>12,.2f}",
            f"503  Compras activos fijos gravadas                 ${self.compras_activos_fijos_gravadas:>12,.2f}",
            f"505  Compras locales tarifa 0%                      ${self.compras_locales_0:>12,.2f}",
            f"507  Importaciones bienes                           ${self.importaciones_bienes:>12,.2f}",
            f"509  Importaciones activos fijos                    ${self.importaciones_activos_fijos:>12,.2f}",
            f"511  Importaciones tarifa 0%                        ${self.importaciones_0:>12,.2f}",
            "-" * 70,
            f"513  TOTAL ADQUISICIONES                            ${self.total_adquisiciones:>12,.2f}",
            "",
            "RESUMEN IMPOSITIVO",
            "-" * 70,
            f"601  IVA en ventas (15%)                            ${self.iva_ventas:>12,.2f}",
            f"605  (-) IVA en compras                             ${self.iva_compras:>12,.2f}",
            f"609  (-) IVA en importaciones                       ${self.iva_importaciones:>12,.2f}",
            f"     (-) Retenciones IVA recibidas                  ${self.retenciones_iva_recibidas:>12,.2f}",
            f"     (-) Crédito tributario anterior                ${self.credito_tributario_anterior:>12,.2f}",
            "-" * 70,
        ]

        if self.iva_a_pagar > 0:
            lineas.append(f"721  IVA A PAGAR                                    ${self.iva_a_pagar:>12,.2f}")
        else:
            lineas.append(f"721  IVA A PAGAR                                    ${Decimal('0'):>12,.2f}")

        if self.credito_proximo_mes > 0:
            lineas.append(f"723  Crédito tributario próximo mes                 ${self.credito_proximo_mes:>12,.2f}")

        lineas.extend([
            "",
            "=" * 70,
            f"Facturas emitidas: {self.total_facturas_emitidas}",
            f"Facturas anuladas: {self.total_facturas_anuladas}",
            "=" * 70,
        ])

        return "\n".join(lineas)


class CalculadorIVA:
    """
    Calculador de datos para declaración IVA.

    Consulta la base de datos y genera los datos del formulario 2011.
    """

    def __init__(self, supabase_client):
        self.supabase = supabase_client

    def calcular_periodo(
        self,
        anio: int,
        mes: int,
        ruc: str,
        razon_social: str,
        credito_anterior: Decimal = Decimal("0")
    ) -> DatosDeclaracionIVA:
        """
        Calcula los datos de IVA para un período.

        Args:
            anio: Año del período
            mes: Mes del período (1-12)
            ruc: RUC del contribuyente
            razon_social: Razón social
            credito_anterior: Crédito tributario del mes anterior

        Returns:
            DatosDeclaracionIVA con todos los cálculos
        """
        import calendar

        fecha_inicio = f"{anio}-{mes:02d}-01"
        ultimo_dia = calendar.monthrange(anio, mes)[1]
        fecha_fin = f"{anio}-{mes:02d}-{ultimo_dia:02d}"

        datos = DatosDeclaracionIVA(
            anio=anio,
            mes=mes,
            ruc=ruc,
            razon_social=razon_social,
            credito_tributario_anterior=credito_anterior,
        )

        # Obtener facturas emitidas (tipo 01)
        facturas = self.supabase.table('comprobantes_electronicos').select(
            'subtotal_15, subtotal_0, iva, estado'
        ).eq(
            'tipo_comprobante', '01'
        ).gte(
            'fecha_emision', fecha_inicio
        ).lte(
            'fecha_emision', fecha_fin
        ).execute().data

        # Sumar ventas autorizadas
        for f in facturas:
            if f.get('estado') == 'authorized':
                datos.ventas_locales_gravadas += Decimal(str(f.get('subtotal_15', 0) or 0))
                datos.ventas_locales_0 += Decimal(str(f.get('subtotal_0', 0) or 0))
                datos.total_facturas_emitidas += 1
            elif f.get('estado') == 'cancelled':
                datos.total_facturas_anuladas += 1

        # ========== OBTENER COMPRAS ==========
        # Consultar facturas de compra registradas (tabla antigua)
        try:
            facturas_compra = self.supabase.table('facturas_compra').select(
                'subtotal_15, subtotal_0, iva, estado'
            ).gte(
                'fecha_emision', fecha_inicio
            ).lte(
                'fecha_emision', fecha_fin
            ).neq('estado', 'anulada').execute().data or []

            for fc in facturas_compra:
                datos.compras_locales_gravadas += Decimal(str(fc.get('subtotal_15', 0) or 0))
                datos.compras_locales_0 += Decimal(str(fc.get('subtotal_0', 0) or 0))
        except Exception:
            pass  # Tabla puede no existir

        # Consultar facturas recibidas (incluye Liquidaciones de Compra tipo 03)
        try:
            facturas_recibidas = self.supabase.table('facturas_recibidas').select(
                'subtotal_15, subtotal_0, subtotal_exento, iva, estado, tipo_comprobante'
            ).gte(
                'fecha_emision', fecha_inicio
            ).lte(
                'fecha_emision', fecha_fin
            ).neq('estado', 'anulada').execute().data or []

            for fr in facturas_recibidas:
                # Subtotales gravados y tarifa 0
                datos.compras_locales_gravadas += Decimal(str(fr.get('subtotal_15', 0) or 0))
                datos.compras_locales_0 += Decimal(str(fr.get('subtotal_0', 0) or 0))
                # Exentos (cripto, etc.) - no generan credito tributario
                # pero se reportan en casillero 505 junto con tarifa 0
                datos.compras_locales_0 += Decimal(str(fr.get('subtotal_exento', 0) or 0))
        except Exception:
            pass  # Tabla puede no existir

        # ========== ALTERNATIVA: OBTENER IVA DESDE MOVIMIENTOS CONTABLES ==========
        # Si no hay datos de facturas, consultar las cuentas de IVA directamente
        if datos.iva_ventas == Decimal("0") and datos.iva_compras == Decimal("0"):
            try:
                # IVA en Ventas (2.1.3.01) - Cuenta de Pasivo
                # El saldo es Haber - Debe (lo que debemos al SRI)
                mov_iva_ventas = self.supabase.table('movimientos_contables').select(
                    'debe, haber, asientos_contables!inner(fecha, estado)'
                ).eq('cuenta_codigo', '2.1.3.01').gte(
                    'asientos_contables.fecha', fecha_inicio
                ).lte(
                    'asientos_contables.fecha', fecha_fin
                ).eq('asientos_contables.estado', 'posted').execute().data or []

                iva_ventas_haber = sum(Decimal(str(m.get('haber', 0) or 0)) for m in mov_iva_ventas)
                iva_ventas_debe = sum(Decimal(str(m.get('debe', 0) or 0)) for m in mov_iva_ventas)

                # Si hay IVA registrado en movimientos, calcular ventas gravadas
                if iva_ventas_haber > 0:
                    # Calcular base imponible: IVA / tarifa
                    base_ventas = (iva_ventas_haber / datos.tarifa_iva).quantize(
                        Decimal("0.01"), ROUND_HALF_UP
                    )
                    datos.ventas_locales_gravadas = base_ventas

                # IVA en Compras (1.1.3.01) - Cuenta de Activo
                # El saldo es Debe - Haber (crédito tributario)
                mov_iva_compras = self.supabase.table('movimientos_contables').select(
                    'debe, haber, asientos_contables!inner(fecha, estado)'
                ).eq('cuenta_codigo', '1.1.3.01').gte(
                    'asientos_contables.fecha', fecha_inicio
                ).lte(
                    'asientos_contables.fecha', fecha_fin
                ).eq('asientos_contables.estado', 'posted').execute().data or []

                iva_compras_debe = sum(Decimal(str(m.get('debe', 0) or 0)) for m in mov_iva_compras)
                iva_compras_haber = sum(Decimal(str(m.get('haber', 0) or 0)) for m in mov_iva_compras)

                # Si hay IVA en compras registrado, calcular base
                if iva_compras_debe > 0:
                    base_compras = (iva_compras_debe / datos.tarifa_iva).quantize(
                        Decimal("0.01"), ROUND_HALF_UP
                    )
                    datos.compras_locales_gravadas = base_compras

            except Exception:
                pass  # Si falla la consulta de movimientos, mantener los valores actuales

        return datos

    def calcular_desde_ats(
        self,
        anio: int,
        mes: int,
        ruc: str,
        razon_social: str,
        credito_anterior: Decimal = Decimal("0")
    ) -> DatosDeclaracionIVA:
        """
        Calcula IVA usando los mismos datos que el ATS.

        Útil para verificar consistencia entre ATS e IVA.
        """
        return self.calcular_periodo(anio, mes, ruc, razon_social, credito_anterior)

    def generar_resumen_anual(
        self,
        anio: int,
        ruc: str,
        razon_social: str
    ) -> list[DatosDeclaracionIVA]:
        """
        Genera resumen de todos los meses del año.

        Returns:
            Lista de DatosDeclaracionIVA por cada mes
        """
        resumen = []
        credito = Decimal("0")

        for mes in range(1, 13):
            datos = self.calcular_periodo(anio, mes, ruc, razon_social, credito)
            resumen.append(datos)
            # El crédito del próximo mes es el crédito que quedó
            credito = datos.credito_proximo_mes

        return resumen
