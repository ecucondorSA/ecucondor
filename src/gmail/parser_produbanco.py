"""
ECUCONDOR - Parser de emails de Produbanco
Extrae datos de depósitos desde el HTML de notificaciones de Produbanco.

Formatos soportados:
- "Transferencia Recibida en Produbanco" (interbancaria)
- "Transferencia acreditada Produbanco" (interna)
- "Notificación Transferencia Acreditada Produbanco" (variante interna)

Estructura HTML (ambos tipos):
    <STRONG>Enviada por:</STRONG> NOMBRE COMPLETO<BR>
    <STRONG>Banco Origen:</STRONG> BANCO XYZ<BR>  (o Banco Beneficiario)
    <STRONG>Beneficiario:</STRONG> ECUCONDOR...<BR>
    <STRONG>Cuenta Beneficiario:</STRONG> XXXXXX70809<BR>
    <STRONG>Monto:</STRONG> $27.00<BR>
    <STRONG>Descripción:</STRONG> texto libre<BR>
    <STRONG>Referencia:</STRONG> 27058674
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


# Remitentes a ignorar (transferencias propias, no P2P)
REMITENTES_IGNORAR = [
    "MOSQUERA BORJA REINA SHAKIRA",
    "ECUCONDOR",
]


@dataclass
class DepositoInfo:
    """Datos extraídos de un email de depósito Produbanco."""

    gmail_message_id: str
    fecha: date
    monto: Decimal
    nombre_remitente: str
    identificacion_remitente: str | None = None
    referencia: str | None = None
    descripcion: str | None = None
    banco_origen: str | None = None


def parsear_deposito(
    html_body: str, subject: str, message_id: str
) -> DepositoInfo | None:
    """
    Parsea el HTML de un email de Produbanco y extrae los datos del depósito.

    Args:
        html_body: Contenido HTML del email
        subject: Subject del email
        message_id: ID del mensaje en Gmail

    Returns:
        DepositoInfo con los datos extraídos, o None si no se pudo parsear
        o si es una transferencia propia a ignorar
    """
    # Extraer monto
    monto = _extraer_monto(html_body)
    if monto is None:
        return None

    # Extraer nombre del remitente
    nombre = _extraer_campo(html_body, "Enviada por")
    if not nombre:
        nombre = _extraer_campo(html_body, "Ordenante")
    if not nombre:
        return None

    # Verificar si es transferencia propia
    nombre_upper = nombre.upper().strip()
    for ignorar in REMITENTES_IGNORAR:
        if ignorar in nombre_upper:
            return None

    # Extraer fecha
    fecha = _extraer_fecha(html_body)
    if fecha is None:
        fecha = date.today()

    # Extraer otros campos
    referencia = _extraer_campo(html_body, "Referencia")
    descripcion = _extraer_campo(html_body, r"Descripci[oó]n")
    banco_origen = _extraer_campo(html_body, "Banco Origen")
    if not banco_origen:
        banco_origen = _extraer_campo(html_body, "Banco Beneficiario")

    return DepositoInfo(
        gmail_message_id=message_id,
        fecha=fecha,
        monto=monto,
        nombre_remitente=nombre.strip(),
        referencia=referencia.strip() if referencia else None,
        descripcion=descripcion.strip() if descripcion else None,
        banco_origen=banco_origen.strip() if banco_origen else None,
    )


def _extraer_monto(html: str) -> Decimal | None:
    """Extrae el monto del depósito del HTML."""
    # Patrón: <STRONG>Monto:</STRONG> $27.00
    # Puede tener espacios, newlines, tags entre medio
    pattern = r"Monto:\s*</\s*(?:STRONG|strong|b|B)\s*>\s*\$?\s*([\d,]+\.?\d*)"
    match = re.search(pattern, html, re.IGNORECASE)
    if match:
        monto_str = match.group(1).replace(",", "")
        try:
            return Decimal(monto_str)
        except InvalidOperation:
            return None

    # Fallback: buscar patrón más flexible
    pattern2 = r"Monto[:\s]*\$\s*([\d,]+\.?\d*)"
    match2 = re.search(pattern2, html, re.IGNORECASE)
    if match2:
        monto_str = match2.group(1).replace(",", "")
        try:
            return Decimal(monto_str)
        except InvalidOperation:
            return None

    return None


def _extraer_campo(html: str, campo: str) -> str | None:
    """
    Extrae el valor de un campo del HTML de Produbanco.

    Formato: <STRONG>Campo:</STRONG> VALOR<BR>
    """
    # Patrón flexible para extraer valor después de </STRONG> hasta <BR>, </P>, </FONT>, \n o fin
    pattern = (
        rf"{campo}:\s*</\s*(?:STRONG|strong|b|B)\s*>\s*"
        r"(.*?)"
        r"(?:<\s*(?:BR|br|/P|/p|/FONT|/font)\s*/?\s*>|\n|$)"
    )
    match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
    if match:
        # Limpiar tags HTML del valor
        valor = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        if valor:
            return valor

    return None


def _extraer_fecha(html: str) -> date | None:
    """Extrae la fecha del email de Produbanco."""
    # Formato 1: 07/enero/2026 09:42
    pattern1 = r"Fecha y Hora:\s*(\d{1,2})/(\w+)/(\d{4})"
    match1 = re.search(pattern1, html, re.IGNORECASE)
    if match1:
        dia = int(match1.group(1))
        mes_str = match1.group(2).lower()
        anio = int(match1.group(3))
        mes = _mes_a_numero(mes_str)
        if mes:
            try:
                return date(anio, mes, dia)
            except ValueError:
                pass

    # Formato 2: 12/18/2025 14:00:55 (MM/DD/YYYY)
    pattern2 = r"Fecha y Hora:\s*(\d{2})/(\d{2})/(\d{4})"
    match2 = re.search(pattern2, html, re.IGNORECASE)
    if match2:
        mes = int(match2.group(1))
        dia = int(match2.group(2))
        anio = int(match2.group(3))
        try:
            return date(anio, mes, dia)
        except ValueError:
            pass

    return None


MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def _mes_a_numero(mes_str: str) -> int | None:
    """Convierte nombre de mes en español a número."""
    return MESES.get(mes_str.lower())
