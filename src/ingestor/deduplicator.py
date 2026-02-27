"""
ECUCONDOR - Deduplicador de Transacciones
Detecta y maneja transacciones duplicadas durante la importación.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import structlog

from src.ingestor.models import (
    EstadoTransaccion,
    TransaccionBancaria,
)

logger = structlog.get_logger(__name__)


@dataclass
class ResultadoDeduplicacion:
    """Resultado del proceso de deduplicación."""

    transacciones_unicas: list[TransaccionBancaria] = field(default_factory=list)
    transacciones_duplicadas: list[TransaccionBancaria] = field(default_factory=list)
    total_procesadas: int = 0
    duplicados_por_hash: int = 0
    duplicados_por_similitud: int = 0


class Deduplicator:
    """
    Deduplicador de transacciones bancarias.

    Utiliza múltiples estrategias:
    1. Hash exacto - Detecta duplicados idénticos
    2. Similitud - Detecta duplicados con pequeñas diferencias
    3. Ventana temporal - Mismo monto en días cercanos
    """

    def __init__(
        self,
        ventana_dias: int = 3,
        tolerancia_monto: Decimal = Decimal("0.01"),
    ):
        """
        Inicializa el deduplicador.

        Args:
            ventana_dias: Días de tolerancia para duplicados temporales
            tolerancia_monto: Tolerancia en diferencia de monto
        """
        self.ventana_dias = ventana_dias
        self.tolerancia_monto = tolerancia_monto

    def deduplicar(
        self,
        transacciones: list[TransaccionBancaria],
        transacciones_existentes: list[TransaccionBancaria] | None = None,
    ) -> ResultadoDeduplicacion:
        """
        Deduplica un lote de transacciones.

        Args:
            transacciones: Transacciones nuevas a verificar
            transacciones_existentes: Transacciones ya en base de datos

        Returns:
            Resultado con transacciones únicas y duplicadas
        """
        resultado = ResultadoDeduplicacion(total_procesadas=len(transacciones))

        # Construir índice de hashes existentes
        hashes_existentes: set[str] = set()
        if transacciones_existentes:
            hashes_existentes = {tx.hash_unico for tx in transacciones_existentes}

        # Índice para detección por similitud
        indice_similitud: dict[str, list[TransaccionBancaria]] = {}

        # Hashes procesados en este lote
        hashes_procesados: set[str] = set()

        for tx in transacciones:
            es_duplicado = False
            razon = ""

            # 1. Verificar hash exacto contra existentes
            if tx.hash_unico in hashes_existentes:
                es_duplicado = True
                razon = "hash_existente"
                resultado.duplicados_por_hash += 1

            # 2. Verificar hash exacto en lote actual
            elif tx.hash_unico in hashes_procesados:
                es_duplicado = True
                razon = "hash_lote"
                resultado.duplicados_por_hash += 1

            # 3. Verificar similitud
            elif self._es_similar_a_existente(tx, indice_similitud):
                es_duplicado = True
                razon = "similitud"
                resultado.duplicados_por_similitud += 1

            # 4. Verificar similitud contra transacciones existentes
            elif transacciones_existentes and self._es_similar_a_lista(
                tx, transacciones_existentes
            ):
                es_duplicado = True
                razon = "similitud_existente"
                resultado.duplicados_por_similitud += 1

            if es_duplicado:
                tx.estado = EstadoTransaccion.DUPLICADA
                resultado.transacciones_duplicadas.append(tx)
                logger.debug(
                    "Transacción duplicada detectada",
                    hash=tx.hash_unico,
                    razon=razon,
                    fecha=tx.fecha.isoformat(),
                    monto=float(tx.monto),
                )
            else:
                resultado.transacciones_unicas.append(tx)
                hashes_procesados.add(tx.hash_unico)
                self._agregar_a_indice(tx, indice_similitud)

        logger.info(
            "Deduplicación completada",
            total=resultado.total_procesadas,
            unicas=len(resultado.transacciones_unicas),
            duplicadas=len(resultado.transacciones_duplicadas),
            por_hash=resultado.duplicados_por_hash,
            por_similitud=resultado.duplicados_por_similitud,
        )

        return resultado

    def _generar_clave_similitud(self, tx: TransaccionBancaria) -> str:
        """
        Genera clave para agrupación por similitud.

        La clave agrupa transacciones del mismo banco, cuenta,
        tipo y rango de monto similar.

        Args:
            tx: Transacción

        Returns:
            Clave de agrupación
        """
        # Redondear monto para agrupar similares
        monto_redondeado = int(tx.monto)

        return f"{tx.banco.value}|{tx.cuenta_bancaria}|{tx.tipo.value}|{monto_redondeado}"

    def _agregar_a_indice(
        self,
        tx: TransaccionBancaria,
        indice: dict[str, list[TransaccionBancaria]],
    ) -> None:
        """
        Agrega una transacción al índice de similitud.

        Args:
            tx: Transacción
            indice: Índice a actualizar
        """
        clave = self._generar_clave_similitud(tx)
        if clave not in indice:
            indice[clave] = []
        indice[clave].append(tx)

    def _es_similar_a_existente(
        self,
        tx: TransaccionBancaria,
        indice: dict[str, list[TransaccionBancaria]],
    ) -> bool:
        """
        Verifica si la transacción es similar a alguna del índice.

        Args:
            tx: Transacción a verificar
            indice: Índice de similitud

        Returns:
            True si es similar
        """
        clave = self._generar_clave_similitud(tx)
        candidatos = indice.get(clave, [])

        for candidato in candidatos:
            if self._son_similares(tx, candidato):
                return True

        return False

    def _es_similar_a_lista(
        self,
        tx: TransaccionBancaria,
        lista: list[TransaccionBancaria],
    ) -> bool:
        """
        Verifica si la transacción es similar a alguna de la lista.

        Args:
            tx: Transacción
            lista: Lista de transacciones

        Returns:
            True si es similar
        """
        for candidato in lista:
            # Filtro rápido por banco y cuenta
            if tx.banco != candidato.banco:
                continue
            if tx.cuenta_bancaria != candidato.cuenta_bancaria:
                continue

            if self._son_similares(tx, candidato):
                return True

        return False

    def _son_similares(
        self,
        tx1: TransaccionBancaria,
        tx2: TransaccionBancaria,
    ) -> bool:
        """
        Determina si dos transacciones son similares (posible duplicado).

        Criterios:
        - Mismo banco
        - Misma cuenta
        - Mismo tipo (crédito/débito)
        - Monto similar (dentro de tolerancia)
        - Fecha cercana (dentro de ventana)
        - Descripción similar (opcional)

        Args:
            tx1: Primera transacción
            tx2: Segunda transacción

        Returns:
            True si son similares
        """
        # Verificar condiciones básicas
        if tx1.banco != tx2.banco:
            return False

        if tx1.cuenta_bancaria != tx2.cuenta_bancaria:
            return False

        if tx1.tipo != tx2.tipo:
            return False

        # Verificar monto
        diff_monto = abs(tx1.monto - tx2.monto)
        if diff_monto > self.tolerancia_monto:
            return False

        # Verificar ventana temporal
        diff_dias = abs((tx1.fecha - tx2.fecha).days)
        if diff_dias > self.ventana_dias:
            return False

        # Si pasó todos los filtros, son similares
        # Opcionalmente, podríamos agregar comparación de descripción

        return True

    def deduplicar_contra_db(
        self,
        transacciones: list[TransaccionBancaria],
        hashes_db: set[str],
    ) -> ResultadoDeduplicacion:
        """
        Deduplica contra hashes de base de datos (más eficiente).

        Args:
            transacciones: Transacciones nuevas
            hashes_db: Set de hashes existentes en DB

        Returns:
            Resultado de deduplicación
        """
        resultado = ResultadoDeduplicacion(total_procesadas=len(transacciones))
        hashes_procesados: set[str] = set()

        for tx in transacciones:
            if tx.hash_unico in hashes_db:
                tx.estado = EstadoTransaccion.DUPLICADA
                resultado.transacciones_duplicadas.append(tx)
                resultado.duplicados_por_hash += 1
            elif tx.hash_unico in hashes_procesados:
                tx.estado = EstadoTransaccion.DUPLICADA
                resultado.transacciones_duplicadas.append(tx)
                resultado.duplicados_por_hash += 1
            else:
                resultado.transacciones_unicas.append(tx)
                hashes_procesados.add(tx.hash_unico)

        return resultado


def deduplicar_transacciones(
    transacciones: list[TransaccionBancaria],
    hashes_existentes: set[str] | None = None,
) -> tuple[list[TransaccionBancaria], list[TransaccionBancaria]]:
    """
    Función de conveniencia para deduplicar transacciones.

    Args:
        transacciones: Transacciones a verificar
        hashes_existentes: Hashes ya en DB

    Returns:
        Tupla (únicas, duplicadas)
    """
    deduplicator = Deduplicator()

    if hashes_existentes:
        resultado = deduplicator.deduplicar_contra_db(
            transacciones, hashes_existentes
        )
    else:
        resultado = deduplicator.deduplicar(transacciones)

    return (resultado.transacciones_unicas, resultado.transacciones_duplicadas)
