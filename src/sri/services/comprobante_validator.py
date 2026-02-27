"""
Servicio de Validación de Comprobantes Electrónicos SRI.
Usa los Web Services SOAP del SRI para validar facturas y otros comprobantes.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from xml.etree import ElementTree as ET

import httpx
import structlog

logger = structlog.get_logger(__name__)


class EstadoAutorizacion(str, Enum):
    """Estados de autorización de comprobantes."""
    AUTORIZADO = "AUTORIZADO"
    NO_AUTORIZADO = "NO AUTORIZADO"
    EN_PROCESO = "EN PROCESO"
    DEVUELTO = "DEVUELTO"
    ERROR = "ERROR"
    DESCONOCIDO = "DESCONOCIDO"


class TipoComprobante(str, Enum):
    """Tipos de comprobantes electrónicos."""
    FACTURA = "01"
    LIQUIDACION_COMPRA = "03"
    NOTA_CREDITO = "04"
    NOTA_DEBITO = "05"
    GUIA_REMISION = "06"
    COMPROBANTE_RETENCION = "07"


@dataclass
class ResultadoValidacion:
    """Resultado de la validación de un comprobante."""
    clave_acceso: str
    estado: EstadoAutorizacion
    numero_autorizacion: Optional[str]
    fecha_autorizacion: Optional[datetime]
    ambiente: str  # PRODUCCION, PRUEBAS
    tipo_comprobante: str
    ruc_emisor: str
    fecha_emision: str
    comprobante_xml: Optional[str]
    mensajes: list[dict[str, str]]
    validado_en: datetime


class ServicioComprobantesSRI:
    """Servicio para validación de comprobantes electrónicos con el SRI."""

    # URLs de los Web Services del SRI
    WSDL_CONSULTA_PROD = "https://cel.sri.gob.ec/comprobantes-electronicos-ws/ConsultaComprobante?wsdl"
    WSDL_CONSULTA_PRUEBAS = "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/ConsultaComprobante?wsdl"

    WSDL_AUTORIZACION_PROD = "https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantes?wsdl"
    WSDL_AUTORIZACION_PRUEBAS = "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantes?wsdl"

    # Endpoints directos (sin WSDL)
    ENDPOINT_AUTORIZACION_PROD = "https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantes"
    ENDPOINT_AUTORIZACION_PRUEBAS = "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantes"

    # Namespaces SOAP
    NS = {
        "soapenv": "http://schemas.xmlsoap.org/soap/envelope/",
        "ec": "http://ec.gob.sri.ws.autorizacion"
    }

    def __init__(self, supabase_client=None, ambiente: str = "PRODUCCION"):
        self.supabase = supabase_client
        self.ambiente = ambiente.upper()
        self.endpoint = (
            self.ENDPOINT_AUTORIZACION_PROD
            if self.ambiente == "PRODUCCION"
            else self.ENDPOINT_AUTORIZACION_PRUEBAS
        )

    def validar_clave_acceso(self, clave: str) -> tuple[bool, str]:
        """
        Valida el formato de una clave de acceso.

        Args:
            clave: Clave de acceso del comprobante (49 dígitos)

        Returns:
            Tuple (es_valida, mensaje)
        """
        if not clave or not isinstance(clave, str):
            return False, "La clave de acceso debe ser una cadena de texto"

        clave = clave.strip()

        if len(clave) != 49:
            return False, f"La clave de acceso debe tener 49 dígitos (tiene {len(clave)})"

        if not clave.isdigit():
            return False, "La clave de acceso solo debe contener dígitos"

        # Validar estructura
        # Posiciones:
        # 0-7: Fecha emisión (ddmmaaaa)
        # 8-9: Tipo comprobante
        # 10-22: RUC emisor
        # 23-24: Tipo ambiente (1=pruebas, 2=producción)
        # 25-27: Serie establecimiento
        # 28-30: Punto de emisión
        # 31-39: Secuencial
        # 40-47: Código numérico
        # 48: Dígito verificador

        # Validar fecha (básico)
        dia = int(clave[0:2])
        mes = int(clave[2:4])
        if dia < 1 or dia > 31 or mes < 1 or mes > 12:
            return False, "Fecha de emisión inválida en la clave de acceso"

        # Validar tipo de comprobante
        tipo = clave[8:10]
        tipos_validos = ["01", "03", "04", "05", "06", "07"]
        if tipo not in tipos_validos:
            return False, f"Tipo de comprobante inválido: {tipo}"

        # Validar ambiente
        ambiente = clave[23:25]
        if ambiente not in ["01", "02"]:
            return False, f"Tipo de ambiente inválido: {ambiente}"

        return True, "Clave de acceso válida"

    def extraer_datos_clave(self, clave: str) -> dict[str, Any]:
        """
        Extrae los datos contenidos en una clave de acceso.

        Args:
            clave: Clave de acceso del comprobante (49 dígitos)

        Returns:
            Diccionario con los datos extraídos
        """
        if len(clave) != 49:
            return {}

        dia = clave[0:2]
        mes = clave[2:4]
        anio = clave[4:8]
        tipo_comp = clave[8:10]
        ruc = clave[10:23]
        ambiente = clave[23:25]
        serie_est = clave[25:28]
        punto_emi = clave[28:31]
        secuencial = clave[31:40]
        cod_numerico = clave[40:48]
        digito_ver = clave[48]

        tipo_nombre = {
            "01": "Factura",
            "03": "Liquidación de Compra",
            "04": "Nota de Crédito",
            "05": "Nota de Débito",
            "06": "Guía de Remisión",
            "07": "Comprobante de Retención"
        }.get(tipo_comp, "Desconocido")

        return {
            "fecha_emision": f"{dia}/{mes}/{anio}",
            "fecha_emision_iso": f"{anio}-{mes}-{dia}",
            "tipo_comprobante": tipo_comp,
            "tipo_comprobante_nombre": tipo_nombre,
            "ruc_emisor": ruc,
            "ambiente": "PRODUCCION" if ambiente == "02" else "PRUEBAS",
            "establecimiento": serie_est,
            "punto_emision": punto_emi,
            "secuencial": secuencial,
            "numero_comprobante": f"{serie_est}-{punto_emi}-{secuencial}",
            "codigo_numerico": cod_numerico,
            "digito_verificador": digito_ver
        }

    async def validar_comprobante(
        self,
        clave_acceso: str
    ) -> ResultadoValidacion:
        """
        Valida un comprobante electrónico con el SRI.

        Args:
            clave_acceso: Clave de acceso del comprobante (49 dígitos)

        Returns:
            ResultadoValidacion con el estado y detalles
        """
        # Validar formato primero
        es_valida, mensaje = self.validar_clave_acceso(clave_acceso)
        if not es_valida:
            return ResultadoValidacion(
                clave_acceso=clave_acceso,
                estado=EstadoAutorizacion.ERROR,
                numero_autorizacion=None,
                fecha_autorizacion=None,
                ambiente=self.ambiente,
                tipo_comprobante="",
                ruc_emisor="",
                fecha_emision="",
                comprobante_xml=None,
                mensajes=[{"tipo": "ERROR", "mensaje": mensaje}],
                validado_en=datetime.now()
            )

        # Extraer datos de la clave
        datos = self.extraer_datos_clave(clave_acceso)

        try:
            # Construir petición SOAP
            soap_request = self._construir_soap_request(clave_acceso)

            # Hacer petición
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.endpoint,
                    content=soap_request,
                    headers={
                        "Content-Type": "text/xml; charset=utf-8",
                        "SOAPAction": ""
                    }
                )

                if response.status_code == 200:
                    return self._parsear_respuesta_soap(clave_acceso, datos, response.text)
                else:
                    logger.error(
                        "Error en respuesta del SRI",
                        status_code=response.status_code,
                        clave=clave_acceso
                    )
                    return ResultadoValidacion(
                        clave_acceso=clave_acceso,
                        estado=EstadoAutorizacion.ERROR,
                        numero_autorizacion=None,
                        fecha_autorizacion=None,
                        ambiente=self.ambiente,
                        tipo_comprobante=datos.get("tipo_comprobante", ""),
                        ruc_emisor=datos.get("ruc_emisor", ""),
                        fecha_emision=datos.get("fecha_emision", ""),
                        comprobante_xml=None,
                        mensajes=[{
                            "tipo": "ERROR",
                            "mensaje": f"Error del servicio SRI: HTTP {response.status_code}"
                        }],
                        validado_en=datetime.now()
                    )

        except httpx.TimeoutException:
            logger.warning("Timeout consultando SRI", clave=clave_acceso)
            return ResultadoValidacion(
                clave_acceso=clave_acceso,
                estado=EstadoAutorizacion.ERROR,
                numero_autorizacion=None,
                fecha_autorizacion=None,
                ambiente=self.ambiente,
                tipo_comprobante=datos.get("tipo_comprobante", ""),
                ruc_emisor=datos.get("ruc_emisor", ""),
                fecha_emision=datos.get("fecha_emision", ""),
                comprobante_xml=None,
                mensajes=[{"tipo": "ERROR", "mensaje": "Timeout al consultar el SRI"}],
                validado_en=datetime.now()
            )
        except Exception as e:
            logger.error("Error validando comprobante", clave=clave_acceso, error=str(e))
            return ResultadoValidacion(
                clave_acceso=clave_acceso,
                estado=EstadoAutorizacion.ERROR,
                numero_autorizacion=None,
                fecha_autorizacion=None,
                ambiente=self.ambiente,
                tipo_comprobante=datos.get("tipo_comprobante", ""),
                ruc_emisor=datos.get("ruc_emisor", ""),
                fecha_emision=datos.get("fecha_emision", ""),
                comprobante_xml=None,
                mensajes=[{"tipo": "ERROR", "mensaje": str(e)}],
                validado_en=datetime.now()
            )

    def _construir_soap_request(self, clave_acceso: str) -> str:
        """Construye la petición SOAP para consultar autorización."""
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:ec="http://ec.gob.sri.ws.autorizacion">
   <soapenv:Header/>
   <soapenv:Body>
      <ec:autorizacionComprobante>
         <claveAccesoComprobante>{clave_acceso}</claveAccesoComprobante>
      </ec:autorizacionComprobante>
   </soapenv:Body>
</soapenv:Envelope>"""

    def _parsear_respuesta_soap(
        self,
        clave_acceso: str,
        datos: dict,
        xml_response: str
    ) -> ResultadoValidacion:
        """Parsea la respuesta SOAP del SRI."""
        try:
            # Parsear XML
            root = ET.fromstring(xml_response)

            # Buscar el elemento de respuesta
            # El namespace puede variar, buscar de forma flexible
            autorizacion = None
            for elem in root.iter():
                if "autorizacion" in elem.tag.lower() and not "autorizaciones" in elem.tag.lower():
                    if elem.text is None:  # Es un elemento contenedor
                        autorizacion = elem
                        break

            if autorizacion is None:
                # Intentar buscar de otra forma
                for elem in root.iter():
                    if "estado" in elem.tag.lower():
                        # Encontramos estado, buscar padre
                        autorizacion = elem.getparent() if hasattr(elem, 'getparent') else None
                        break

            # Extraer campos
            estado_texto = ""
            numero_aut = None
            fecha_aut = None
            comprobante_xml = None
            mensajes = []

            for elem in root.iter():
                tag_lower = elem.tag.lower()
                if "estado" in tag_lower and elem.text:
                    estado_texto = elem.text.upper()
                elif "numeroautorizacion" in tag_lower and elem.text:
                    numero_aut = elem.text
                elif "fechaautorizacion" in tag_lower and elem.text:
                    try:
                        fecha_aut = datetime.fromisoformat(elem.text.replace("Z", "+00:00"))
                    except:
                        fecha_aut = None
                elif "comprobante" in tag_lower and elem.text:
                    comprobante_xml = elem.text
                elif "mensaje" in tag_lower:
                    msg = {}
                    for child in elem:
                        if "tipo" in child.tag.lower():
                            msg["tipo"] = child.text or ""
                        elif "identificador" in child.tag.lower():
                            msg["identificador"] = child.text or ""
                        elif "mensaje" in child.tag.lower():
                            msg["mensaje"] = child.text or ""
                        elif "informacionadicional" in child.tag.lower():
                            msg["informacion_adicional"] = child.text or ""
                    if msg:
                        mensajes.append(msg)

            # Determinar estado
            estado = EstadoAutorizacion.DESCONOCIDO
            if "AUTORIZADO" in estado_texto:
                estado = EstadoAutorizacion.AUTORIZADO
            elif "NO AUTORIZADO" in estado_texto:
                estado = EstadoAutorizacion.NO_AUTORIZADO
            elif "PROCESO" in estado_texto:
                estado = EstadoAutorizacion.EN_PROCESO
            elif "DEVUELTO" in estado_texto:
                estado = EstadoAutorizacion.DEVUELTO

            return ResultadoValidacion(
                clave_acceso=clave_acceso,
                estado=estado,
                numero_autorizacion=numero_aut,
                fecha_autorizacion=fecha_aut,
                ambiente=self.ambiente,
                tipo_comprobante=datos.get("tipo_comprobante", ""),
                ruc_emisor=datos.get("ruc_emisor", ""),
                fecha_emision=datos.get("fecha_emision", ""),
                comprobante_xml=comprobante_xml,
                mensajes=mensajes,
                validado_en=datetime.now()
            )

        except ET.ParseError as e:
            logger.error("Error parseando respuesta XML", error=str(e))
            return ResultadoValidacion(
                clave_acceso=clave_acceso,
                estado=EstadoAutorizacion.ERROR,
                numero_autorizacion=None,
                fecha_autorizacion=None,
                ambiente=self.ambiente,
                tipo_comprobante=datos.get("tipo_comprobante", ""),
                ruc_emisor=datos.get("ruc_emisor", ""),
                fecha_emision=datos.get("fecha_emision", ""),
                comprobante_xml=None,
                mensajes=[{"tipo": "ERROR", "mensaje": f"Error parseando respuesta: {e}"}],
                validado_en=datetime.now()
            )

    async def guardar_validacion(self, resultado: ResultadoValidacion) -> bool:
        """
        Guarda el resultado de la validación en la base de datos.

        Args:
            resultado: Resultado de la validación

        Returns:
            True si se guardó correctamente
        """
        if not self.supabase:
            return False

        try:
            # Actualizar la factura recibida si existe
            self.supabase.table('facturas_recibidas').update({
                'estado_sri': resultado.estado.value,
                'numero_autorizacion': resultado.numero_autorizacion,
                'fecha_autorizacion': resultado.fecha_autorizacion.isoformat() if resultado.fecha_autorizacion else None,
                'validado_sri': True,
                'fecha_validacion_sri': resultado.validado_en.isoformat(),
                'updated_at': datetime.now().isoformat()
            }).eq('clave_acceso', resultado.clave_acceso).execute()
            return True
        except Exception as e:
            logger.error("Error guardando validación", error=str(e))
            return False
