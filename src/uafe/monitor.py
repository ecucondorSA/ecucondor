"""
ECUCONDOR - Monitor UAFE (RESU/ROII)
Motor de monitoreo continuo de transacciones para acumulación de umbrales.
"""

from datetime import date
from typing import Optional
from uuid import UUID

import structlog

logger = structlog.get_logger(__name__)


class UafeMonitor:
    """Motor de monitoreo para cumplimiento UAFE."""

    def __init__(self, supabase_client):
        """Inicializa el monitor con cliente Supabase."""
        self.supabase = supabase_client

    def evaluar_transaccion(self, transaccion_id: UUID) -> bool:
        """
        Evalúa una transacción recién registrada para actualizar acumulados RESU
        y disparar alertas ROII si es necesario.
        
        Args:
            transaccion_id: UUID de la transacción bancaria.
            
        Returns:
            bool: True si la evaluación fue exitosa.
        """
        try:
            # Obtener transacción
            result = self.supabase.table("transacciones_bancarias").select("*").eq("id", str(transaccion_id)).limit(1).execute()
            
            if not result.data:
                logger.error("Transacción no encontrada para evaluación UAFE", transaccion_id=str(transaccion_id))
                return False
                
            transaccion = result.data[0]
            cliente_id = transaccion.get("contraparte_identificacion")
            fecha = transaccion.get("fecha")
            
            if not cliente_id or not fecha:
                logger.debug("Transacción ignorada por falta de datos", transaccion_id=str(transaccion_id))
                return True
                
            # Calcular periodo (YYYY-MM)
            periodo = fecha[:7] if isinstance(fecha, str) else fecha.strftime("%Y-%m")
            
            # Actualizar monitoreo RESU (llama a función SQL)
            logger.info("Actualizando monitoreo RESU", cliente=cliente_id, periodo=periodo)
            self.verificar_umbral_resu(cliente_id, periodo)
            
            # Aquí se puede llamar al detector ROII si la transacción individual es inusual
            # self.detector.evaluar_transaccion_roii(transaccion)
            
            return True
            
        except Exception as e:
            logger.exception("Error evaluando transacción para UAFE", error=str(e), transaccion_id=str(transaccion_id))
            return False

    def verificar_umbral_resu(self, cliente_identificacion: str, periodo: str) -> Optional[UUID]:
        """
        Invoca la función SQL para recalcular y actualizar los montos RESU
        del cliente en el mes específico.
        
        Args:
            cliente_identificacion: RUC/CI del cliente.
            periodo: Periodo formato "YYYY-MM".
            
        Returns:
            UUID: ID del registro de monitoreo actualizado.
        """
        try:
            # Invocar función RPC 'actualizar_monitoreo_resu' que definimos en la migración
            result = self.supabase.rpc(
                "actualizar_monitoreo_resu",
                {
                    "p_periodo": periodo,
                    "p_cliente_identificacion": cliente_identificacion
                }
            ).execute()
            
            if result.data:
                monitoreo_id = result.data
                logger.info("Monitoreo RESU actualizado", monitoreo_id=monitoreo_id)
                return UUID(monitoreo_id)
                
            return None
            
        except Exception as e:
            logger.exception(
                "Error al invocar actualizar_monitoreo_resu", 
                error=str(e), 
                cliente=cliente_identificacion, 
                periodo=periodo
            )
            return None
