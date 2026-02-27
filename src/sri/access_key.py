"""
ECUCONDOR - Generador de Clave de Acceso SRI
Implementa el algoritmo Módulo 11 para generar claves de 49 dígitos.

Estructura de la Clave de Acceso (49 dígitos):
- Posición 1-8:   Fecha de emisión (ddmmaaaa)
- Posición 9-10:  Tipo de comprobante (01=Factura, 04=NC, 07=Retención)
- Posición 11-23: RUC del emisor (13 dígitos)
- Posición 24:    Tipo de ambiente (1=Pruebas, 2=Producción)
- Posición 25-27: Establecimiento (001)
- Posición 28-30: Punto de emisión (001)
- Posición 31-39: Secuencial (9 dígitos)
- Posición 40-47: Código numérico aleatorio (8 dígitos)
- Posición 48:    Tipo de emisión (1=Normal)
- Posición 49:    Dígito verificador (Módulo 11)
"""

import random
from datetime import date

from src.sri.models import TipoComprobante


def calcular_digito_verificador(cadena: str) -> str:
    """
    Calcula el dígito verificador usando el algoritmo Módulo 11.

    El algoritmo:
    1. Recorre la cadena de derecha a izquierda
    2. Multiplica cada dígito por factores cíclicos [2, 3, 4, 5, 6, 7]
    3. Suma todos los productos
    4. Calcula el residuo de la división por 11
    5. Resta el residuo de 11 para obtener el dígito verificador
    6. Casos especiales: si el resultado es 11 -> 0, si es 10 -> 1

    Args:
        cadena: String de 48 dígitos (la clave sin el dígito verificador)

    Returns:
        Dígito verificador como string de un carácter

    Raises:
        ValueError: Si la cadena no tiene 48 dígitos o contiene no-dígitos
    """
    if len(cadena) != 48:
        raise ValueError(f"La cadena debe tener 48 dígitos, tiene {len(cadena)}")

    if not cadena.isdigit():
        raise ValueError("La cadena debe contener solo dígitos")

    # Factores cíclicos del algoritmo Módulo 11
    factores = [2, 3, 4, 5, 6, 7]

    # Sumar productos de derecha a izquierda
    suma = 0
    for i, digito in enumerate(reversed(cadena)):
        factor = factores[i % len(factores)]
        suma += int(digito) * factor

    # Calcular dígito verificador
    residuo = suma % 11
    resultado = 11 - residuo

    # Casos especiales
    if resultado == 11:
        return "0"
    elif resultado == 10:
        return "1"
    else:
        return str(resultado)


