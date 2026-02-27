"""
ECUCONDOR - Ingestor Financiero
Módulo para importación y procesamiento de extractos bancarios.
"""

from src.ingestor.models import (
    BancoEcuador,
    EstadoTransaccion,
    FiltrosTransaccion,
    OrigenTransaccion,
    ResultadoImportacion,
    TipoTransaccion,
    TransaccionBancaria,
)
from src.ingestor.normalizer import TransactionNormalizer, normalizar_transacciones
from src.ingestor.deduplicator import Deduplicator, deduplicar_transacciones
from src.ingestor.reconciler import Reconciler, ReconciliationRules

__all__ = [
    # Modelos
    "BancoEcuador",
    "EstadoTransaccion",
    "FiltrosTransaccion",
    "OrigenTransaccion",
    "ResultadoImportacion",
    "TipoTransaccion",
    "TransaccionBancaria",
    # Clases
    "TransactionNormalizer",
    "Deduplicator",
    "Reconciler",
    "ReconciliationRules",
    # Funciones
    "normalizar_transacciones",
    "deduplicar_transacciones",
]
