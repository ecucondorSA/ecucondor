"""
ECUCONDOR - Detector de Operaciones Inusuales (ROII)
Heurísticas para detección de transacciones sospechosas.
"""

from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog

logger = structlog.get_logger(__name__)


class RoiiDetector:
    """Motor de heurísticas para detección ROII."""

    def __init__(self, supabase_client):
        """Inicializa el detector con cliente Supabase."""
        self.supabase = supabase_client
        self._parametros = None

    def _cargar_parametros(self) -> Dict[str, Any]:
        """Carga parámetros UAFE vigentes o usa defaults."""
        if self._parametros:
            return self._parametros
            
        try:
            result = self.supabase.table("uafe_parametros").select("*").eq("activo", True).order("vigencia_desde", desc=True).limit(1).execute()
            if result.data:
                self._parametros = result.data[0]
                return self._parametros
        except Exception as e:
            logger.error(f"Error cargando parámetros UAFE: {e}")
            
        # Defaults
        return {
            "umbral_monto_inusual": 50000.00,
            "umbral_frecuencia_diaria": 5,
            "puntaje_riesgo_minimo": 70.00
        }

    def evaluar_transaccion_roii(self, transaccion: Dict[str, Any]) -> Optional[UUID]:
        """
        Evalúa una transacción específica contra heurísticas de inusualidad.
        
        Args:
            transaccion: Datos de la transacción (dict).
            
        Returns:
            UUID de la detección si aplica, None en caso contrario.
        """
        if not transaccion:
            return None
            
        parametros = self._cargar_parametros()
        detecciones = []
        
        # 1. Heurística: Monto inusualmente alto
        monto = float(transaccion.get("monto", 0))
        umbral_monto = float(parametros.get("umbral_monto_inusual", 50000.00))
        
        if monto >= umbral_monto:
            detecciones.append({
                "tipo_deteccion": "monto_inusual_alto",
                "categoria": "inusual",
                "severidad": 4 if monto >= (umbral_monto * 2) else 3,
                "descripcion": f"Transacción excede umbral de alerta automática (${monto:,.2f} >= ${umbral_monto:,.2f})",
                "puntaje_riesgo": 85.0 if monto >= (umbral_monto * 2) else 75.0,
                "indicadores": {"monto": monto, "umbral": umbral_monto, "exceso": monto - umbral_monto}
            })
            
        # 2. Heurística: Fraccionamiento (varias transacciones pequeñas el mismo día)
        # Requiere consultar count() de transacciones del mismo cliente en la misma fecha
        cliente_id = transaccion.get("contraparte_identificacion")
        fechaStr = transaccion.get("fecha")
        
        if cliente_id and fechaStr:
            fecha_corta = fechaStr[:10] if isinstance(fechaStr, str) else fechaStr.strftime("%Y-%m-%d")
            try:
                # Contar transacciones del día
                resp_count = self.supabase.table("transacciones_bancarias") \
                    .select("id", count="exact") \
                    .eq("contraparte_identificacion", cliente_id) \
                    .gte("fecha", f"{fecha_corta}T00:00:00Z") \
                    .lte("fecha", f"{fecha_corta}T23:59:59Z") \
                    .neq("estado", "duplicada") \
                    .execute()
                    
                total_dia = resp_count.count if hasattr(resp_count, 'count') else len(resp_count.data)
                umbral_frecuencia = int(parametros.get("umbral_frecuencia_diaria", 5))
                
                # Reportar solo si esta transacción es la que cruzó el umbral
                if total_dia >= umbral_frecuencia:
                    detecciones.append({
                        "tipo_deteccion": "frecuencia_diaria_inusual",
                        "categoria": "sospechoso",
                        "severidad": 4 if total_dia > (umbral_frecuencia * 2) else 3,
                        "descripcion": f"Frecuencia inusual: {total_dia} transacciones en el mismo día (límite {umbral_frecuencia})",
                        "puntaje_riesgo": 80.0,
                        "indicadores": {"total_dia": total_dia, "umbral": umbral_frecuencia, "fecha": fecha_corta}
                    })
                    
            except Exception as e:
                logger.error(f"Error evaluando fraccionamiento: {e}")
                
        # Procesar si hubo detecciones (tomar la más severa para guardar)
        if not detecciones:
            return None
            
        # Ordenar por severidad (desc) y tomar la más alta
        deteccion_principal = sorted(detecciones, key=lambda x: x["severidad"], reverse=True)[0]
        
        return self._guardar_deteccion(transaccion, deteccion_principal)
        
    def _guardar_deteccion(self, transaccion: Dict[str, Any], deteccion: Dict[str, Any]) -> Optional[UUID]:
        """Guarda la detección en la tabla `uafe_detecciones_roii`."""
        try:
            monto = transaccion.get("monto")
            fechaStr = transaccion.get("fecha", date.today().isoformat())
            fecha = fechaStr[:10] if isinstance(fechaStr, str) else fechaStr.strftime("%Y-%m-%d")
            
            payload = {
                "transaccion_id": transaccion.get("id"),
                "cliente_identificacion": transaccion.get("contraparte_identificacion"),
                "cliente_razon_social": transaccion.get("contraparte_nombre"),
                "tipo_deteccion": deteccion["tipo_deteccion"],
                "categoria": deteccion["categoria"],
                "severidad": deteccion["severidad"],
                "descripcion": deteccion["descripcion"],
                "monto_involucrado": monto,
                "fecha_deteccion": fecha,
                "indicadores": deteccion.get("indicadores", {}),
                "puntaje_riesgo": deteccion.get("puntaje_riesgo", 0.0),
                "estado": "pendiente"
            }
            
            result = self.supabase.table("uafe_detecciones_roii").insert(payload).execute()
            
            if result.data:
                logger.warning(
                    "Nueva detección ROII registrada", 
                    detect_id=result.data[0]["id"],
                    tipo=deteccion["tipo_deteccion"],
                    cliente=payload["cliente_identificacion"]
                )
                return UUID(result.data[0]["id"])
                
            return None
            
        except Exception as e:
            logger.exception("Error guardando detección ROII", error=str(e), transaccion_id=transaccion.get("id"))
            return None
