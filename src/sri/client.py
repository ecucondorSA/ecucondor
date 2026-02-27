"""
ECUCONDOR - Cliente SOAP para Web Services del SRI
Maneja la comunicación con los servicios de Recepción y Autorización.
"""

import base64
from typing import Any

import structlog
from zeep import Client
from zeep.exceptions import Fault, TransportError
from zeep.transports import Transport
from requests import Session
from requests.exceptions import ConnectionError, Timeout

from src.config.settings import get_settings
from src.sri.models import (
    AutorizacionSRI,
    EstadoComprobante,
    MensajeSRI,
    RespuestaAutorizacion,
    RespuestaRecepcion,
)
from src.sri.retry import (
    ExponentialBackoff,
    RetryConfig,
    SRIConnectionError,
    SRIServiceUnavailable,
    SRITimeoutError,
    SRIValidationError,
    classify_sri_error,
    with_retry,
)

logger = structlog.get_logger(__name__)


# URLs de los Web Services del SRI
SRI_ENDPOINTS = {
    "pruebas": {
        "recepcion": "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl",
        "autorizacion": "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl",
    },
    "produccion": {
        "recepcion": "https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl",
        "autorizacion": "https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl",
    },
}


class SRIClient:
    """
    Cliente para comunicación con los Web Services del SRI.

    Implementa los métodos de:
    - Recepción de comprobantes (validarComprobante)
    - Autorización de comprobantes (autorizacionComprobante)
    """

    def __init__(
        self,
        ambiente: str = "1",
        timeout: int = 60,
    ):
        """
        Inicializa el cliente SRI.

        Args:
            ambiente: '1' para pruebas, '2' para producción
            timeout: Timeout de conexión en segundos
        """
        self.ambiente = "produccion" if ambiente == "2" else "pruebas"
        self.timeout = timeout

        # Configurar sesión HTTP
        self._session = Session()
        self._session.headers.update({
            "Content-Type": "text/xml; charset=utf-8",
        })

        # Transport de Zeep con timeout
        self._transport = Transport(
            session=self._session,
            timeout=timeout,
            operation_timeout=timeout,
        )

        # Clientes SOAP (lazy loading)
        self._client_recepcion: Client | None = None
        self._client_autorizacion: Client | None = None

        logger.info(
            "Cliente SRI inicializado",
            ambiente=self.ambiente,
            timeout=timeout,
        )

    @property
    def client_recepcion(self) -> Client:
        """Cliente SOAP para el servicio de Recepción (lazy loading)."""
        if self._client_recepcion is None:
            url = SRI_ENDPOINTS[self.ambiente]["recepcion"]
            logger.debug("Conectando a servicio de Recepción", url=url)
            self._client_recepcion = Client(url, transport=self._transport)
        return self._client_recepcion

    @property
    def client_autorizacion(self) -> Client:
        """Cliente SOAP para el servicio de Autorización (lazy loading)."""
        if self._client_autorizacion is None:
            url = SRI_ENDPOINTS[self.ambiente]["autorizacion"]
            logger.debug("Conectando a servicio de Autorización", url=url)
            self._client_autorizacion = Client(url, transport=self._transport)
        return self._client_autorizacion

    @with_retry(max_attempts=RetryConfig.MAX_ATTEMPTS)
    def enviar_comprobante(self, xml_firmado: str) -> RespuestaRecepcion:
        """
        Envía un comprobante firmado al servicio de Recepción del SRI.

        Args:
            xml_firmado: Documento XML firmado en formato string

        Returns:
            RespuestaRecepcion con el estado del envío

        Raises:
            SRIConnectionError: Error de conexión
            SRITimeoutError: Timeout en la comunicación
            SRIValidationError: Error de validación del comprobante
        """
        try:
            logger.info("Enviando comprobante al SRI")

            # Codificar XML en base64 como requiere el SRI
            xml_bytes = xml_firmado.encode("utf-8")

            # Llamar al servicio
            response = self.client_recepcion.service.validarComprobante(xml_bytes)

            # Procesar respuesta
            estado = response.estado if hasattr(response, "estado") else "ERROR"

            logger.info(
                "Respuesta de Recepción SRI",
                estado=estado,
            )

            # Extraer comprobantes/errores
            comprobantes = []
            if hasattr(response, "comprobantes") and response.comprobantes:
                for comp in response.comprobantes.comprobante:
                    comp_dict = {
                        "clave_acceso": getattr(comp, "claveAcceso", None),
                        "mensajes": [],
                    }

                    if hasattr(comp, "mensajes") and comp.mensajes:
                        for msg in comp.mensajes.mensaje:
                            comp_dict["mensajes"].append({
                                "identificador": getattr(msg, "identificador", ""),
                                "mensaje": getattr(msg, "mensaje", ""),
                                "informacion_adicional": getattr(msg, "informacionAdicional", ""),
                                "tipo": getattr(msg, "tipo", ""),
                            })

                    comprobantes.append(comp_dict)

            return RespuestaRecepcion(
                estado=estado,
                comprobantes=comprobantes if comprobantes else None,
            )

        except Fault as e:
            logger.error("Error SOAP en Recepción", fault=str(e))
            raise SRIValidationError(f"Error SOAP: {e}")

        except (ConnectionError, Timeout) as e:
            logger.error("Error de conexión con SRI", error=str(e))
            raise SRIConnectionError(f"Error de conexión: {e}")

        except TransportError as e:
            logger.error("Error de transporte", error=str(e))
            raise SRIConnectionError(f"Error de transporte: {e}")

    @with_retry(max_attempts=RetryConfig.MAX_ATTEMPTS)
    def consultar_autorizacion(self, clave_acceso: str) -> RespuestaAutorizacion:
        """
        Consulta el estado de autorización de un comprobante.

        Args:
            clave_acceso: Clave de acceso de 49 dígitos del comprobante

        Returns:
            RespuestaAutorizacion con el estado y detalles

        Raises:
            SRIConnectionError: Error de conexión
            SRITimeoutError: Timeout en la comunicación
        """
        try:
            logger.info("Consultando autorización", clave_acceso=clave_acceso[:20] + "...")

            # Llamar al servicio
            response = self.client_autorizacion.service.autorizacionComprobante(clave_acceso)

            # Procesar respuesta
            autorizaciones: list[AutorizacionSRI] = []

            if hasattr(response, "autorizaciones") and response.autorizaciones:
                for auth in response.autorizaciones.autorizacion:
                    mensajes: list[MensajeSRI] = []

                    if hasattr(auth, "mensajes") and auth.mensajes:
                        for msg in auth.mensajes.mensaje:
                            mensajes.append(MensajeSRI(
                                identificador=getattr(msg, "identificador", ""),
                                mensaje=getattr(msg, "mensaje", ""),
                                informacion_adicional=getattr(msg, "informacionAdicional", None),
                                tipo=getattr(msg, "tipo", None),
                            ))

                    autorizaciones.append(AutorizacionSRI(
                        estado=getattr(auth, "estado", "DESCONOCIDO"),
                        numero_autorizacion=getattr(auth, "numeroAutorizacion", None),
                        fecha_autorizacion=getattr(auth, "fechaAutorizacion", None),
                        ambiente=getattr(auth, "ambiente", None),
                        comprobante=getattr(auth, "comprobante", None),
                        mensajes=mensajes,
                    ))

            num_comprobantes = len(autorizaciones)

            logger.info(
                "Respuesta de Autorización SRI",
                clave_acceso=clave_acceso[:20] + "...",
                num_autorizaciones=num_comprobantes,
                estado=autorizaciones[0].estado if autorizaciones else "SIN RESPUESTA",
            )

            return RespuestaAutorizacion(
                clave_acceso_consultada=clave_acceso,
                numero_comprobantes=num_comprobantes,
                autorizaciones=autorizaciones,
            )

        except Fault as e:
            logger.error("Error SOAP en Autorización", fault=str(e))
            raise SRIValidationError(f"Error SOAP: {e}")

        except (ConnectionError, Timeout) as e:
            logger.error("Error de conexión con SRI", error=str(e))
            raise SRIConnectionError(f"Error de conexión: {e}")

        except TransportError as e:
            logger.error("Error de transporte", error=str(e))
            raise SRIConnectionError(f"Error de transporte: {e}")

    async def enviar_y_autorizar(
        self,
        xml_firmado: str,
        clave_acceso: str,
        max_intentos_autorizacion: int = 10,
        espera_entre_consultas: float = 3.0,
    ) -> dict[str, Any]:
        """
        Flujo completo: envía el comprobante y consulta la autorización.

        Este método implementa el flujo recomendado por el SRI:
        1. Enviar comprobante al servicio de Recepción
        2. Esperar unos segundos
        3. Consultar autorización hasta obtener respuesta definitiva

        Args:
            xml_firmado: XML firmado del comprobante
            clave_acceso: Clave de acceso de 49 dígitos
            max_intentos_autorizacion: Máximo de consultas de autorización
            espera_entre_consultas: Segundos entre cada consulta

        Returns:
            Diccionario con:
                - estado: EstadoComprobante
                - numero_autorizacion: str | None
                - fecha_autorizacion: datetime | None
                - xml_autorizado: str | None
                - mensajes: list[dict]
        """
        import asyncio

        resultado = {
            "estado": EstadoComprobante.ERROR,
            "numero_autorizacion": None,
            "fecha_autorizacion": None,
            "xml_autorizado": None,
            "mensajes": [],
        }

        # Paso 1: Enviar comprobante
        try:
            respuesta_recepcion = self.enviar_comprobante(xml_firmado)

            if respuesta_recepcion.estado == "DEVUELTA":
                # Comprobante rechazado en recepción
                resultado["estado"] = EstadoComprobante.REJECTED

                if respuesta_recepcion.comprobantes:
                    for comp in respuesta_recepcion.comprobantes:
                        resultado["mensajes"].extend(comp.get("mensajes", []))

                logger.warning(
                    "Comprobante devuelto por el SRI",
                    mensajes=resultado["mensajes"],
                )
                return resultado

            # Comprobante recibido, proceder a consultar autorización
            resultado["estado"] = EstadoComprobante.RECEIVED

        except Exception as e:
            logger.error("Error al enviar comprobante", error=str(e))
            resultado["mensajes"].append({
                "identificador": "ERROR",
                "mensaje": str(e),
            })
            return resultado

        # Paso 2: Esperar antes de primera consulta
        await asyncio.sleep(espera_entre_consultas)

        # Paso 3: Consultar autorización con reintentos
        backoff = ExponentialBackoff(
            max_attempts=max_intentos_autorizacion,
            base_wait=espera_entre_consultas,
            max_wait=30.0,
        )

        while backoff.should_retry():
            backoff.next_attempt()

            try:
                respuesta_auth = self.consultar_autorizacion(clave_acceso)

                if respuesta_auth.autorizaciones:
                    auth = respuesta_auth.autorizaciones[0]

                    if auth.estado == "AUTORIZADO":
                        resultado["estado"] = EstadoComprobante.AUTHORIZED
                        resultado["numero_autorizacion"] = auth.numero_autorizacion
                        resultado["fecha_autorizacion"] = auth.fecha_autorizacion
                        resultado["xml_autorizado"] = auth.comprobante

                        logger.info(
                            "Comprobante autorizado",
                            numero_autorizacion=auth.numero_autorizacion,
                        )
                        return resultado

                    elif auth.estado == "NO AUTORIZADO":
                        resultado["estado"] = EstadoComprobante.REJECTED
                        resultado["mensajes"] = [
                            {
                                "identificador": m.identificador,
                                "mensaje": m.mensaje,
                                "informacion_adicional": m.informacion_adicional,
                            }
                            for m in auth.mensajes
                        ]

                        logger.warning(
                            "Comprobante no autorizado",
                            mensajes=resultado["mensajes"],
                        )
                        return resultado

                    else:
                        # Estado intermedio, seguir consultando
                        logger.debug(
                            "Estado intermedio, reintentando",
                            estado=auth.estado,
                            intento=backoff.attempt,
                        )

            except Exception as e:
                logger.warning(
                    "Error en consulta de autorización",
                    error=str(e),
                    intento=backoff.attempt,
                )

            if backoff.should_retry():
                await backoff.wait()

        # Se agotaron los intentos
        resultado["estado"] = EstadoComprobante.PENDING
        resultado["mensajes"].append({
            "identificador": "TIMEOUT",
            "mensaje": "Se agotaron los intentos de consulta de autorización",
        })

        logger.warning(
            "Timeout consultando autorización",
            clave_acceso=clave_acceso[:20] + "...",
            intentos=backoff.attempt,
        )

        return resultado


def get_sri_client() -> SRIClient:
    """
    Factory function para obtener un cliente SRI configurado.

    Returns:
        Cliente SRI configurado según el ambiente de settings
    """
    settings = get_settings()
    return SRIClient(ambiente=settings.sri_ambiente)
