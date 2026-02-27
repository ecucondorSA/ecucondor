"""
ECUCONDOR - Normalizador de Transacciones
Limpia y estandariza descripciones, sugiere categorías y cuentas contables.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

import structlog

from src.config.constants import MCC_BLOQUEADOS
from src.ingestor.models import (
    OrigenTransaccion,
    TipoTransaccion,
    TransaccionBancaria,
)

logger = structlog.get_logger(__name__)


@dataclass
class ReglaCategorizacion:
    """Regla para categorizar transacciones."""

    nombre: str
    patrones: list[str]  # Regex patterns
    cuenta_contable: str
    categoria: str
    confianza: float = 0.8
    solo_credito: bool = False
    solo_debito: bool = False


class TransactionNormalizer:
    """
    Normalizador de transacciones bancarias.

    Funcionalidades:
    - Limpia y estandariza descripciones
    - Sugiere categorías contables
    - Mapea a cuentas NIIF
    - Detecta transacciones sospechosas (Muralla China)
    """

    # Reglas de categorización por tipo de negocio (alquiler de vehículos)
    REGLAS_CATEGORIZACION: list[ReglaCategorizacion] = [
        # === INGRESOS (Créditos) ===
        ReglaCategorizacion(
            nombre="Pago de alquiler",
            patrones=[
                r"alquiler",
                r"renta.*vehiculo",
                r"arrendamiento",
                r"rent.*car",
                r"pago.*reserva",
            ],
            cuenta_contable="4.1.01",  # Ingresos por servicios
            categoria="ingreso_operacional",
            confianza=0.9,
            solo_credito=True,
        ),
        ReglaCategorizacion(
            nombre="Pago tarjeta (cliente)",
            patrones=[
                r"datafast",
                r"medianet",
                r"pago.*pos",
                r"venta.*establecimiento",
            ],
            cuenta_contable="4.1.01",
            categoria="ingreso_tarjeta",
            confianza=0.85,
            solo_credito=True,
        ),
        ReglaCategorizacion(
            nombre="Transferencia recibida",
            patrones=[
                r"transf.*recibida",
                r"ach.*entrante",
                r"spi.*entrada",
                r"deposito.*transfer",
            ],
            cuenta_contable="1.1.03",  # Bancos
            categoria="transferencia_entrada",
            confianza=0.7,
            solo_credito=True,
        ),

        # === GASTOS OPERACIONALES (Débitos) ===
        ReglaCategorizacion(
            nombre="Combustible",
            patrones=[
                r"gasolina",
                r"combustible",
                r"petroecuador",
                r"primax",
                r"mobil",
                r"shell",
                r"puma.*energy",
                r"gasolinera",
            ],
            cuenta_contable="5.2.05",  # Combustibles
            categoria="gasto_combustible",
            confianza=0.95,
            solo_debito=True,
        ),
        ReglaCategorizacion(
            nombre="Mantenimiento vehículos",
            patrones=[
                r"taller",
                r"mecanica",
                r"repuesto",
                r"llanta",
                r"lubricante",
                r"cambio.*aceite",
                r"lavadora",
                r"lavado.*auto",
                r"autopista",  # Peajes
                r"peaje",
            ],
            cuenta_contable="5.2.06",  # Mantenimiento
            categoria="gasto_mantenimiento",
            confianza=0.9,
            solo_debito=True,
        ),
        ReglaCategorizacion(
            nombre="Seguros",
            patrones=[
                r"seguro",
                r"aseguradora",
                r"poliza",
                r"prima.*seguro",
                r"equinoccial",
                r"seguros.*oriente",
                r"liberty",
                r"mapfre",
            ],
            cuenta_contable="5.2.07",  # Seguros
            categoria="gasto_seguro",
            confianza=0.9,
            solo_debito=True,
        ),
        ReglaCategorizacion(
            nombre="Arriendo local/oficina",
            patrones=[
                r"arriendo.*local",
                r"arriendo.*oficina",
                r"alquiler.*local",
                r"canon.*arrendamiento",
            ],
            cuenta_contable="5.2.01",  # Arriendos
            categoria="gasto_arriendo",
            confianza=0.85,
            solo_debito=True,
        ),

        # === GASTOS ADMINISTRATIVOS ===
        ReglaCategorizacion(
            nombre="Servicios básicos",
            patrones=[
                r"luz",
                r"agua",
                r"telefono",
                r"internet",
                r"cnt",
                r"claro",
                r"movistar",
                r"ee.*quito",  # Empresa Eléctrica
                r"emaap",
                r"interagua",
            ],
            cuenta_contable="5.2.03",  # Servicios básicos
            categoria="gasto_servicios",
            confianza=0.9,
            solo_debito=True,
        ),
        ReglaCategorizacion(
            nombre="Comisiones bancarias",
            patrones=[
                r"comision",
                r"costo.*mensual",
                r"mantenimiento.*cuenta",
                r"costo.*chequ",
                r"cargo.*admin",
            ],
            cuenta_contable="5.3.02",  # Gastos financieros
            categoria="gasto_bancario",
            confianza=0.95,
            solo_debito=True,
        ),

        # === IMPUESTOS ===
        ReglaCategorizacion(
            nombre="Impuesto salida divisas",
            patrones=[
                r"isd",
                r"impuesto.*salida.*divisas",
            ],
            cuenta_contable="5.3.03",  # Impuestos
            categoria="impuesto_isd",
            confianza=0.95,
            solo_debito=True,
        ),
        ReglaCategorizacion(
            nombre="Impuesto GMT",
            patrones=[
                r"gmt",
                r"gravamen.*movimiento",
            ],
            cuenta_contable="5.3.03",
            categoria="impuesto_gmt",
            confianza=0.95,
            solo_debito=True,
        ),
        ReglaCategorizacion(
            nombre="Pago SRI",
            patrones=[
                r"sri",
                r"servicio.*rentas",
                r"pago.*impuesto",
                r"formulario.*104",
                r"formulario.*103",
            ],
            cuenta_contable="2.1.05",  # Impuestos por pagar
            categoria="pago_impuesto_sri",
            confianza=0.9,
            solo_debito=True,
        ),

        # === NÓMINA Y HONORARIOS ===
        ReglaCategorizacion(
            nombre="Pago IESS",
            patrones=[
                r"iess",
                r"seguro.*social",
                r"aporte.*patronal",
                r"fondo.*reserva",
            ],
            cuenta_contable="2.1.06",  # IESS por pagar
            categoria="pago_iess",
            confianza=0.95,
            solo_debito=True,
        ),
        ReglaCategorizacion(
            nombre="Honorarios profesionales",
            patrones=[
                r"honorario",
                r"servicios.*profesionales",
                r"asesoria",
                r"consultoria",
            ],
            cuenta_contable="5.2.08",  # Honorarios
            categoria="gasto_honorarios",
            confianza=0.8,
            solo_debito=True,
        ),
    ]

    # Palabras a remover/normalizar en descripciones
    PALABRAS_RUIDO = [
        r"\s+",           # Espacios múltiples
        r"^\d+\s*",       # Números al inicio
        r"\s*-\s*$",      # Guiones al final
        r"\.{2,}",        # Puntos múltiples
        r"\*+",           # Asteriscos
    ]

    # Abreviaciones comunes a expandir
    ABREVIACIONES = {
        r"\bTRF\b": "TRANSFERENCIA",
        r"\bDEP\b": "DEPOSITO",
        r"\bRET\b": "RETIRO",
        r"\bCTA\b": "CUENTA",
        r"\bNRO\b": "NUMERO",
        r"\bPAG\b": "PAGO",
        r"\bCOMP\b": "COMPROBANTE",
        r"\bVENT\b": "VENTANILLA",
        r"\bEFECT\b": "EFECTIVO",
        r"\bCH\b": "CHEQUE",
        r"\bSUC\b": "SUCURSAL",
        r"\bOF\b": "OFICINA",
    }

    def __init__(self):
        """Inicializa el normalizador."""
        # Compilar patrones de reglas
        for regla in self.REGLAS_CATEGORIZACION:
            regla._compiled = [
                re.compile(p, re.IGNORECASE)
                for p in regla.patrones
            ]

    def normalizar(
        self,
        transaccion: TransaccionBancaria,
    ) -> TransaccionBancaria:
        """
        Normaliza una transacción.

        Args:
            transaccion: Transacción a normalizar

        Returns:
            Transacción normalizada
        """
        # Limpiar descripción
        desc_normalizada = self._limpiar_descripcion(
            transaccion.descripcion_original
        )
        transaccion.descripcion_normalizada = desc_normalizada

        # Categorizar
        categoria, cuenta, confianza = self._categorizar(transaccion)
        transaccion.categoria_sugerida = categoria
        transaccion.cuenta_contable_sugerida = cuenta
        transaccion.confianza_categoria = confianza

        return transaccion

    def normalizar_lote(
        self,
        transacciones: list[TransaccionBancaria],
    ) -> list[TransaccionBancaria]:
        """
        Normaliza un lote de transacciones.

        Args:
            transacciones: Lista de transacciones

        Returns:
            Lista de transacciones normalizadas
        """
        return [self.normalizar(tx) for tx in transacciones]

    def _limpiar_descripcion(self, descripcion: str) -> str:
        """
        Limpia y estandariza una descripción.

        Args:
            descripcion: Descripción original

        Returns:
            Descripción limpia
        """
        if not descripcion:
            return ""

        texto = descripcion.strip().upper()

        # Expandir abreviaciones
        for patron, expansion in self.ABREVIACIONES.items():
            texto = re.sub(patron, expansion, texto)

        # Remover ruido
        for patron in self.PALABRAS_RUIDO:
            texto = re.sub(patron, " ", texto)

        # Limpiar espacios
        texto = " ".join(texto.split())

        return texto

    def _categorizar(
        self,
        transaccion: TransaccionBancaria,
    ) -> tuple[str | None, str | None, float | None]:
        """
        Categoriza una transacción.

        Args:
            transaccion: Transacción a categorizar

        Returns:
            Tupla (categoria, cuenta_contable, confianza)
        """
        descripcion = transaccion.descripcion_normalizada or transaccion.descripcion_original
        descripcion_lower = descripcion.lower()

        mejor_match: tuple[str | None, str | None, float] = (None, None, 0.0)

        for regla in self.REGLAS_CATEGORIZACION:
            # Verificar restricción de tipo
            if regla.solo_credito and transaccion.tipo != TipoTransaccion.CREDITO:
                continue
            if regla.solo_debito and transaccion.tipo != TipoTransaccion.DEBITO:
                continue

            # Buscar match
            for patron in regla._compiled:
                if patron.search(descripcion_lower):
                    if regla.confianza > mejor_match[2]:
                        mejor_match = (
                            regla.categoria,
                            regla.cuenta_contable,
                            regla.confianza,
                        )
                    break

        if mejor_match[2] > 0:
            return mejor_match

        # Categorización por defecto basada en origen
        return self._categorizar_por_origen(transaccion)

    def _categorizar_por_origen(
        self,
        transaccion: TransaccionBancaria,
    ) -> tuple[str | None, str | None, float | None]:
        """
        Categoriza basándose en el origen de la transacción.

        Args:
            transaccion: Transacción

        Returns:
            Tupla (categoria, cuenta, confianza)
        """
        origen = transaccion.origen

        if transaccion.tipo == TipoTransaccion.CREDITO:
            # Ingresos
            if origen == OrigenTransaccion.TRANSFERENCIA:
                return ("transferencia_entrada", "1.1.03", 0.5)
            elif origen == OrigenTransaccion.DEPOSITO:
                return ("deposito_recibido", "1.1.03", 0.5)
            elif origen == OrigenTransaccion.PAGO_TARJETA:
                return ("ingreso_tarjeta", "4.1.01", 0.6)
            else:
                return ("ingreso_otro", "4.1.09", 0.3)
        else:
            # Egresos
            if origen == OrigenTransaccion.TRANSFERENCIA:
                return ("pago_transferencia", "2.1.01", 0.5)
            elif origen == OrigenTransaccion.COMISION_BANCARIA:
                return ("gasto_bancario", "5.3.02", 0.8)
            elif origen == OrigenTransaccion.IMPUESTO:
                return ("impuesto", "5.3.03", 0.7)
            elif origen == OrigenTransaccion.CHEQUE:
                return ("pago_cheque", "1.1.03", 0.5)
            else:
                return ("gasto_otro", "5.2.99", 0.3)

    def detectar_muralla_china(
        self,
        transaccion: TransaccionBancaria,
    ) -> tuple[bool, str | None]:
        """
        Detecta si una transacción corresponde a un MCC bloqueado.

        La "Muralla China" prohíbe ciertos tipos de comercios para
        evitar conflictos de interés en negocios de alquiler de vehículos.

        Args:
            transaccion: Transacción a verificar

        Returns:
            Tupla (es_bloqueado, razon)
        """
        descripcion_lower = (
            transaccion.descripcion_normalizada or
            transaccion.descripcion_original
        ).lower()

        # Solo aplica a gastos (débitos)
        if transaccion.tipo != TipoTransaccion.DEBITO:
            return (False, None)

        # Verificar MCCs bloqueados
        for categoria, info in MCC_BLOQUEADOS.items():
            palabras_clave = info.get("palabras_clave", [])
            for palabra in palabras_clave:
                if palabra.lower() in descripcion_lower:
                    return (True, f"MCC bloqueado: {categoria} - {info.get('razon', '')}")

        return (False, None)

    def sugerir_contraparte(
        self,
        transaccion: TransaccionBancaria,
    ) -> str | None:
        """
        Intenta sugerir la contraparte si no está definida.

        Args:
            transaccion: Transacción

        Returns:
            Nombre sugerido de contraparte o None
        """
        if transaccion.contraparte_nombre:
            return transaccion.contraparte_nombre

        descripcion = transaccion.descripcion_normalizada or transaccion.descripcion_original

        # Patrones comunes de empresas conocidas
        empresas_conocidas = {
            r"datafast": "DATAFAST S.A.",
            r"medianet": "MEDIANET S.A.",
            r"cnt": "CNT EP",
            r"claro": "CONECEL S.A. (CLARO)",
            r"movistar": "OTECEL S.A. (MOVISTAR)",
            r"iess": "IESS",
            r"sri": "SERVICIO DE RENTAS INTERNAS",
            r"pichincha": "BANCO PICHINCHA",
            r"produbanco": "PRODUBANCO",
            r"primax": "PRIMAX COMERCIAL DEL ECUADOR",
        }

        desc_lower = descripcion.lower()
        for patron, empresa in empresas_conocidas.items():
            if patron in desc_lower:
                return empresa

        return None


def normalizar_transacciones(
    transacciones: list[TransaccionBancaria],
) -> list[TransaccionBancaria]:
    """
    Función de conveniencia para normalizar transacciones.

    Args:
        transacciones: Lista de transacciones

    Returns:
        Lista normalizada
    """
    normalizer = TransactionNormalizer()
    return normalizer.normalizar_lote(transacciones)
