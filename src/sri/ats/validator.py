"""
ECUCONDOR - Validador XSD para ATS (Anexo Transaccional Simplificado)
Valida el XML generado contra el esquema oficial del SRI.
"""

from pathlib import Path
from typing import Tuple, List
from lxml import etree

# XSD embebido junto al módulo
XSD_PATH = Path(__file__).parent / "ats.xsd"


def validar_xml(xml_str: str) -> Tuple[bool, List[str]]:
    """
    Valida un XML de ATS contra el XSD oficial del SRI.

    Args:
        xml_str: String con el XML completo del ATS

    Returns:
        Tupla (valido, errores) donde:
        - valido: True si pasa validación XSD
        - errores: Lista de mensajes de error (vacía si válido)
    """
    try:
        xsd_doc = etree.parse(str(XSD_PATH))
        schema = etree.XMLSchema(xsd_doc)
    except Exception as e:
        return False, [f"Error cargando XSD: {e}"]

    try:
        xml_doc = etree.fromstring(xml_str.encode("utf-8"))
    except etree.XMLSyntaxError as e:
        return False, [f"XML mal formado: {e}"]

    valido = schema.validate(xml_doc)
    if valido:
        return True, []

    errores = [str(err) for err in schema.error_log]
    return False, errores
