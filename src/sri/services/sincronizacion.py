"""
Servicio de Sincronización de Comprobantes Recibidos del SRI.
Permite descargar e importar automáticamente facturas recibidas.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree as ET
import base64
import json

import httpx
import structlog

logger = structlog.get_logger(__name__)


class EstadoSincronizacion(str, Enum):
    """Estados de sincronización."""
    PENDIENTE = "pendiente"
    EN_PROCESO = "en_proceso"
    COMPLETADO = "completado"
    ERROR = "error"
    PARCIAL = "parcial"


class EstadoFactura(str, Enum):
    """Estados de facturas importadas."""
    NUEVA = "nueva"  # Recién descargada
    PENDIENTE_REVISION = "pendiente_revision"  # Requiere revisión manual
    APROBADA = "aprobada"  # Aprobada para contabilizar
    RECHAZADA = "rechazada"  # Rechazada
    CONTABILIZADA = "contabilizada"  # Ya registrada en contabilidad
    DUPLICADA = "duplicada"  # Ya existía en el sistema


@dataclass
class FacturaRecibida:
    """Datos de una factura recibida del SRI."""
    clave_acceso: str
    tipo_comprobante: str
    numero_comprobante: str
    fecha_emision: date
    ruc_emisor: str
    razon_social_emisor: str
    subtotal: float
    iva: float
    total: float
    estado: EstadoFactura = EstadoFactura.NUEVA
    xml_contenido: Optional[str] = None
    fecha_descarga: datetime = field(default_factory=datetime.now)
    detalles: list[dict] = field(default_factory=list)


@dataclass
class ResultadoSincronizacion:
    """Resultado de una sincronización."""
    fecha_inicio: datetime
    fecha_fin: Optional[datetime]
    estado: EstadoSincronizacion
    periodo_desde: date
    periodo_hasta: date
    total_encontrados: int = 0
    total_descargados: int = 0
    total_nuevos: int = 0
    total_duplicados: int = 0
    total_errores: int = 0
    errores: list[str] = field(default_factory=list)
    facturas: list[FacturaRecibida] = field(default_factory=list)


class ServicioSincronizacionSRI:
    """
    Servicio para sincronizar comprobantes recibidos desde el portal del SRI.

    NOTA: La descarga automática del portal SRI requiere autenticación.
    Este servicio está preparado para integrarse cuando se proporcionen
    las credenciales necesarias.
    """

    # URLs del portal SRI
    SRI_LOGIN_URL = "https://srienlinea.sri.gob.ec/sri-en-linea/inicio/NAT"
    SRI_COMPROBANTES_URL = "https://srienlinea.sri.gob.ec/sri-en-linea/consulta/comprobantes-recibidos"

    def __init__(self, supabase_client=None, ruc: str = None):
        self.supabase = supabase_client
        self.ruc = ruc
        self._session_token = None
        self._credenciales_configuradas = False

    def configurar_credenciales(self, usuario: str, clave: str) -> bool:
        """
        Configura las credenciales para acceder al portal SRI.

        NOTA: Las credenciales deben almacenarse de forma segura.
        Este método es un placeholder para la implementación real.

        Args:
            usuario: Usuario del portal SRI (RUC o cédula)
            clave: Contraseña del portal SRI

        Returns:
            True si las credenciales son válidas
        """
        # En una implementación real, aquí se validarían las credenciales
        # y se almacenarían de forma segura (ej: en variables de entorno o vault)
        logger.info("Credenciales configuradas para sincronización SRI", usuario=usuario[:5] + "***")
        self._credenciales_configuradas = True
        return True

    async def sincronizar(
        self,
        fecha_desde: Optional[date] = None,
        fecha_hasta: Optional[date] = None,
        solo_facturas: bool = True
    ) -> ResultadoSincronizacion:
        """
        Sincroniza comprobantes recibidos del SRI.

        Args:
            fecha_desde: Fecha inicial del periodo (default: hace 30 días)
            fecha_hasta: Fecha final del periodo (default: hoy)
            solo_facturas: Si solo sincroniza facturas (tipo 01)

        Returns:
            ResultadoSincronizacion con los resultados
        """
        fecha_hasta = fecha_hasta or date.today()
        fecha_desde = fecha_desde or (fecha_hasta - timedelta(days=30))

        resultado = ResultadoSincronizacion(
            fecha_inicio=datetime.now(),
            fecha_fin=None,
            estado=EstadoSincronizacion.EN_PROCESO,
            periodo_desde=fecha_desde,
            periodo_hasta=fecha_hasta
        )

        if not self._credenciales_configuradas:
            resultado.estado = EstadoSincronizacion.ERROR
            resultado.errores.append(
                "Credenciales del SRI no configuradas. Use configurar_credenciales() primero."
            )
            resultado.fecha_fin = datetime.now()
            return resultado

        try:
            # Paso 1: Autenticarse en el portal
            if not await self._autenticar():
                resultado.estado = EstadoSincronizacion.ERROR
                resultado.errores.append("Error de autenticación con el portal SRI")
                resultado.fecha_fin = datetime.now()
                return resultado

            # Paso 2: Consultar comprobantes del periodo
            comprobantes = await self._consultar_comprobantes(
                fecha_desde, fecha_hasta, solo_facturas
            )
            resultado.total_encontrados = len(comprobantes)

            # Paso 3: Descargar y procesar cada comprobante
            for comp in comprobantes:
                try:
                    factura = await self._descargar_comprobante(comp)
                    if factura:
                        # Verificar si ya existe
                        existe = await self._verificar_existencia(factura.clave_acceso)
                        if existe:
                            factura.estado = EstadoFactura.DUPLICADA
                            resultado.total_duplicados += 1
                        else:
                            factura.estado = EstadoFactura.NUEVA
                            resultado.total_nuevos += 1
                            # Guardar en base de datos
                            await self._guardar_factura(factura)

                        resultado.facturas.append(factura)
                        resultado.total_descargados += 1
                except Exception as e:
                    logger.error("Error descargando comprobante", error=str(e))
                    resultado.total_errores += 1
                    resultado.errores.append(str(e))

            resultado.estado = EstadoSincronizacion.COMPLETADO
            if resultado.total_errores > 0:
                resultado.estado = EstadoSincronizacion.PARCIAL

        except Exception as e:
            logger.error("Error en sincronización", error=str(e))
            resultado.estado = EstadoSincronizacion.ERROR
            resultado.errores.append(str(e))

        resultado.fecha_fin = datetime.now()

        # Guardar registro de sincronización
        await self._guardar_registro_sincronizacion(resultado)

        return resultado

    async def _autenticar(self) -> bool:
        """Autentica en el portal SRI."""
        # Placeholder - implementar cuando se tengan credenciales
        logger.info("Intentando autenticación con portal SRI")
        return False  # Por ahora siempre falla hasta que se implemente

    async def _consultar_comprobantes(
        self,
        fecha_desde: date,
        fecha_hasta: date,
        solo_facturas: bool
    ) -> list[dict]:
        """Consulta la lista de comprobantes en el periodo."""
        # Placeholder - implementar cuando se tenga acceso al portal
        return []

    async def _descargar_comprobante(self, comprobante: dict) -> Optional[FacturaRecibida]:
        """Descarga el XML de un comprobante específico."""
        # Placeholder - implementar cuando se tenga acceso al portal
        return None

    async def _verificar_existencia(self, clave_acceso: str) -> bool:
        """Verifica si una factura ya existe en el sistema."""
        if not self.supabase:
            return False

        try:
            result = self.supabase.table('facturas_recibidas').select(
                'id'
            ).eq('clave_acceso', clave_acceso).limit(1).execute()
            return len(result.data) > 0
        except Exception:
            return False

    async def _guardar_factura(self, factura: FacturaRecibida) -> bool:
        """Guarda una factura recibida en la base de datos."""
        if not self.supabase:
            return False

        try:
            self.supabase.table('facturas_recibidas').insert({
                'clave_acceso': factura.clave_acceso,
                'tipo_comprobante': factura.tipo_comprobante,
                'numero_comprobante': factura.numero_comprobante,
                'fecha_emision': str(factura.fecha_emision),
                'ruc_emisor': factura.ruc_emisor,
                'razon_social_emisor': factura.razon_social_emisor,
                'subtotal': factura.subtotal,
                'iva': factura.iva,
                'total': factura.total,
                'estado': factura.estado.value,
                'xml_contenido': factura.xml_contenido,
                'fecha_descarga': factura.fecha_descarga.isoformat(),
                'detalles': json.dumps(factura.detalles),
                'created_at': datetime.now().isoformat()
            }).execute()
            return True
        except Exception as e:
            logger.error("Error guardando factura", error=str(e))
            return False

    async def _guardar_registro_sincronizacion(self, resultado: ResultadoSincronizacion) -> None:
        """Guarda el registro de la sincronización."""
        if not self.supabase:
            return

        try:
            self.supabase.table('sincronizaciones_sri').insert({
                'fecha_inicio': resultado.fecha_inicio.isoformat(),
                'fecha_fin': resultado.fecha_fin.isoformat() if resultado.fecha_fin else None,
                'estado': resultado.estado.value,
                'periodo_desde': str(resultado.periodo_desde),
                'periodo_hasta': str(resultado.periodo_hasta),
                'total_encontrados': resultado.total_encontrados,
                'total_descargados': resultado.total_descargados,
                'total_nuevos': resultado.total_nuevos,
                'total_duplicados': resultado.total_duplicados,
                'total_errores': resultado.total_errores,
                'errores': json.dumps(resultado.errores),
                'created_at': datetime.now().isoformat()
            }).execute()
        except Exception as e:
            logger.warning("Error guardando registro de sincronización", error=str(e))

    # =========================================================
    # IMPORTACIÓN MANUAL DE XML
    # =========================================================

    def parsear_xml_factura(self, xml_content: str) -> Optional[FacturaRecibida]:
        """
        Parsea el contenido XML de una factura electrónica.

        Args:
            xml_content: Contenido del archivo XML

        Returns:
            FacturaRecibida con los datos extraídos
        """
        try:
            # Limpiar posible CDATA o encoding
            if 'CDATA' in xml_content:
                # Extraer contenido del CDATA si existe
                import re
                cdata_match = re.search(r'<!\[CDATA\[(.*?)\]\]>', xml_content, re.DOTALL)
                if cdata_match:
                    xml_content = cdata_match.group(1)

            root = ET.fromstring(xml_content)

            # Buscar infoTributaria
            info_trib = root.find('.//infoTributaria')
            if info_trib is None:
                # Intentar con namespace
                for elem in root.iter():
                    if 'infoTributaria' in elem.tag:
                        info_trib = elem
                        break

            if info_trib is None:
                logger.warning("No se encontró infoTributaria en el XML")
                return None

            # Extraer datos básicos
            clave_acceso = self._get_xml_text(info_trib, 'claveAcceso', '')
            ruc_emisor = self._get_xml_text(info_trib, 'ruc', '')
            razon_social = self._get_xml_text(info_trib, 'razonSocial', '')
            tipo_comp = self._get_xml_text(info_trib, 'codDoc', '01')

            estab = self._get_xml_text(info_trib, 'estab', '000')
            pto_emi = self._get_xml_text(info_trib, 'ptoEmi', '000')
            secuencial = self._get_xml_text(info_trib, 'secuencial', '000000000')
            numero = f"{estab}-{pto_emi}-{secuencial}"

            # Buscar infoFactura
            info_fact = root.find('.//infoFactura')
            fecha_emision = date.today()
            subtotal = 0.0
            iva = 0.0
            total = 0.0

            if info_fact is not None:
                fecha_str = self._get_xml_text(info_fact, 'fechaEmision', '')
                if fecha_str:
                    try:
                        fecha_emision = datetime.strptime(fecha_str, '%d/%m/%Y').date()
                    except ValueError:
                        pass

                total = float(self._get_xml_text(info_fact, 'importeTotal', '0'))

                # Buscar totalConImpuestos
                for imp in info_fact.iter():
                    if 'totalImpuesto' in imp.tag:
                        codigo = self._get_xml_text(imp, 'codigo', '')
                        if codigo == '2':  # IVA
                            iva = float(self._get_xml_text(imp, 'valor', '0'))
                            subtotal = float(self._get_xml_text(imp, 'baseImponible', '0'))

            if subtotal == 0:
                subtotal = total - iva

            # Extraer detalles
            detalles = []
            for detalle in root.iter():
                if 'detalle' in detalle.tag.lower() and detalle.tag != 'detalles':
                    det = {
                        'descripcion': self._get_xml_text(detalle, 'descripcion', ''),
                        'cantidad': float(self._get_xml_text(detalle, 'cantidad', '1')),
                        'precio_unitario': float(self._get_xml_text(detalle, 'precioUnitario', '0')),
                        'precio_total': float(self._get_xml_text(detalle, 'precioTotalSinImpuesto', '0'))
                    }
                    if det['descripcion']:
                        detalles.append(det)

            return FacturaRecibida(
                clave_acceso=clave_acceso,
                tipo_comprobante=tipo_comp,
                numero_comprobante=numero,
                fecha_emision=fecha_emision,
                ruc_emisor=ruc_emisor,
                razon_social_emisor=razon_social,
                subtotal=subtotal,
                iva=iva,
                total=total,
                xml_contenido=xml_content,
                detalles=detalles
            )

        except ET.ParseError as e:
            logger.error("Error parseando XML", error=str(e))
            return None
        except Exception as e:
            logger.error("Error procesando factura XML", error=str(e))
            return None

    def _get_xml_text(self, parent, tag: str, default: str = '') -> str:
        """Obtiene el texto de un elemento XML."""
        elem = parent.find(f'.//{tag}')
        if elem is None:
            # Intentar sin namespace
            for child in parent.iter():
                if tag in child.tag:
                    return child.text or default
        return elem.text if elem is not None and elem.text else default

    async def importar_xml(self, xml_content: str) -> Optional[FacturaRecibida]:
        """
        Importa una factura desde su contenido XML.

        Args:
            xml_content: Contenido del archivo XML

        Returns:
            FacturaRecibida si se importó correctamente
        """
        factura = self.parsear_xml_factura(xml_content)
        if not factura:
            return None

        # Verificar si ya existe
        existe = await self._verificar_existencia(factura.clave_acceso)
        if existe:
            factura.estado = EstadoFactura.DUPLICADA
            logger.info("Factura duplicada", clave=factura.clave_acceso)
        else:
            factura.estado = EstadoFactura.PENDIENTE_REVISION
            await self._guardar_factura(factura)
            logger.info("Factura importada", clave=factura.clave_acceso)

        return factura

    async def importar_archivo(self, ruta_archivo: Path) -> Optional[FacturaRecibida]:
        """
        Importa una factura desde un archivo XML.

        Args:
            ruta_archivo: Ruta al archivo XML

        Returns:
            FacturaRecibida si se importó correctamente
        """
        if not ruta_archivo.exists():
            logger.error("Archivo no encontrado", ruta=str(ruta_archivo))
            return None

        xml_content = ruta_archivo.read_text(encoding='utf-8')
        return await self.importar_xml(xml_content)

    # =========================================================
    # GESTIÓN DE FACTURAS PENDIENTES
    # =========================================================

    async def obtener_facturas_pendientes(
        self,
        limit: int = 50,
        offset: int = 0
    ) -> list[dict]:
        """
        Obtiene las facturas pendientes de revisión.

        Returns:
            Lista de facturas pendientes
        """
        if not self.supabase:
            return []

        try:
            result = self.supabase.table('facturas_recibidas').select(
                '*'
            ).in_(
                'estado', ['nueva', 'pendiente_revision']
            ).order(
                'fecha_emision', desc=True
            ).range(offset, offset + limit - 1).execute()

            return result.data
        except Exception as e:
            logger.error("Error obteniendo facturas pendientes", error=str(e))
            return []

    async def aprobar_factura(
        self,
        clave_acceso: str,
        codigo_retencion_ir: Optional[str] = None,
        codigo_retencion_iva: Optional[str] = None
    ) -> bool:
        """
        Aprueba una factura para contabilización.

        Args:
            clave_acceso: Clave de acceso de la factura
            codigo_retencion_ir: Código de retención IR a aplicar
            codigo_retencion_iva: Código de retención IVA a aplicar

        Returns:
            True si se aprobó correctamente
        """
        if not self.supabase:
            return False

        try:
            self.supabase.table('facturas_recibidas').update({
                'estado': EstadoFactura.APROBADA.value,
                'codigo_retencion_ir': codigo_retencion_ir,
                'codigo_retencion_iva': codigo_retencion_iva,
                'fecha_aprobacion': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }).eq('clave_acceso', clave_acceso).execute()
            return True
        except Exception as e:
            logger.error("Error aprobando factura", error=str(e))
            return False

    async def rechazar_factura(
        self,
        clave_acceso: str,
        motivo: str
    ) -> bool:
        """
        Rechaza una factura.

        Args:
            clave_acceso: Clave de acceso de la factura
            motivo: Motivo del rechazo

        Returns:
            True si se rechazó correctamente
        """
        if not self.supabase:
            return False

        try:
            self.supabase.table('facturas_recibidas').update({
                'estado': EstadoFactura.RECHAZADA.value,
                'motivo_rechazo': motivo,
                'updated_at': datetime.now().isoformat()
            }).eq('clave_acceso', clave_acceso).execute()
            return True
        except Exception as e:
            logger.error("Error rechazando factura", error=str(e))
            return False

    async def obtener_resumen_sincronizacion(self) -> dict:
        """
        Obtiene un resumen del estado de sincronización.

        Returns:
            Diccionario con estadísticas
        """
        if not self.supabase:
            return {
                'total_facturas': 0,
                'pendientes_revision': 0,
                'aprobadas': 0,
                'contabilizadas': 0,
                'ultima_sincronizacion': None
            }

        try:
            # Contar por estado
            result = self.supabase.table('facturas_recibidas').select(
                'estado', count='exact'
            ).execute()

            estados = {}
            for row in result.data:
                estado = row.get('estado', 'desconocido')
                estados[estado] = estados.get(estado, 0) + 1

            # Última sincronización
            sync_result = self.supabase.table('sincronizaciones_sri').select(
                'fecha_fin, estado, total_descargados'
            ).order('fecha_inicio', desc=True).limit(1).execute()

            ultima_sync = None
            if sync_result.data:
                ultima_sync = sync_result.data[0]

            return {
                'total_facturas': sum(estados.values()),
                'nuevas': estados.get('nueva', 0),
                'pendientes_revision': estados.get('pendiente_revision', 0),
                'aprobadas': estados.get('aprobada', 0),
                'contabilizadas': estados.get('contabilizada', 0),
                'rechazadas': estados.get('rechazada', 0),
                'duplicadas': estados.get('duplicada', 0),
                'ultima_sincronizacion': ultima_sync
            }
        except Exception as e:
            logger.error("Error obteniendo resumen", error=str(e))
            return {}
