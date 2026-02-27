"""
ECUCONDOR - Modelos UAFE (RESU/ROII)
Validación de estructuras de datos para cumplimiento normativo.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UafeBaseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class UafeParametros(UafeBaseModel):
    """Parámetros y umbrales vigentes de UAFE."""
    id: Optional[UUID] = None
    umbral_resu_usd: float = Field(default=10000.00, description="Umbral mensual RESU")
    umbral_efectivo_usd: float = Field(default=10000.00, description="Umbral mensual efectivo")
    umbral_monto_inusual: float = Field(default=50000.00, description="Monto para alerta ROII automática")
    umbral_frecuencia_diaria: int = Field(default=5, description="Transacciones por día para alerta ROII")
    puntaje_riesgo_minimo: float = Field(default=70.00, description="Puntaje mínimo para reportar ROII")
    vigencia_desde: date
    vigencia_hasta: Optional[date] = None
    activo: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MonitoreoResu(UafeBaseModel):
    """Estado de monitoreo RESU por cliente/mes."""
    id: Optional[UUID] = None
    anio: int
    mes: int
    periodo: str
    cliente_tipo_id: Optional[str] = None
    cliente_identificacion: str
    cliente_razon_social: str
    total_transacciones: int = 0
    monto_total_creditos: float = 0.0
    monto_total_debitos: float = 0.0
    monto_total_efectivo: float = 0.0
    umbral_resu: float
    supera_umbral: bool = False
    reporte_generado: bool = False
    reporte_id: Optional[UUID] = None
    fecha_reporte: Optional[datetime] = None
    transacciones_ids: Optional[List[str]] = None
    notas: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DeteccionRoii(UafeBaseModel):
    """Alerta de Operación Inusual o Sospechosa."""
    id: Optional[UUID] = None
    transaccion_id: Optional[UUID] = None
    comprobante_id: Optional[UUID] = None
    cliente_tipo_id: Optional[str] = None
    cliente_identificacion: Optional[str] = None
    cliente_razon_social: Optional[str] = None
    tipo_deteccion: str
    categoria: str
    severidad: int = Field(ge=1, le=5)
    descripcion: str
    monto_involucrado: Optional[float] = None
    fecha_deteccion: date
    indicadores: Optional[Dict[str, Any]] = None
    puntaje_riesgo: Optional[float] = Field(None, ge=0.0, le=100.0)
    estado: str = "pendiente"  # pendiente, en_revision, reportado, descartado, falso_positivo
    debe_reportarse: bool = False
    reporte_generado: bool = False
    reporte_id: Optional[UUID] = None
    fecha_reporte: Optional[datetime] = None
    revisado_por: Optional[UUID] = None
    revisado_at: Optional[datetime] = None
    notas_revision: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ReporteUafe(UafeBaseModel):
    """Reporte oficial generado para la UAFE."""
    id: Optional[UUID] = None
    tipo: str  # RESU, ROII
    numero_reporte: Optional[str] = None
    anio: int
    mes: Optional[int] = None
    periodo: Optional[str] = None
    fecha_reporte: date
    xml_reporte: Optional[str] = None
    json_datos: Optional[Dict[str, Any]] = None
    total_clientes: Optional[int] = None
    total_transacciones: Optional[int] = None
    monto_total: Optional[float] = None
    estado: str = "borrador"  # borrador, generado, enviado, aceptado, rechazado
    fecha_generacion: Optional[datetime] = None
    fecha_envio: Optional[datetime] = None
    fecha_respuesta: Optional[datetime] = None
    respuesta_uafe: Optional[str] = None
    codigo_aceptacion: Optional[str] = None
    generado_por: Optional[UUID] = None
    enviado_por: Optional[UUID] = None
    notas: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
