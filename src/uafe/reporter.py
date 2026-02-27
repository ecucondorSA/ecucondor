"""
ECUCONDOR - Generador de Reportes UAFE (RESU/ROII)
Genera los archivos XML con el esquema oficial de la UAFE.
"""

import json
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog

logger = structlog.get_logger(__name__)


class UafeReporter:
    """Clase encargada de generar reportes XML para la UAFE."""

    def __init__(self, supabase_client):
        """Inicializa el reporter con cliente Supabase."""
        self.supabase = supabase_client

    def generar_resu_mensual(self, periodo: str) -> Optional[UUID]:
        """
        Genera el reporte RESU (Reporte de Operaciones y Transacciones Individuales Múltiples)
        para el mes indicado (formato YYYY-MM).
        
        Args:
            periodo: Periodo a reportar (e.g. "2025-01").
            
        Returns:
            UUID del reporte generado o None en caso de error.
        """
        try:
            # Obtener registros pendientes de reporte que superen el umbral
            resp = self.supabase.table("v_uafe_resu_pendientes").select("*").eq("periodo", periodo).execute()
            
            if not resp.data:
                logger.info(f"No hay registros RESU pendientes para el periodo {periodo}")
                return None
                
            registros = resp.data
            
            # Crear XML Base (Estructura referencial genérica para Factoring)
            # En la vida real, se debe usar el XSD provisto por la UAFE
            root = ET.Element("ReporteRESU")
            cabecera = ET.SubElement(root, "Cabecera")
            
            # Obtener datos empresa
            empresa_resp = self.supabase.table("company_info").select("*").limit(1).execute()
            empresa = empresa_resp.data[0] if empresa_resp.data else {}
            
            ET.SubElement(cabecera, "RucSujetoObligado").text = empresa.get("ruc", "1391937000001")
            ET.SubElement(cabecera, "MesReporte").text = str(registros[0]["mes"])
            ET.SubElement(cabecera, "AnioReporte").text = str(registros[0]["anio"])
            
            detalle = ET.SubElement(root, "DetalleOperaciones")
            
            monto_total = 0.0
            
            for reg in registros:
                operacion = ET.SubElement(detalle, "Operacion")
                
                cliente = ET.SubElement(operacion, "Cliente")
                ET.SubElement(cliente, "TipoIdentificacion").text = "RUC" if len(reg["cliente_identificacion"]) == 13 else "C"
                ET.SubElement(cliente, "Identificacion").text = reg["cliente_identificacion"]
                ET.SubElement(cliente, "RazonSocial").text = reg["cliente_razon_social"]
                
                ET.SubElement(operacion, "MontoTotal").text = f"{reg['monto']:.2f}"
                ET.SubElement(operacion, "CantidadTransacciones").text = str(reg["total_transacciones"])
                
                monto_total += float(reg['monto'])
                
            # Generar string de XML
            xml_str = ET.tostring(root, encoding="utf8", method="xml").decode("utf8")
            
            # Guardar reporte en base de datos
            payload = {
                "tipo": "RESU",
                "anio": int(registros[0]["anio"]),
                "mes": int(registros[0]["mes"]),
                "periodo": periodo,
                "fecha_reporte": date.today().isoformat(),
                "xml_reporte": xml_str,
                "json_datos": json.loads(json.dumps(registros, default=str)),
                "total_clientes": len(registros),
                "monto_total": monto_total,
                "total_transacciones": sum([int(r["total_transacciones"]) for r in registros]),
                "estado": "generado",
                "fecha_generacion": datetime.now().isoformat()
            }
            
            rep_db = self.supabase.table("uafe_reportes").insert(payload).execute()
            reporte_id = rep_db.data[0]["id"]
            
            # Actualizar registros como reportados
            ids_registrados = [r["id"] for r in registros]
            self.supabase.table("uafe_monitoreo_resu") \
                .update({"reporte_generado": True, "reporte_id": reporte_id, "fecha_reporte": payload["fecha_reporte"]}) \
                .in_("id", ids_registrados) \
                .execute()
                
            logger.info("Reporte RESU generado exitosamente", reporte_id=reporte_id, periodo=periodo, clientes=len(registros))
            
            return UUID(reporte_id)
            
        except Exception as e:
            logger.exception("Error generando reporte RESU mensual", error=str(e), periodo=periodo)
            return None

    def marcar_reportado(self, reporte_id: str, codigo_aceptacion: str) -> bool:
        """
        Actualiza el estado de un reporte luego de ser subido exitosamente al portal UAFE.
        
        Args:
            reporte_id: UUID del reporte.
            codigo_aceptacion: Código de respuesta/ticket de la UAFE.
            
        Returns:
            bool: True si la actualización fue exitosa.
        """
        try:
            self.supabase.table("uafe_reportes").update({
                "estado": "aceptado",
                "fecha_envio": datetime.now().isoformat(),
                "codigo_aceptacion": codigo_aceptacion
            }).eq("id", reporte_id).execute()
            
            logger.info("Reporte marcado como enviado a UAFE", reporte_id=reporte_id, codigo=codigo_aceptacion)
            return True
        except Exception as e:
            logger.error(f"Error actualizando estado reporte UAFE: {e}")
            return False
