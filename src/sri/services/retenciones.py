"""
Servicio de Retenciones SRI.
Manejo de retenciones de Impuesto a la Renta (IR) e IVA.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class RetencionIR:
    """Datos de una retención de IR."""
    codigo: str
    concepto: str
    porcentaje: Decimal
    base: Decimal = Decimal("0")
    valor: Decimal = Decimal("0")


@dataclass
class RetencionIVA:
    """Datos de una retención de IVA."""
    codigo: str
    concepto: str
    porcentaje: Decimal
    base: Decimal = Decimal("0")
    valor: Decimal = Decimal("0")


@dataclass
class ResultadoRetenciones:
    """Resultado del cálculo de retenciones."""
    ir: RetencionIR
    iva: RetencionIVA
    total_retenciones: Decimal
    valor_a_pagar: Decimal  # subtotal + iva - retenciones


# Tabla local de retenciones IR (fallback si no hay DB)
TABLA_IR_2025 = {
    "303": ("Honorarios profesionales", Decimal("10.00")),
    "304": ("Servicios predomina intelecto", Decimal("8.00")),
    "307": ("Servicios predomina mano de obra", Decimal("2.00")),
    "308": ("Servicios entre sociedades", Decimal("2.00")),
    "309": ("Servicios publicidad y comunicación", Decimal("1.75")),
    "310": ("Transporte privado", Decimal("1.00")),
    "312": ("Transferencia de bienes muebles", Decimal("1.00")),
    "319": ("Arrendamiento mercantil", Decimal("1.00")),
    "320": ("Arrendamiento bienes inmuebles", Decimal("8.00")),
    "322": ("Seguros y reaseguros", Decimal("1.75")),
    "323": ("Rendimientos financieros", Decimal("2.00")),
    "332": ("Bienes no producidos en el país", Decimal("1.75")),
    "332B": ("Bienes agrícolas", Decimal("1.00")),
    "340": ("Otras 1%", Decimal("1.00")),
    "341": ("Otras 2%", Decimal("2.00")),
    "342": ("Otras 8%", Decimal("8.00")),
}

# Tabla local de retenciones IVA (fallback si no hay DB)
TABLA_IVA_2025 = {
    "721": ("Retención 10% IVA", Decimal("10.00")),
    "723": ("Retención 20% IVA", Decimal("20.00")),
    "725": ("Retención 30% IVA", Decimal("30.00")),
    "727": ("Retención 70% IVA", Decimal("70.00")),
    "729": ("Retención 100% IVA", Decimal("100.00")),
    "731": ("No aplica retención", Decimal("0.00")),
}

# Tipos de contribuyente
TIPOS_CONTRIBUYENTE = {
    "ESPECIAL": "Contribuyente Especial",
    "SOCIEDAD": "Sociedad",
    "PN_OBLIG": "Persona Natural Obligada",
    "PN_NO_OBLIG": "Persona Natural No Obligada",
    "RISE": "RISE",
    "RIMPE_EMP": "RIMPE Emprendedor",
    "RIMPE_NEG": "RIMPE Negocio Popular",
}


class ServicioRetenciones:
    """Servicio para cálculo y consulta de retenciones."""

    def __init__(self, supabase_client=None):
        self.supabase = supabase_client

    def obtener_conceptos_ir(self) -> list[dict[str, Any]]:
        """Obtiene la lista de conceptos de retención IR."""
        if self.supabase:
            try:
                result = self.supabase.table('conceptos_retencion_ir').select(
                    'codigo_sri, concepto, porcentaje'
                ).eq('activo', True).order('codigo_sri').execute()
                return result.data
            except Exception as e:
                logger.warning("Error obteniendo conceptos IR de DB", error=str(e))

        # Fallback a tabla local
        return [
            {"codigo_sri": k, "concepto": v[0], "porcentaje": float(v[1])}
            for k, v in TABLA_IR_2025.items()
        ]

    def obtener_conceptos_iva(self) -> list[dict[str, Any]]:
        """Obtiene la lista de conceptos de retención IVA."""
        if self.supabase:
            try:
                result = self.supabase.table('conceptos_retencion_iva').select(
                    'codigo_sri, concepto, porcentaje'
                ).eq('activo', True).order('codigo_sri').execute()
                return result.data
            except Exception as e:
                logger.warning("Error obteniendo conceptos IVA de DB", error=str(e))

        # Fallback a tabla local
        return [
            {"codigo_sri": k, "concepto": v[0], "porcentaje": float(v[1])}
            for k, v in TABLA_IVA_2025.items()
        ]

    def obtener_porcentaje_ir(self, codigo: str) -> Decimal:
        """Obtiene el porcentaje de retención IR para un código."""
        if self.supabase:
            try:
                result = self.supabase.rpc(
                    'obtener_retencion_ir',
                    {'p_codigo_concepto': codigo}
                ).execute()
                if result.data is not None:
                    return Decimal(str(result.data))
            except Exception as e:
                logger.warning("Error obteniendo porcentaje IR de DB", error=str(e))

        # Fallback a tabla local
        if codigo in TABLA_IR_2025:
            return TABLA_IR_2025[codigo][1]
        return Decimal("0")

    def obtener_retencion_iva(
        self,
        tipo_agente: str,
        tipo_proveedor: str,
        tipo_transaccion: str
    ) -> tuple[str, Decimal]:
        """
        Obtiene el código y porcentaje de retención IVA según la matriz.

        Args:
            tipo_agente: Tipo de contribuyente del comprador (ESPECIAL, SOCIEDAD, etc.)
            tipo_proveedor: Tipo de contribuyente del proveedor
            tipo_transaccion: Tipo de transacción (BIENES, SERVICIOS, PROFESIONALES, etc.)

        Returns:
            Tuple con (código de retención, porcentaje)
        """
        if self.supabase:
            try:
                result = self.supabase.rpc(
                    'obtener_retencion_iva',
                    {
                        'p_tipo_agente': tipo_agente,
                        'p_tipo_sujeto': tipo_proveedor,
                        'p_tipo_transaccion': tipo_transaccion
                    }
                ).execute()
                if result.data:
                    row = result.data[0]
                    return row['codigo_retencion'], Decimal(str(row['porcentaje']))
            except Exception as e:
                logger.warning("Error obteniendo retención IVA de DB", error=str(e))

        # Fallback: lógica simplificada
        return self._calcular_iva_local(tipo_agente, tipo_proveedor, tipo_transaccion)

    def _calcular_iva_local(
        self,
        tipo_agente: str,
        tipo_proveedor: str,
        tipo_transaccion: str
    ) -> tuple[str, Decimal]:
        """Calcula retención IVA usando lógica local."""
        # Contribuyente especial siempre retiene
        if tipo_agente == "ESPECIAL":
            if tipo_proveedor in ["PN_NO_OBLIG", "RISE"]:
                if tipo_transaccion in ["PROFESIONALES", "ARRIENDO", "LIQ_COMPRAS"]:
                    return "729", Decimal("100")
                elif tipo_transaccion == "SERVICIOS":
                    return "729", Decimal("100")
                else:
                    return "721", Decimal("10")
            elif tipo_transaccion == "CONSTRUCCION":
                return "725", Decimal("30")
            elif tipo_transaccion == "SERVICIOS":
                return "723", Decimal("20")
            else:
                return "721", Decimal("10")

        # Sociedad
        elif tipo_agente == "SOCIEDAD":
            if tipo_proveedor in ["PN_NO_OBLIG"]:
                if tipo_transaccion in ["PROFESIONALES", "ARRIENDO", "LIQ_COMPRAS", "SERVICIOS"]:
                    return "729", Decimal("100")
                else:
                    return "721", Decimal("10")
            # Sociedad a sociedad no retiene
            return "731", Decimal("0")

        # Por defecto no retiene
        return "731", Decimal("0")

    def calcular_retenciones(
        self,
        subtotal: Decimal,
        iva: Decimal,
        codigo_ir: str,
        tipo_agente: str = "SOCIEDAD",
        tipo_proveedor: str = "SOCIEDAD",
        tipo_transaccion: str = "SERVICIOS"
    ) -> ResultadoRetenciones:
        """
        Calcula las retenciones para una compra.

        Args:
            subtotal: Subtotal de la factura (sin IVA)
            iva: Valor del IVA
            codigo_ir: Código del concepto de retención IR
            tipo_agente: Tipo de contribuyente del comprador
            tipo_proveedor: Tipo de contribuyente del proveedor
            tipo_transaccion: Tipo de transacción

        Returns:
            ResultadoRetenciones con los valores calculados
        """
        # Obtener datos de retención IR
        porcentaje_ir = self.obtener_porcentaje_ir(codigo_ir)
        valor_ir = (subtotal * porcentaje_ir / Decimal("100")).quantize(Decimal("0.01"))
        concepto_ir = TABLA_IR_2025.get(codigo_ir, ("Otro", Decimal("0")))[0]

        # Obtener datos de retención IVA
        codigo_iva, porcentaje_iva = self.obtener_retencion_iva(
            tipo_agente, tipo_proveedor, tipo_transaccion
        )
        valor_iva = (iva * porcentaje_iva / Decimal("100")).quantize(Decimal("0.01"))
        concepto_iva = TABLA_IVA_2025.get(codigo_iva, ("Otro", Decimal("0")))[0]

        # Total
        total_retenciones = valor_ir + valor_iva
        total_factura = subtotal + iva
        valor_a_pagar = total_factura - total_retenciones

        return ResultadoRetenciones(
            ir=RetencionIR(
                codigo=codigo_ir,
                concepto=concepto_ir,
                porcentaje=porcentaje_ir,
                base=subtotal,
                valor=valor_ir
            ),
            iva=RetencionIVA(
                codigo=codigo_iva,
                concepto=concepto_iva,
                porcentaje=porcentaje_iva,
                base=iva,
                valor=valor_iva
            ),
            total_retenciones=total_retenciones,
            valor_a_pagar=valor_a_pagar
        )

    def sugerir_retencion_ir(self, descripcion: str) -> list[dict[str, Any]]:
        """
        Sugiere códigos de retención IR basándose en la descripción.

        Args:
            descripcion: Descripción del gasto o servicio

        Returns:
            Lista de sugerencias con código, concepto, porcentaje y confianza
        """
        if self.supabase:
            try:
                result = self.supabase.rpc(
                    'sugerir_retencion_ir',
                    {'p_descripcion': descripcion}
                ).execute()
                if result.data:
                    return result.data
            except Exception as e:
                logger.warning("Error obteniendo sugerencias de DB", error=str(e))

        # Fallback: lógica local simplificada
        return self._sugerir_local(descripcion)

    def _sugerir_local(self, descripcion: str) -> list[dict[str, Any]]:
        """Sugiere retenciones usando lógica local."""
        desc_lower = descripcion.lower()
        sugerencias = []

        # Reglas de sugerencia
        if any(k in desc_lower for k in ['honorario', 'profesional', 'abogad', 'contador', 'doctor']):
            sugerencias.append({
                "codigo_sri": "303",
                "concepto": "Honorarios profesionales",
                "porcentaje": 10.00,
                "confianza": 0.95
            })

        if any(k in desc_lower for k in ['limpieza', 'mantenimiento', 'jardin', 'seguridad']):
            sugerencias.append({
                "codigo_sri": "307",
                "concepto": "Servicios predomina mano de obra",
                "porcentaje": 2.00,
                "confianza": 0.90
            })

        if any(k in desc_lower for k in ['transport', 'flete', 'courier', 'encomienda']):
            sugerencias.append({
                "codigo_sri": "310",
                "concepto": "Transporte privado",
                "porcentaje": 1.00,
                "confianza": 0.90
            })

        if any(k in desc_lower for k in ['arriendo', 'alquiler', 'arrendamiento']):
            sugerencias.append({
                "codigo_sri": "320",
                "concepto": "Arrendamiento bienes inmuebles",
                "porcentaje": 8.00,
                "confianza": 0.85
            })

        if any(k in desc_lower for k in ['publicidad', 'marketing', 'anuncio']):
            sugerencias.append({
                "codigo_sri": "309",
                "concepto": "Servicios publicidad",
                "porcentaje": 1.75,
                "confianza": 0.85
            })

        if any(k in desc_lower for k in ['servicio']):
            sugerencias.append({
                "codigo_sri": "308",
                "concepto": "Servicios entre sociedades",
                "porcentaje": 2.00,
                "confianza": 0.60
            })

        if any(k in desc_lower for k in ['compra', 'material', 'suministro', 'producto']):
            sugerencias.append({
                "codigo_sri": "312",
                "concepto": "Transferencia bienes muebles",
                "porcentaje": 1.00,
                "confianza": 0.60
            })

        # Ordenar por confianza
        sugerencias.sort(key=lambda x: x['confianza'], reverse=True)
        return sugerencias[:3]

    def obtener_tipos_contribuyente(self) -> dict[str, str]:
        """Obtiene el diccionario de tipos de contribuyente."""
        return TIPOS_CONTRIBUYENTE.copy()

    def obtener_tipos_transaccion(self) -> list[str]:
        """Obtiene la lista de tipos de transacción."""
        return [
            "BIENES",
            "SERVICIOS",
            "PROFESIONALES",
            "CONSTRUCCION",
            "ARRIENDO",
            "LIQ_COMPRAS"
        ]
