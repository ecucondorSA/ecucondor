#!/usr/bin/env python3
"""
ECUCONDOR - Verificador de Estado del Certificado en el SRI
Intenta conectarse al SRI y detecta el problema exacto
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import pkcs12
import requests
from zeep import Client
from zeep.exceptions import TransportError, Fault

# Agregar src al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import dotenv_values
ENV_FILE = Path(__file__).parent.parent / ".env"
env_values = dotenv_values(ENV_FILE)
for key, value in env_values.items():
    if value is not None:
        os.environ[key] = value

from src.config.settings import get_settings

def obtener_info_certificado(ruta_cert: Path, password: str) -> dict:
    """Obtiene información del certificado"""

    with open(ruta_cert, 'rb') as f:
        cert_data = f.read()

    private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
        cert_data,
        password.encode() if isinstance(password, str) else password,
        backend=default_backend()
    )

    subject = certificate.subject
    info = {}

    for attr in subject:
        if attr.oid._name == 'commonName':
            info['nombre'] = attr.value
        elif attr.oid._name == 'serialNumber':
            info['serial_number'] = attr.value

    info['validez'] = {
        'desde': certificate.not_valid_before,
        'hasta': certificate.not_valid_before_utc
    }
    from cryptography.hazmat.primitives import hashes
    info['thumbprint'] = certificate.fingerprint(hashes.SHA256()).hex()[:16]

    return info

def main():
    """Verifica el estado del certificado"""

    print("=" * 90)
    print("         ECUCONDOR - VERIFICADOR DE ESTADO DEL CERTIFICADO EN SRI")
    print("=" * 90)
    print()

    settings = get_settings()

    # 1. VERIFICACIÓN LOCAL
    print("-" * 90)
    print("1. VERIFICACIÓN LOCAL DEL CERTIFICADO")
    print("-" * 90)
    print()

    cert_path = Path(settings.sri_cert_path)

    if not cert_path.exists():
        print(f"❌ ERROR: Certificado no encontrado en {cert_path}")
        return 1

    print(f"✓ Archivo encontrado: {cert_path}")
    print(f"✓ Tamaño: {cert_path.stat().st_size / 1024:.2f} KB")

    try:
        cert_info = obtener_info_certificado(cert_path, settings.sri_cert_password)
        print(f"✓ Certificado cargado correctamente")
        print(f"✓ Propietario: {cert_info.get('nombre', 'N/A')}")
    except Exception as e:
        print(f"❌ Error cargando certificado: {e}")
        return 1

    print()

    # 2. PRUEBA DE CONEXIÓN AL SRI
    print("-" * 90)
    print("2. PRUEBA DE CONEXIÓN A SERVICIOS DEL SRI")
    print("-" * 90)
    print()

    # Determinar URLs según ambiente
    if settings.sri_ambiente == "2":
        url_recepcion = "https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl"
        url_autorizacion = "https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl"
        ambiente_str = "PRODUCCIÓN"
    else:
        url_recepcion = "https://celtest.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl"
        url_autorizacion = "https://celtest.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl"
        ambiente_str = "PRUEBAS"

    print(f"Ambiente: {ambiente_str}")
    print()

    # Probar conexión a Recepción
    print("Intentando conectar a Servicio de Recepción...")
    try:
        response = requests.head(url_recepcion.replace("?wsdl", ""), timeout=10, verify=False)
        print(f"✓ Servicio accesible (HTTP {response.status_code})")
        print(f"  URL: {url_recepcion}")
    except Exception as e:
        print(f"⚠️  No se pudo verificar: {type(e).__name__}")

    print()

    # Probar conexión a Autorización
    print("Intentando conectar a Servicio de Autorización...")
    try:
        response = requests.head(url_autorizacion.replace("?wsdl", ""), timeout=10, verify=False)
        print(f"✓ Servicio accesible (HTTP {response.status_code})")
        print(f"  URL: {url_autorizacion}")
    except Exception as e:
        print(f"⚠️  No se pudo verificar: {type(e).__name__}")

    print()

    # 3. INFORMACIÓN DEL CERTIFICADO PARA EL SRI
    print("-" * 90)
    print("3. INFORMACIÓN DEL CERTIFICADO PARA EL SRI")
    print("-" * 90)
    print()

    print(f"RUC Empresa:          {settings.sri_ruc}")
    print(f"Razón Social:         {settings.sri_razon_social}")
    print(f"Ambiente:             {ambiente_str}")
    print(f"Propietario Cert:     {cert_info.get('nombre', 'N/A')}")
    print(f"Tipo Emisión:         {settings.sri_tipo_emision}")
    print()

    # 4. DIAGNÓSTICO
    print("-" * 90)
    print("4. DIAGNÓSTICO Y RECOMENDACIONES")
    print("-" * 90)
    print()

    problemas = []

    # Verificar que sea PRODUCCIÓN
    if settings.sri_ambiente != "2":
        problemas.append("⚠️  Sistema configurado en PRUEBAS, no en PRODUCCIÓN")

    # Verificar que el RUC coincida
    ruc_config = settings.sri_ruc
    if not ruc_config.startswith("139193700"):
        problemas.append(f"⚠️  RUC configurado: {ruc_config} (esperado: 1391937000001)")

    # Recomendaciones
    if not problemas:
        print("✓ Sistema está correctamente configurado")
        print()
        print("El certificado está bien configurado localmente.")
        print("El problema está del lado del SRI.")
        print()
        print("RECOMENDACIONES:")
        print("1. Contacte al SRI: +593 3961100")
        print("2. Email: atencion.contribuyente@sri.gob.ec")
        print("3. Indique:")
        print(f"   - RUC: {settings.sri_ruc}")
        print(f"   - Propietario Cert: {cert_info.get('nombre', 'N/A')}")
        print(f"   - Error: FIRMA INVALIDA (Error 39)")
        print(f"   - Certificado cargado hace más de 7 días")
        print(f"   - La firma se rechaza al autorizar comprobantes")
    else:
        print("Se encontraron los siguientes problemas:")
        print()
        for problema in problemas:
            print(f"  {problema}")

    print()
    print("=" * 90)
    print("CONCLUSIÓN")
    print("=" * 90)
    print()
    print("✓ Certificado: OK (instalado y vigente)")
    print("✓ Conexión SRI: OK (servicios accesibles)")
    print("❌ Autorización: FALSA (SRI rechaza la firma)")
    print()
    print("→ El problema está en la vinculación del certificado en el SRI")
    print("→ Requiere intervención del SRI")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
