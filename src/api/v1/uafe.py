"""
ECUCONDOR - Rutas API para Cumplimiento UAFE
Endpoints para consultar y operar sobre monitoreo RESU y alertas ROII.
"""

from typing import Any, Dict, List
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.db.supabase import get_supabase_client as get_supabase
from src.uafe.detector import RoiiDetector
from src.uafe.models import DeteccionRoii, MonitoreoResu, ReporteUafe, UafeParametros
from src.uafe.reporter import UafeReporter

logger = structlog.get_logger(__name__)

router = APIRouter()


class GenerarReporteRequest(BaseModel):
    periodo: str  # YYYY-MM


@router.get("/parametros", response_model=Dict[str, Any])
async def get_parametros_uafe(supabase=Depends(get_supabase)):
    """Obtiene los parámetros y umbrales vigentes para cumplimiento UAFE."""
    try:
        resp = supabase.table("uafe_parametros") \
            .select("*") \
            .eq("activo", True) \
            .order("vigencia_desde", desc=True) \
            .limit(1) \
            .execute()
            
        if not resp.data:
            return {
                "umbral_resu_usd": 10000.00,
                "umbral_efectivo_usd": 10000.00,
                "umbral_monto_inusual": 50000.00,
                "umbral_frecuencia_diaria": 5,
                "puntaje_riesgo_minimo": 70.00
            }
            
        return resp.data[0]
    except Exception as e:
        logger.error(f"Error consultando parametros UAFE: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener parámetros UAFE")


@router.get("/resu/pendientes", response_model=List[Dict[str, Any]])
async def get_resu_pendientes(
    periodo: str = Query(..., description="Período a consultar ('YYYY-MM')"),
    supabase=Depends(get_supabase)
):
    """Obtiene clientes que han superado el umbral RESU en un mes y no han sido reportados."""
    try:
        resp = supabase.table("v_uafe_resu_pendientes") \
            .select("*") \
            .eq("periodo", periodo) \
            .execute()
            
        return resp.data
    except Exception as e:
        logger.error(f"Error consultando RESU pendientes: {e}")
        raise HTTPException(status_code=500, detail="Error consultando monitoreo RESU")


@router.get("/roii/alertas", response_model=List[Dict[str, Any]])
async def get_roii_alertas(
    severidad_min: int = Query(3, description="Severidad mínima a mostrar"),
    supabase=Depends(get_supabase)
):
    """Lista las alertas de operaciones inusuales/sospechosas (ROII) pendientes de revisión."""
    try:
        resp = supabase.table("v_uafe_roii_alto_riesgo") \
            .select("*") \
            .gte("severidad", severidad_min) \
            .execute()
            
        return resp.data
    except Exception as e:
        logger.error(f"Error consultando alertas ROII: {e}")
        raise HTTPException(status_code=500, detail="Error consultando detecciones ROII")


@router.post("/reportes/resu", operation_id="generar_reporte_resu")
async def generar_reporte_resu(
    req: GenerarReporteRequest,
    supabase=Depends(get_supabase)
):
    """
    Genera el archivo XML del reporte RESU para un mes específico
    empaquetando a todos los clientes que superaron el umbral.
    """
    reporter = UafeReporter(supabase)
    reporte_id = reporter.generar_resu_mensual(req.periodo)
    
    if not reporte_id:
        raise HTTPException(status_code=404, detail="No hay transacciones pendientes de reporte RESU para este periodo")
        
    return {"status": "success", "reporte_id": str(reporte_id), "mensaje": "Reporte generado exitosamente"}


@router.get("/reportes/{reporte_id}")
async def descargar_reporte_xml(
    reporte_id: UUID,
    supabase=Depends(get_supabase)
):
    """Descarga el XML de un reporte previamente generado."""
    try:
        resp = supabase.table("uafe_reportes").select("xml_reporte, tipo, periodo").eq("id", str(reporte_id)).execute()
        
        if not resp.data:
            raise HTTPException(status_code=404, detail="Reporte no encontrado")
            
        reporte = resp.data[0]
        
        # En una versión real, esto devolvería un Response XML para descargar
        return {
            "filename": f"UAFE_{reporte['tipo']}_{reporte['periodo']}.xml",
            "content": reporte["xml_reporte"]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error descargando reporte XML: {e}")
        raise HTTPException(status_code=500, detail="Error al consultar el reporte")
