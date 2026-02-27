"""
Servicio de Validación y Consulta de RUC.
Consulta información del RUC desde el portal del SRI.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class InfoRUC:
    """Información del RUC obtenida del SRI."""
    ruc: str
    razon_social: str
    nombre_comercial: Optional[str]
    estado: str  # ACTIVO, PASIVO, SUSPENDIDO
    tipo_contribuyente: str  # PERSONA NATURAL, SOCIEDAD
    obligado_contabilidad: bool
    actividad_economica: Optional[str]
    fecha_inicio_actividades: Optional[str]
    direccion: Optional[str]
    fecha_consulta: datetime
    es_contribuyente_especial: bool = False
    es_exportador: bool = False
    agente_retencion: bool = False


class ServicioRUC:
    """Servicio para consulta y validación de RUC."""

    # URL del portal SRI para consulta de RUC
    SRI_URL = "https://srienlinea.sri.gob.ec/sri-en-linea/SriRucWeb/ConsultaRuc/Consultas/consultaRuc"
    SRI_API_URL = "https://srienlinea.sri.gob.ec/sri-catastro-sujeto-servicio-internet/rest/ConsolidadoContribuyente/obtenerPorNumerosRuc"

    # Cache de consultas (en memoria)
    _cache: dict[str, tuple[InfoRUC, datetime]] = {}
    CACHE_DURATION = timedelta(hours=24)

    def __init__(self, supabase_client=None):
        self.supabase = supabase_client

    def validar_formato_ruc(self, ruc: str) -> tuple[bool, str]:
        """
        Valida el formato del RUC.

        Args:
            ruc: Número de RUC a validar

        Returns:
            Tuple (es_valido, mensaje)
        """
        # Debe ser string de 13 dígitos
        if not ruc or not isinstance(ruc, str):
            return False, "El RUC debe ser una cadena de texto"

        ruc = ruc.strip()

        if len(ruc) != 13:
            return False, "El RUC debe tener 13 dígitos"

        if not ruc.isdigit():
            return False, "El RUC solo debe contener dígitos"

        # Validar código de provincia (primeros 2 dígitos)
        provincia = int(ruc[:2])
        if provincia < 1 or provincia > 24:
            if provincia != 30:  # Código especial para extranjeros
                return False, "Código de provincia inválido"

        # Validar tercer dígito (tipo de contribuyente)
        tercer_digito = int(ruc[2])
        if tercer_digito == 6:
            # Entidad pública
            if ruc[10:13] != "001":
                return False, "RUC de entidad pública debe terminar en 001"
        elif tercer_digito == 9:
            # Sociedad privada o extranjera
            if ruc[10:13] != "001":
                return False, "RUC de sociedad debe terminar en 001"
        elif tercer_digito < 6:
            # Persona natural
            if ruc[10:13] != "001":
                return False, "RUC de persona natural debe terminar en 001"
        else:
            return False, "Tercer dígito del RUC inválido"

        # Validar dígito verificador (módulo 11 o módulo 10)
        if not self._validar_digito_verificador(ruc):
            return False, "Dígito verificador inválido"

        return True, "RUC válido"

    def _validar_digito_verificador(self, ruc: str) -> bool:
        """Valida el dígito verificador del RUC."""
        tercer_digito = int(ruc[2])

        if tercer_digito < 6:
            # Persona natural - módulo 10
            coeficientes = [2, 1, 2, 1, 2, 1, 2, 1, 2]
            suma = 0
            for i, coef in enumerate(coeficientes):
                producto = int(ruc[i]) * coef
                if producto >= 10:
                    producto -= 9
                suma += producto
            verificador = (10 - (suma % 10)) % 10
            return verificador == int(ruc[9])

        elif tercer_digito == 6:
            # Entidad pública - módulo 11
            coeficientes = [3, 2, 7, 6, 5, 4, 3, 2]
            suma = sum(int(ruc[i]) * coef for i, coef in enumerate(coeficientes))
            verificador = 11 - (suma % 11)
            if verificador == 11:
                verificador = 0
            return verificador == int(ruc[8])

        elif tercer_digito == 9:
            # Sociedad privada - módulo 11
            coeficientes = [4, 3, 2, 7, 6, 5, 4, 3, 2]
            suma = sum(int(ruc[i]) * coef for i, coef in enumerate(coeficientes))
            verificador = 11 - (suma % 11)
            if verificador == 11:
                verificador = 0
            return verificador == int(ruc[9])

        return False

    def obtener_tipo_contribuyente_codigo(self, ruc: str) -> str:
        """
        Obtiene el código de tipo de contribuyente basado en el RUC.

        Args:
            ruc: Número de RUC

        Returns:
            Código de tipo (SOCIEDAD, PN_OBLIG, PN_NO_OBLIG, etc.)
        """
        if len(ruc) != 13:
            return "DESCONOCIDO"

        tercer_digito = int(ruc[2])

        if tercer_digito == 6:
            return "SECTOR_PUBLICO"
        elif tercer_digito == 9:
            return "SOCIEDAD"
        elif tercer_digito < 6:
            # Persona natural - asumimos no obligado por defecto
            # Esto se refinará con la consulta al SRI
            return "PN_NO_OBLIG"

        return "DESCONOCIDO"

    async def consultar_ruc(
        self,
        ruc: str,
        usar_cache: bool = True
    ) -> Optional[InfoRUC]:
        """
        Consulta información del RUC desde el SRI.

        Args:
            ruc: Número de RUC a consultar
            usar_cache: Si debe usar cache de consultas anteriores

        Returns:
            InfoRUC con la información del contribuyente
        """
        # Validar formato primero
        es_valido, mensaje = self.validar_formato_ruc(ruc)
        if not es_valido:
            logger.warning("RUC inválido", ruc=ruc, mensaje=mensaje)
            return None

        # Verificar cache
        if usar_cache and ruc in self._cache:
            info, timestamp = self._cache[ruc]
            if datetime.now() - timestamp < self.CACHE_DURATION:
                logger.debug("RUC obtenido de cache", ruc=ruc)
                return info

        # Intentar consulta al SRI
        try:
            info = await self._consultar_sri(ruc)
            if info:
                # Guardar en cache
                self._cache[ruc] = (info, datetime.now())
                # Guardar en DB si está disponible
                await self._guardar_en_db(info)
                return info
        except Exception as e:
            logger.error("Error consultando RUC al SRI", ruc=ruc, error=str(e))

        # Fallback: intentar obtener de DB
        info_db = await self._obtener_de_db(ruc)
        if info_db:
            return info_db

        # Si no se pudo consultar, crear info básica
        return self._crear_info_basica(ruc)

    async def _consultar_sri(self, ruc: str) -> Optional[InfoRUC]:
        """Consulta el RUC directamente al SRI."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Intentar API REST primero
                response = await client.post(
                    self.SRI_API_URL,
                    json={"numeroRuc": ruc},
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json"
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    if data:
                        return self._parsear_respuesta_api(ruc, data)

        except httpx.TimeoutException:
            logger.warning("Timeout consultando SRI", ruc=ruc)
        except Exception as e:
            logger.warning("Error en consulta SRI", ruc=ruc, error=str(e))

        return None

    def _parsear_respuesta_api(self, ruc: str, data: dict) -> InfoRUC:
        """Parsea la respuesta de la API del SRI."""
        # La estructura puede variar, esto es una aproximación
        return InfoRUC(
            ruc=ruc,
            razon_social=data.get('razonSocial', data.get('nombreCompleto', 'Desconocido')),
            nombre_comercial=data.get('nombreComercial'),
            estado=data.get('estado', 'DESCONOCIDO').upper(),
            tipo_contribuyente=data.get('tipoContribuyente', 'DESCONOCIDO'),
            obligado_contabilidad=data.get('obligadoContabilidad', False),
            actividad_economica=data.get('actividadEconomica'),
            fecha_inicio_actividades=data.get('fechaInicioActividades'),
            direccion=data.get('direccion'),
            fecha_consulta=datetime.now(),
            es_contribuyente_especial=data.get('contribuyenteEspecial', False),
            es_exportador=data.get('exportadorHabitual', False),
            agente_retencion=data.get('agenteRetencion', False)
        )

    def _crear_info_basica(self, ruc: str) -> InfoRUC:
        """Crea información básica basada solo en el formato del RUC."""
        tercer_digito = int(ruc[2])

        if tercer_digito == 6:
            tipo = "SECTOR PÚBLICO"
            obligado = True
        elif tercer_digito == 9:
            tipo = "SOCIEDAD PRIVADA"
            obligado = True
        else:
            tipo = "PERSONA NATURAL"
            obligado = False  # Por defecto, se debe confirmar con consulta

        return InfoRUC(
            ruc=ruc,
            razon_social="(Consulta pendiente)",
            nombre_comercial=None,
            estado="PENDIENTE VERIFICACIÓN",
            tipo_contribuyente=tipo,
            obligado_contabilidad=obligado,
            actividad_economica=None,
            fecha_inicio_actividades=None,
            direccion=None,
            fecha_consulta=datetime.now()
        )

    async def _guardar_en_db(self, info: InfoRUC) -> None:
        """Guarda o actualiza la información del RUC en la base de datos."""
        if not self.supabase:
            return

        try:
            # Intentar actualizar proveedor existente o crear nuevo registro en cache
            self.supabase.table('proveedores').upsert({
                'ruc': info.ruc,
                'razon_social': info.razon_social,
                'nombre_comercial': info.nombre_comercial,
                'tipo_contribuyente': info.tipo_contribuyente,
                'estado_sri': info.estado,
                'obligado_contabilidad': info.obligado_contabilidad,
                'es_contribuyente_especial': info.es_contribuyente_especial,
                'actividad_economica': info.actividad_economica,
                'direccion': info.direccion,
                'ultima_verificacion_sri': info.fecha_consulta.isoformat(),
                'updated_at': datetime.now().isoformat()
            }, on_conflict='ruc').execute()
        except Exception as e:
            logger.warning("Error guardando RUC en DB", ruc=info.ruc, error=str(e))

    async def _obtener_de_db(self, ruc: str) -> Optional[InfoRUC]:
        """Obtiene información del RUC desde la base de datos."""
        if not self.supabase:
            return None

        try:
            result = self.supabase.table('proveedores').select(
                'ruc, razon_social, nombre_comercial, tipo_contribuyente, '
                'estado_sri, obligado_contabilidad, es_contribuyente_especial, '
                'actividad_economica, direccion, ultima_verificacion_sri'
            ).eq('ruc', ruc).limit(1).execute()

            if result.data:
                row = result.data[0]
                return InfoRUC(
                    ruc=row['ruc'],
                    razon_social=row['razon_social'],
                    nombre_comercial=row.get('nombre_comercial'),
                    estado=row.get('estado_sri', 'DESCONOCIDO'),
                    tipo_contribuyente=row.get('tipo_contribuyente', 'DESCONOCIDO'),
                    obligado_contabilidad=row.get('obligado_contabilidad', False),
                    actividad_economica=row.get('actividad_economica'),
                    fecha_inicio_actividades=None,
                    direccion=row.get('direccion'),
                    fecha_consulta=datetime.fromisoformat(
                        row['ultima_verificacion_sri']
                    ) if row.get('ultima_verificacion_sri') else datetime.now(),
                    es_contribuyente_especial=row.get('es_contribuyente_especial', False)
                )
        except Exception as e:
            logger.warning("Error obteniendo RUC de DB", ruc=ruc, error=str(e))

        return None

    def determinar_tipo_retencion(self, info: InfoRUC) -> str:
        """
        Determina el código de tipo de contribuyente para retenciones.

        Args:
            info: Información del RUC

        Returns:
            Código para usar en matriz de retenciones (ESPECIAL, SOCIEDAD, PN_OBLIG, etc.)
        """
        if info.es_contribuyente_especial:
            return "ESPECIAL"

        tipo = info.tipo_contribuyente.upper()

        if "SOCIEDAD" in tipo or "PRIVADA" in tipo or "JURÍDICA" in tipo:
            return "SOCIEDAD"

        if "PÚBLICO" in tipo or "PUBLICA" in tipo:
            return "SECTOR_PUBLICO"

        if "NATURAL" in tipo:
            if info.obligado_contabilidad:
                return "PN_OBLIG"
            else:
                return "PN_NO_OBLIG"

        return "SOCIEDAD"  # Default seguro

    def limpiar_cache(self) -> int:
        """
        Limpia el cache de consultas expiradas.

        Returns:
            Número de entradas eliminadas
        """
        ahora = datetime.now()
        expirados = [
            ruc for ruc, (_, timestamp) in self._cache.items()
            if ahora - timestamp >= self.CACHE_DURATION
        ]
        for ruc in expirados:
            del self._cache[ruc]
        return len(expirados)
