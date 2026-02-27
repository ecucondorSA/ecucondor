"""
ECUCONDOR - Validadores
Funciones de validación para datos ecuatorianos.
"""

import re
from typing import Literal


def validar_ruc(ruc: str) -> tuple[bool, str]:
    """
    Valida un RUC ecuatoriano.

    Args:
        ruc: Número de RUC a validar

    Returns:
        Tupla (es_válido, mensaje)
    """
    # Limpiar espacios
    ruc = ruc.strip()

    # Validar longitud
    if len(ruc) != 13:
        return False, "El RUC debe tener exactamente 13 dígitos"

    # Validar que sean solo números
    if not ruc.isdigit():
        return False, "El RUC debe contener solo dígitos"

    # Validar provincia (primeros 2 dígitos)
    provincia = int(ruc[:2])
    if provincia < 1 or provincia > 24:
        if provincia not in [30]:  # 30 para extranjeros
            return False, f"Código de provincia inválido: {provincia}"

    # Validar tercer dígito (tipo de contribuyente)
    tercer_digito = int(ruc[2])

    if tercer_digito < 6:
        # Persona natural: validar como cédula
        if not _validar_modulo_10(ruc[:10]):
            return False, "Dígito verificador de cédula inválido"
    elif tercer_digito == 6:
        # Entidad pública: validar módulo 11
        if not _validar_modulo_11_ruc(ruc[:9], int(ruc[9])):
            return False, "Dígito verificador de entidad pública inválido"
    elif tercer_digito == 9:
        # Persona jurídica: validar módulo 11
        if not _validar_modulo_11_ruc(ruc[:9], int(ruc[9])):
            return False, "Dígito verificador de persona jurídica inválido"
    else:
        return False, f"Tercer dígito inválido: {tercer_digito}"

    # Validar que termine en 001
    if not ruc.endswith("001"):
        return False, "El RUC debe terminar en 001"

    return True, "RUC válido"


def validar_cedula(cedula: str) -> tuple[bool, str]:
    """
    Valida una cédula ecuatoriana.

    Args:
        cedula: Número de cédula a validar

    Returns:
        Tupla (es_válido, mensaje)
    """
    cedula = cedula.strip()

    if len(cedula) != 10:
        return False, "La cédula debe tener exactamente 10 dígitos"

    if not cedula.isdigit():
        return False, "La cédula debe contener solo dígitos"

    # Validar provincia
    provincia = int(cedula[:2])
    if provincia < 1 or provincia > 24:
        if provincia != 30:
            return False, f"Código de provincia inválido: {provincia}"

    # Validar tercer dígito
    tercer_digito = int(cedula[2])
    if tercer_digito > 5:
        return False, "Tercer dígito debe ser menor a 6 para cédulas"

    # Validar módulo 10
    if not _validar_modulo_10(cedula):
        return False, "Dígito verificador inválido"

    return True, "Cédula válida"


def _validar_modulo_10(numero: str) -> bool:
    """Valida el dígito verificador usando módulo 10 (algoritmo de Luhn)."""
    coeficientes = [2, 1, 2, 1, 2, 1, 2, 1, 2]
    suma = 0

    for i, coef in enumerate(coeficientes):
        valor = int(numero[i]) * coef
        if valor > 9:
            valor -= 9
        suma += valor

    residuo = suma % 10
    digito_verificador = 0 if residuo == 0 else 10 - residuo

    return digito_verificador == int(numero[9])


def _validar_modulo_11_ruc(base: str, digito_verificador: int) -> bool:
    """Valida el dígito verificador usando módulo 11 para RUC."""
    coeficientes = [4, 3, 2, 7, 6, 5, 4, 3, 2]
    suma = 0

    for i, coef in enumerate(coeficientes):
        suma += int(base[i]) * coef

    residuo = suma % 11
    resultado = 11 - residuo if residuo != 0 else 0

    return resultado == digito_verificador


def validar_email(email: str) -> tuple[bool, str]:
    """
    Valida un email.

    Args:
        email: Email a validar

    Returns:
        Tupla (es_válido, mensaje)
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

    if re.match(pattern, email):
        return True, "Email válido"
    else:
        return False, "Formato de email inválido"


def validar_telefono(telefono: str) -> tuple[bool, str]:
    """
    Valida un número de teléfono ecuatoriano.

    Args:
        telefono: Número a validar

    Returns:
        Tupla (es_válido, mensaje)
    """
    # Limpiar caracteres no numéricos
    solo_numeros = re.sub(r'\D', '', telefono)

    # Celulares: 10 dígitos comenzando con 09
    if len(solo_numeros) == 10 and solo_numeros.startswith('09'):
        return True, "Teléfono celular válido"

    # Fijos: 9 dígitos comenzando con 02-07
    if len(solo_numeros) == 9 and solo_numeros[0] == '0' and solo_numeros[1] in '234567':
        return True, "Teléfono fijo válido"

    # Con código de país +593
    if len(solo_numeros) == 12 and solo_numeros.startswith('593'):
        return True, "Teléfono con código de país válido"

    return False, "Formato de teléfono inválido"


def determinar_tipo_identificacion(identificacion: str) -> Literal["04", "05", "06", "07"]:
    """
    Determina el tipo de identificación basado en el formato.

    Args:
        identificacion: Número de identificación

    Returns:
        Código SRI del tipo de identificación:
        - "04": RUC
        - "05": Cédula
        - "06": Pasaporte
        - "07": Consumidor Final
    """
    identificacion = identificacion.strip()

    # Consumidor final
    if identificacion == "9999999999999":
        return "07"

    # RUC (13 dígitos terminando en 001)
    if len(identificacion) == 13 and identificacion.isdigit():
        return "04"

    # Cédula (10 dígitos)
    if len(identificacion) == 10 and identificacion.isdigit():
        return "05"

    # Pasaporte (cualquier otro formato)
    return "06"


def formatear_monto(monto: float | str, decimales: int = 2) -> str:
    """
    Formatea un monto con el número especificado de decimales.

    Args:
        monto: Monto a formatear
        decimales: Número de decimales

    Returns:
        Monto formateado como string
    """
    if isinstance(monto, str):
        monto = float(monto)
    return f"{monto:.{decimales}f}"


def limpiar_texto_xml(texto: str) -> str:
    """
    Limpia un texto para uso seguro en XML.

    Remueve caracteres que pueden causar problemas en el XML del SRI.

    Args:
        texto: Texto a limpiar

    Returns:
        Texto limpio
    """
    if not texto:
        return ""

    # Reemplazar caracteres problemáticos
    replacements = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&apos;',
        '\x00': '',  # Null
        '\x0b': '',  # Vertical tab
        '\x0c': '',  # Form feed
    }

    for char, replacement in replacements.items():
        texto = texto.replace(char, replacement)

    # Remover caracteres de control excepto tab, newline, carriage return
    texto = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', texto)

    return texto.strip()
