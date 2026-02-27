"""
ECUCONDOR - Conciliador de Transacciones
Concilia transacciones bancarias con comprobantes electrónicos.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from src.ingestor.models import (
    EstadoTransaccion,
    TipoTransaccion,
    TransaccionBancaria,
)

logger = structlog.get_logger(__name__)


@dataclass
class MatchCandidate:
    """Candidato de conciliación."""

    comprobante_id: str
    numero_comprobante: str
    tipo_comprobante: str
    fecha_emision: date
    cliente_nombre: str
    cliente_identificacion: str
    monto_total: Decimal
    score: float = 0.0
    razones: list[str] = field(default_factory=list)


@dataclass
class ResultadoConciliacion:
    """Resultado del proceso de conciliación."""

    transaccion: TransaccionBancaria
    estado: str  # "conciliado", "sin_match", "multiples_candidatos", "error"
    candidatos: list[MatchCandidate] = field(default_factory=list)
    match_seleccionado: MatchCandidate | None = None
    confianza: float = 0.0


@dataclass
class ResumenConciliacion:
    """Resumen de proceso de conciliación masiva."""

    total_transacciones: int = 0
    conciliadas_automatico: int = 0
    multiples_candidatos: int = 0
    sin_match: int = 0
    errores: int = 0
    resultados: list[ResultadoConciliacion] = field(default_factory=list)


class Reconciler:
    """
    Conciliador de transacciones bancarias con comprobantes.

    Estrategias de matching:
    1. Match exacto por monto y fecha
    2. Match por referencia en descripción
    3. Match por identificación de contraparte
    4. Match por monto con tolerancia temporal
    """

    # Patrones para extraer referencias de comprobantes
    PATRONES_FACTURA = [
        # Formato estándar SRI: 001-001-000000001
        re.compile(r"(\d{3})-(\d{3})-(\d{9})"),
        # Sin guiones: 001001000000001
        re.compile(r"(\d{3})(\d{3})(\d{9})"),
        # Parcial: FAC 000000001
        re.compile(r"(?:FAC|FACT|FACTURA)[.\s#]*(\d{6,9})", re.IGNORECASE),
        # Solo secuencial
        re.compile(r"(?:SEC|SECUENCIAL|NRO)[.\s#]*(\d{6,9})", re.IGNORECASE),
    ]

    # Patrones para extraer clave de acceso (49 dígitos)
    PATRON_CLAVE_ACCESO = re.compile(r"\b(\d{49})\b")

    def __init__(
        self,
        tolerancia_monto: Decimal = Decimal("0.01"),
        tolerancia_dias: int = 7,
        umbral_confianza: float = 0.7,
    ):
        """
        Inicializa el conciliador.

        Args:
            tolerancia_monto: Tolerancia en diferencia de monto
            tolerancia_dias: Días de tolerancia para matching temporal
            umbral_confianza: Umbral mínimo para auto-conciliación
        """
        self.tolerancia_monto = tolerancia_monto
        self.tolerancia_dias = tolerancia_dias
        self.umbral_confianza = umbral_confianza

    async def conciliar(
        self,
        transaccion: TransaccionBancaria,
        comprobantes: list[dict[str, Any]],
    ) -> ResultadoConciliacion:
        """
        Intenta conciliar una transacción con comprobantes.

        Args:
            transaccion: Transacción bancaria
            comprobantes: Lista de comprobantes candidatos

        Returns:
            Resultado de conciliación
        """
        resultado = ResultadoConciliacion(transaccion=transaccion)

        # Solo conciliar créditos (ingresos)
        if transaccion.tipo != TipoTransaccion.CREDITO:
            resultado.estado = "no_aplica"
            return resultado

        try:
            # Buscar candidatos
            candidatos = self._buscar_candidatos(transaccion, comprobantes)

            if not candidatos:
                resultado.estado = "sin_match"
                return resultado

            # Ordenar por score
            candidatos.sort(key=lambda x: x.score, reverse=True)
            resultado.candidatos = candidatos

            # Verificar si hay match claro
            if len(candidatos) == 1 and candidatos[0].score >= self.umbral_confianza:
                resultado.estado = "conciliado"
                resultado.match_seleccionado = candidatos[0]
                resultado.confianza = candidatos[0].score
            elif candidatos[0].score >= 0.9:
                # Score muy alto, auto-conciliar aunque haya otros
                resultado.estado = "conciliado"
                resultado.match_seleccionado = candidatos[0]
                resultado.confianza = candidatos[0].score
            else:
                resultado.estado = "multiples_candidatos"

        except Exception as e:
            logger.error("Error en conciliación", error=str(e), exc_info=True)
            resultado.estado = "error"

        return resultado

    async def conciliar_lote(
        self,
        transacciones: list[TransaccionBancaria],
        comprobantes: list[dict[str, Any]],
    ) -> ResumenConciliacion:
        """
        Concilia un lote de transacciones.

        Args:
            transacciones: Lista de transacciones
            comprobantes: Lista de comprobantes

        Returns:
            Resumen de conciliación
        """
        resumen = ResumenConciliacion(total_transacciones=len(transacciones))

        for tx in transacciones:
            resultado = await self.conciliar(tx, comprobantes)
            resumen.resultados.append(resultado)

            if resultado.estado == "conciliado":
                resumen.conciliadas_automatico += 1
            elif resultado.estado == "multiples_candidatos":
                resumen.multiples_candidatos += 1
            elif resultado.estado == "sin_match":
                resumen.sin_match += 1
            elif resultado.estado == "error":
                resumen.errores += 1

        logger.info(
            "Conciliación masiva completada",
            total=resumen.total_transacciones,
            conciliadas=resumen.conciliadas_automatico,
            multiples=resumen.multiples_candidatos,
            sin_match=resumen.sin_match,
            errores=resumen.errores,
        )

        return resumen

    def _buscar_candidatos(
        self,
        transaccion: TransaccionBancaria,
        comprobantes: list[dict[str, Any]],
    ) -> list[MatchCandidate]:
        """
        Busca comprobantes candidatos para una transacción.

        Args:
            transaccion: Transacción bancaria
            comprobantes: Lista de comprobantes

        Returns:
            Lista de candidatos con scores
        """
        candidatos: list[MatchCandidate] = []

        # Extraer información de la descripción
        info_descripcion = self._extraer_info_descripcion(transaccion)

        for comp in comprobantes:
            score = 0.0
            razones: list[str] = []

            # Crear candidato base
            candidato = MatchCandidate(
                comprobante_id=comp["id"],
                numero_comprobante=f"{comp['establecimiento']}-{comp['punto_emision']}-{comp['secuencial']}",
                tipo_comprobante=comp["tipo_comprobante"],
                fecha_emision=date.fromisoformat(comp["fecha_emision"]) if isinstance(comp["fecha_emision"], str) else comp["fecha_emision"],
                cliente_nombre=comp.get("cliente_razon_social", ""),
                cliente_identificacion=comp.get("cliente_identificacion", ""),
                monto_total=Decimal(str(comp["importe_total"])),
            )

            # === CRITERIOS DE MATCHING ===

            # 1. Match por clave de acceso (máxima confianza)
            if info_descripcion.get("clave_acceso"):
                if comp.get("clave_acceso") == info_descripcion["clave_acceso"]:
                    score += 0.95
                    razones.append("clave_acceso_exacta")

            # 2. Match por número de factura
            if info_descripcion.get("numero_factura"):
                numero_comp = f"{comp['establecimiento']}-{comp['punto_emision']}-{comp['secuencial']}"
                if info_descripcion["numero_factura"] == numero_comp:
                    score += 0.8
                    razones.append("numero_factura_exacto")
                elif info_descripcion.get("secuencial") == comp["secuencial"]:
                    score += 0.5
                    razones.append("secuencial_match")

            # 3. Match por monto exacto
            diff_monto = abs(transaccion.monto - candidato.monto_total)
            if diff_monto <= self.tolerancia_monto:
                score += 0.4
                razones.append("monto_exacto")
            elif diff_monto <= Decimal("1.00"):
                score += 0.2
                razones.append("monto_cercano")

            # 4. Match por fecha cercana
            diff_dias = abs((transaccion.fecha - candidato.fecha_emision).days)
            if diff_dias == 0:
                score += 0.2
                razones.append("fecha_exacta")
            elif diff_dias <= 3:
                score += 0.1
                razones.append("fecha_cercana")
            elif diff_dias > self.tolerancia_dias:
                score -= 0.2  # Penalizar si muy lejano

            # 5. Match por identificación de contraparte
            if transaccion.contraparte_identificacion:
                if transaccion.contraparte_identificacion == comp.get("cliente_identificacion"):
                    score += 0.3
                    razones.append("identificacion_match")

            # 6. Match por nombre de contraparte (parcial)
            if transaccion.contraparte_nombre and comp.get("cliente_razon_social"):
                nombre_tx = transaccion.contraparte_nombre.lower()
                nombre_comp = comp["cliente_razon_social"].lower()
                if nombre_tx in nombre_comp or nombre_comp in nombre_tx:
                    score += 0.15
                    razones.append("nombre_similar")

            # Solo agregar si tiene algún score positivo
            if score > 0:
                candidato.score = min(score, 1.0)  # Máximo 1.0
                candidato.razones = razones
                candidatos.append(candidato)

        return candidatos

    def _extraer_info_descripcion(
        self,
        transaccion: TransaccionBancaria,
    ) -> dict[str, str | None]:
        """
        Extrae información relevante de la descripción.

        Args:
            transaccion: Transacción

        Returns:
            Diccionario con información extraída
        """
        info: dict[str, str | None] = {
            "clave_acceso": None,
            "numero_factura": None,
            "secuencial": None,
        }

        descripcion = transaccion.descripcion_normalizada or transaccion.descripcion_original

        # Buscar clave de acceso
        match = self.PATRON_CLAVE_ACCESO.search(descripcion)
        if match:
            info["clave_acceso"] = match.group(1)

        # Buscar número de factura
        for patron in self.PATRONES_FACTURA:
            match = patron.search(descripcion)
            if match:
                grupos = match.groups()
                if len(grupos) == 3:
                    # Formato completo: establecimiento-punto-secuencial
                    info["numero_factura"] = f"{grupos[0]}-{grupos[1]}-{grupos[2]}"
                    info["secuencial"] = grupos[2]
                elif len(grupos) == 1:
                    # Solo secuencial
                    info["secuencial"] = grupos[0].zfill(9)
                break

        return info

    def sugerir_conciliacion_manual(
        self,
        transaccion: TransaccionBancaria,
        candidatos: list[MatchCandidate],
    ) -> dict[str, Any]:
        """
        Genera información para conciliación manual.

        Args:
            transaccion: Transacción a conciliar
            candidatos: Candidatos disponibles

        Returns:
            Información para UI
        """
        return {
            "transaccion": {
                "id": str(transaccion.id) if transaccion.id else None,
                "fecha": transaccion.fecha.isoformat(),
                "monto": float(transaccion.monto),
                "descripcion": transaccion.descripcion_normalizada or transaccion.descripcion_original,
                "contraparte": transaccion.contraparte_nombre,
            },
            "candidatos": [
                {
                    "comprobante_id": c.comprobante_id,
                    "numero": c.numero_comprobante,
                    "fecha": c.fecha_emision.isoformat(),
                    "monto": float(c.monto_total),
                    "cliente": c.cliente_nombre,
                    "score": c.score,
                    "razones": c.razones,
                }
                for c in candidatos
            ],
            "total_candidatos": len(candidatos),
        }


class ReconciliationRules:
    """
    Reglas adicionales de conciliación para el modelo de negocio.

    Para ECUCONDOR (alquiler de vehículos), implementa la lógica
    de split de comisión:
    - 1.5% comisión (ingreso)
    - 98.5% pasivo (a devolver a propietario)
    """

    PORCENTAJE_COMISION = Decimal("0.015")  # 1.5%

    @classmethod
    def calcular_split_comision(
        cls,
        monto_total: Decimal,
    ) -> dict[str, Decimal]:
        """
        Calcula el split de comisión de una transacción.

        Args:
            monto_total: Monto total recibido

        Returns:
            Diccionario con montos para cada cuenta
        """
        comision = (monto_total * cls.PORCENTAJE_COMISION).quantize(Decimal("0.01"))
        pasivo = monto_total - comision

        return {
            "ingreso_comision": comision,
            "pasivo_propietario": pasivo,
            "total": monto_total,
        }

    @classmethod
    def generar_asiento_comision(
        cls,
        transaccion: TransaccionBancaria,
        comprobante_id: str,
    ) -> list[dict[str, Any]]:
        """
        Genera los movimientos contables para una transacción con comisión.

        Asiento:
        - Debe: 1.1.03 Bancos (total)
        - Haber: 4.1.01 Ingresos por comisión (1.5%)
        - Haber: 2.1.09 Cuentas por pagar propietarios (98.5%)

        Args:
            transaccion: Transacción bancaria
            comprobante_id: ID del comprobante relacionado

        Returns:
            Lista de movimientos para el asiento
        """
        split = cls.calcular_split_comision(transaccion.monto)

        movimientos = [
            # Debe: Bancos
            {
                "cuenta": "1.1.03",
                "debe": split["total"],
                "haber": Decimal("0"),
                "concepto": f"Cobro factura - {transaccion.descripcion_normalizada or transaccion.descripcion_original}",
            },
            # Haber: Ingreso comisión
            {
                "cuenta": "4.1.01",
                "debe": Decimal("0"),
                "haber": split["ingreso_comision"],
                "concepto": f"Comisión 1.5% - Factura",
            },
            # Haber: Pasivo propietario
            {
                "cuenta": "2.1.09",
                "debe": Decimal("0"),
                "haber": split["pasivo_propietario"],
                "concepto": f"Por pagar a propietario - 98.5%",
            },
        ]

        return movimientos