def generar_clave_acceso(
    fecha_emision: date,
    tipo_comprobante: TipoComprobante | str,
    ruc: str,
    ambiente: str,
    establecimiento: str,
    punto_emision: str,
    secuencial: int | str,
    codigo_numerico: str | None = None,
    tipo_emision: str = "1",
) -> str:
    """
    Genera una clave de acceso de 49 dígitos para comprobantes electrónicos del SRI.

    Args:
        fecha_emision: Fecha de emisión del comprobante
        tipo_comprobante: Código del tipo de comprobante (01, 04, 07, etc.)
        ruc: RUC del emisor (13 dígitos)
        ambiente: Tipo de ambiente (1=Pruebas, 2=Producción)
        establecimiento: Código del establecimiento (3 dígitos)
        punto_emision: Código del punto de emisión (3 dígitos)
        secuencial: Número secuencial del comprobante
        codigo_numerico: Código numérico aleatorio (8 dígitos). Si es None, se genera.
        tipo_emision: Tipo de emisión (1=Normal)

    Returns:
        Clave de acceso de 49 dígitos

    Raises:
        ValueError: Si algún parámetro no cumple con el formato requerido

    Example:
        >>> clave = generar_clave_acceso(
        ...     fecha_emision=date(2024, 3, 15),
        ...     tipo_comprobante=TipoComprobante.FACTURA,
        ...     ruc="1234567890001",
        ...     ambiente="1",
        ...     establecimiento="001",
        ...     punto_emision="001",
        ...     secuencial=1
        ... )
        >>> len(clave)
        49
    """
    # Validaciones
    if isinstance(tipo_comprobante, TipoComprobante):
        tipo_comprobante = tipo_comprobante.value

    if len(ruc) != 13 or not ruc.isdigit():
        raise ValueError(f"RUC inválido: {ruc}. Debe tener 13 dígitos numéricos.")

    if ambiente not in ("1", "2"):
        raise ValueError(f"Ambiente inválido: {ambiente}. Debe ser '1' o '2'.")

    if len(establecimiento) != 3 or not establecimiento.isdigit():
        raise ValueError(f"Establecimiento inválido: {establecimiento}")

    if len(punto_emision) != 3 or not punto_emision.isdigit():
        raise ValueError(f"Punto de emisión inválido: {punto_emision}")

    if tipo_emision != "1":
        raise ValueError(f"Tipo de emisión inválido: {tipo_emision}")

    # Convertir secuencial a string con padding
    if isinstance(secuencial, int):
        secuencial_str = str(secuencial).zfill(9)
    else:
        secuencial_str = secuencial.zfill(9)

    if len(secuencial_str) != 9 or not secuencial_str.isdigit():
        raise ValueError(f"Secuencial inválido: {secuencial}")

    # Generar código numérico aleatorio si no se proporciona
    if codigo_numerico is None:
        codigo_numerico = str(random.randint(10000000, 99999999))
    else:
        codigo_numerico = codigo_numerico.zfill(8)

    if len(codigo_numerico) != 8 or not codigo_numerico.isdigit():
        raise ValueError(f"Código numérico inválido: {codigo_numerico}")

    # Construir los primeros 48 dígitos
    clave_base = (
        fecha_emision.strftime("%d%m%Y")  # 8 dígitos: ddmmaaaa
        + tipo_comprobante.zfill(2)        # 2 dígitos
        + ruc                               # 13 dígitos
        + ambiente                          # 1 dígito
        + establecimiento                   # 3 dígitos
        + punto_emision                     # 3 dígitos
        + secuencial_str                    # 9 dígitos
        + codigo_numerico                   # 8 dígitos
        + tipo_emision                      # 1 dígito
    )

    # Verificar longitud
    if len(clave_base) != 48:
        raise ValueError(f"Error interno: clave base tiene {len(clave_base)} dígitos")

    # Calcular dígito verificador
    digito_verificador = calcular_digito_verificador(clave_base)

    return clave_base + digito_verificador


def validar_clave_acceso(clave: str) -> bool:
    """
    Valida una clave de acceso verificando su dígito verificador.

    Args:
        clave: Clave de acceso de 49 dígitos

    Returns:
        True si la clave es válida, False en caso contrario
    """
    if len(clave) != 49:
        return False

    if not clave.isdigit():
        return False

    # Extraer base y dígito verificador
    clave_base = clave[:48]
    digito_esperado = clave[48]

    # Calcular y comparar
    digito_calculado = calcular_digito_verificador(clave_base)

    return digito_calculado == digito_esperado


def extraer_datos_clave(clave: str) -> dict:
    """
    Extrae los datos contenidos en una clave de acceso.

    Args:
        clave: Clave de acceso de 49 dígitos

    Returns:
        Diccionario con los componentes de la clave

    Raises:
        ValueError: Si la clave no tiene el formato correcto
    """
    if not validar_clave_acceso(clave):
        raise ValueError("Clave de acceso inválida")

    return {
        "fecha_emision": f"{clave[0:2]}/{clave[2:4]}/{clave[4:8]}",
        "tipo_comprobante": clave[8:10],
        "ruc": clave[10:23],
        "ambiente": "Pruebas" if clave[23] == "1" else "Producción",
        "establecimiento": clave[24:27],
        "punto_emision": clave[27:30],
        "secuencial": clave[30:39],
        "codigo_numerico": clave[39:47],
        "tipo_emision": clave[47],
        "digito_verificador": clave[48],
    }


# Mapeo de códigos de tipo de comprobante a nombres
NOMBRES_COMPROBANTE = {
    "01": "Factura",
    "03": "Liquidación de Compra",
    "04": "Nota de Crédito",
    "05": "Nota de Débito",
    "06": "Guía de Remisión",
    "07": "Comprobante de Retención",
}


def describir_clave(clave: str) -> str:
    """
    Genera una descripción legible de una clave de acceso.

    Args:
        clave: Clave de acceso de 49 dígitos

    Returns:
        Descripción formateada de la clave
    """
    datos = extraer_datos_clave(clave)
    tipo = NOMBRES_COMPROBANTE.get(datos["tipo_comprobante"], "Desconocido")

    return (
        f"Tipo: {tipo}\n"
        f"Fecha: {datos['fecha_emision']}\n"
        f"RUC Emisor: {datos['ruc']}\n"
        f"Ambiente: {datos['ambiente']}\n"
        f"Número: {datos['establecimiento']}-{datos['punto_emision']}-{datos['secuencial']}"
    )
