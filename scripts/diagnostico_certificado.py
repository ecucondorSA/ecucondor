#!/usr/bin/env python3
"""
ECUCONDOR - Diagnóstico Completo de Certificado Digital
Verifica configuración, validez y vinculación del certificado SRI
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
import pytz

# Agregar src al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import dotenv_values
ENV_FILE = Path(__file__).parent.parent / ".env"
env_values = dotenv_values(ENV_FILE)
for key, value in env_values.items():
    if value is not None:
        os.environ[key] = value

from src.config.settings import get_settings
from supabase import create_client

def analizar_certificado_p12(ruta_cert: Path, password: str) -> dict:
    """Analiza un certificado PKCS#12"""

    info = {
        'archivo': str(ruta_cert),
        'existe': ruta_cert.exists(),
        'tamaño_kb': 0,
        'valido': False,
        'tipo': 'PKCS#12 (.p12)',
        'error': None,
        'propietario': {},
        'validez': {},
        'uso': {}
    }

    if not ruta_cert.exists():
        info['error'] = 'Archivo no encontrado'
        return info

    info['tamaño_kb'] = ruta_cert.stat().st_size / 1024

    try:
        with open(ruta_cert, 'rb') as f:
            cert_data = f.read()

        # Cargar certificado PKCS#12
        private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
            cert_data,
            password.encode() if isinstance(password, str) else password,
            backend=default_backend()
        )

        if not certificate:
            info['error'] = 'No se encontró certificado en el archivo'
            return info

        info['valido'] = True

        # Información del propietario (Subject)
        subject = certificate.subject
        info['propietario'] = {
            'nombre': None,
            'organizacion': None,
            'pais': None,
            'ruc': None,
            'email': None,
            'raw': str(subject)
        }

        for attr in subject:
            name = attr.oid._name
            value = attr.value

            if name == 'commonName':
                info['propietario']['nombre'] = value
            elif name == 'organizationName':
                info['propietario']['organizacion'] = value
            elif name == 'countryName':
                info['propietario']['pais'] = value
            elif name == 'emailAddress':
                info['propietario']['email'] = value

        # Información del emisor (Issuer)
        issuer = certificate.issuer
        info['emisor'] = {
            'nombre': None,
            'organizacion': None,
            'raw': str(issuer)
        }

        for attr in issuer:
            name = attr.oid._name
            value = attr.value

            if name == 'commonName':
                info['emisor']['nombre'] = value
            elif name == 'organizationName':
                info['emisor']['organizacion'] = value

        # Validez
        not_valid_before = certificate.not_valid_before
        not_valid_after = certificate.not_valid_after

        # Convertir a UTC
        tz_utc = pytz.UTC
        ahora = datetime.now(tz_utc)

        if isinstance(not_valid_before, datetime):
            not_valid_before = not_valid_before.replace(tzinfo=tz_utc)
        if isinstance(not_valid_after, datetime):
            not_valid_after = not_valid_after.replace(tzinfo=tz_utc)

        info['validez'] = {
            'valido_desde': not_valid_before.strftime('%d/%m/%Y %H:%M:%S UTC') if not_valid_before else None,
            'valido_hasta': not_valid_after.strftime('%d/%m/%Y %H:%M:%S UTC') if not_valid_after else None,
            'estado': 'VIGENTE' if ahora < not_valid_after else 'EXPIRADO',
            'dias_restantes': (not_valid_after - ahora).days if not_valid_after > ahora else 0
        }

        # Número de serie
        info['numero_serie'] = str(certificate.serial_number)

        # Extensiones (usos permitidos)
        try:
            key_usage = certificate.extensions.get_extension_for_class(x509.KeyUsage)
            info['uso'] = {
                'firma_digital': key_usage.value.digital_signature,
                'repudio': key_usage.value.content_commitment,
                'cifrado_clave': key_usage.value.key_encipherment,
                'acuerdo_clave': key_usage.value.key_agreement
            }
        except:
            pass

        # Información técnica
        try:
            algo_firma = certificate.signature_algorithm_oid._name
        except:
            algo_firma = 'Desconocido'

        info['tecnico'] = {
            'algoritmo_firma': algo_firma,
            'algoritmo_clave_publica': 'RSA' if private_key else 'Desconocido'
        }

    except Exception as e:
        info['error'] = str(e)

    return info


def main():
    """Ejecuta diagnóstico completo"""

    print("=" * 90)
    print("         ECUCONDOR SAS - DIAGNÓSTICO DE CERTIFICADO DIGITAL")
    print("=" * 90)
    print()

    settings = get_settings()

    # 1. INFORMACIÓN DE CONFIGURACIÓN
    print("-" * 90)
    print("1. INFORMACIÓN DE CONFIGURACIÓN DEL SISTEMA")
    print("-" * 90)
    print()
    print(f"  RUC Empresa (SRI):           {settings.sri_ruc}")
    print(f"  Razón Social:                {settings.sri_razon_social}")
    print(f"  Nombre Comercial:            {settings.sri_nombre_comercial}")
    print(f"  Ambiente:                    {'PRODUCCIÓN' if settings.sri_ambiente == '2' else 'PRUEBAS'}")
    print(f"  Ruta del Certificado:        {settings.sri_cert_path}")
    print(f"  Certificado Configurado:     {'SÍ' if Path(settings.sri_cert_path).exists() else 'NO'}")
    print()

    # 2. ANÁLISIS DEL CERTIFICADO
    print("-" * 90)
    print("2. ANÁLISIS DEL CERTIFICADO DIGITAL (.P12)")
    print("-" * 90)
    print()

    if not Path(settings.sri_cert_path).exists():
        print(f"  ⚠️  ERROR: No se encontró certificado en: {settings.sri_cert_path}")
        return 1

    cert_info = analizar_certificado_p12(
        Path(settings.sri_cert_path),
        settings.sri_cert_password
    )

    if not cert_info['valido']:
        print(f"  ❌ ERROR: {cert_info['error']}")
        return 1

    print(f"  ✓ Archivo:                   {cert_info['archivo']}")
    print(f"  ✓ Tamaño:                    {cert_info['tamaño_kb']:.2f} KB")
    print(f"  ✓ Tipo:                      {cert_info['tipo']}")
    print()

    # 3. INFORMACIÓN DEL PROPIETARIO
    print("-" * 90)
    print("3. IDENTIFICACIÓN DEL PROPIETARIO DEL CERTIFICADO")
    print("-" * 90)
    print()
    print(f"  Nombre Completo:             {cert_info['propietario']['nombre']}")
    print(f"  Organización:                {cert_info['propietario']['organizacion']}")
    print(f"  País:                        {cert_info['propietario']['pais']}")
    print(f"  Email:                       {cert_info['propietario']['email']}")
    print(f"  Número de Serie:             {cert_info['numero_serie']}")
    print()

    # Determinar si es personal o de empresa
    propietario_texto = (cert_info['propietario']['nombre'] or '').upper()
    if 'ECUCONDOR' in propietario_texto or 'SAS' in propietario_texto:
        tipo_cert = "CERTIFICADO DE EMPRESA (ECUCONDOR SAS)"
        color = "✓"
    elif propietario_texto and any(palabra in propietario_texto for palabra in ['PERSONA', 'NATURAL', 'INDIVIDUAL']):
        tipo_cert = "CERTIFICADO DE PERSONA NATURAL"
        color = "⚠️"
    else:
        tipo_cert = "CERTIFICADO PERSONAL (No es de ECUCONDOR)"
        color = "⚠️"

    print(f"  {color} TIPO DE CERTIFICADO:       {tipo_cert}")
    print()

    # 4. INFORMACIÓN DEL EMISOR
    print("-" * 90)
    print("4. AUTORIDAD CERTIFICADORA (EMISOR)")
    print("-" * 90)
    print()
    print(f"  Nombre:                      {cert_info['emisor']['nombre']}")
    print(f"  Organización:                {cert_info['emisor']['organizacion']}")
    print()

    # 5. VALIDEZ DEL CERTIFICADO
    print("-" * 90)
    print("5. PERÍODO DE VALIDEZ")
    print("-" * 90)
    print()
    print(f"  Válido Desde:                {cert_info['validez']['valido_desde']}")
    print(f"  Válido Hasta:                {cert_info['validez']['valido_hasta']}")
    print(f"  Estado:                      {cert_info['validez']['estado']}")

    if cert_info['validez']['estado'] == 'EXPIRADO':
        print(f"  ❌ EL CERTIFICADO HA EXPIRADO")
    elif cert_info['validez']['dias_restantes'] < 30:
        print(f"  ⚠️  Días restantes:           {cert_info['validez']['dias_restantes']} (Por expirar)")
    else:
        print(f"  ✓ Días restantes:            {cert_info['validez']['dias_restantes']}")

    print()

    # 6. USOS PERMITIDOS
    print("-" * 90)
    print("6. USOS PERMITIDOS DEL CERTIFICADO")
    print("-" * 90)
    print()
    if cert_info['uso']:
        print(f"  Firma Digital:               {'SÍ' if cert_info['uso']['firma_digital'] else 'NO'}")
        print(f"  No Repudio:                  {'SÍ' if cert_info['uso']['repudio'] else 'NO'}")
        print(f"  Cifrado de Clave:            {'SÍ' if cert_info['uso']['cifrado_clave'] else 'NO'}")
        print(f"  Acuerdo de Clave:            {'SÍ' if cert_info['uso']['acuerdo_clave'] else 'NO'}")
    print()

    # 7. INFORMACIÓN TÉCNICA
    print("-" * 90)
    print("7. INFORMACIÓN TÉCNICA")
    print("-" * 90)
    print()
    print(f"  Algoritmo de Firma:          {cert_info['tecnico']['algoritmo_firma']}")
    print(f"  Algoritmo de Clave Pública:  {cert_info['tecnico']['algoritmo_clave_publica']}")
    print()

    # 8. ESTADO EN EL SRI
    print("-" * 90)
    print("8. ESTADO DE VINCULACIÓN EN EL SRI")
    print("-" * 90)
    print()

    try:
        supabase = create_client(settings.supabase_url, settings.supabase_key)

        # Verificar si hay comprobantes autorizados
        resultado = supabase.table('comprobantes_electronicos').select('count').execute()

        # Consultar estado en SRI (requiere verificación manual)
        print(f"  Portal SRI:                  https://srienlinea.sri.gob.ec")
        print(f"  Ir a:                        Certificación Electrónica > Certificados")
        print(f"  Estado Esperado:             VIGENTE y VINCULADO")
        print()

        # Verificar comprobantes
        comprobantes = supabase.table('comprobantes_electronicos').select('id,estado,numero_autorizacion').execute()
        if comprobantes.data:
            autorizados = sum(1 for c in comprobantes.data if c.get('estado') == 'authorized')
            print(f"  Comprobantes en BD:          {len(comprobantes.data)}")
            print(f"  Comprobantes Autorizados:    {autorizados}")

    except Exception as e:
        print(f"  ⚠️  Error consultando BD: {e}")

    print()

    # 9. RECOMENDACIONES
    print("-" * 90)
    print("9. RECOMENDACIONES")
    print("-" * 90)
    print()

    recomendaciones = []

    if 'ECUCONDOR' not in propietario_texto and 'SAS' not in propietario_texto:
        recomendaciones.append("⚠️  El certificado NO es de ECUCONDOR SAS")
        recomendaciones.append("   → Para emitir comprobantes a nombre de ECUCONDOR SAS debe usar")
        recomendaciones.append("     el certificado registrado con el RUC 1793216659001")

    if cert_info['validez']['estado'] == 'EXPIRADO':
        recomendaciones.append("❌ El certificado está EXPIRADO")
        recomendaciones.append("   → Solicite uno nuevo a su autoridad certificadora")
    elif cert_info['validez']['dias_restantes'] < 30:
        recomendaciones.append("⚠️  El certificado está por expirar")
        recomendaciones.append(f"   → Quedan {cert_info['validez']['dias_restantes']} días")
        recomendaciones.append("   → Solicite renovación cuanto antes")
    else:
        recomendaciones.append("✓ Certificado vigente y válido para usar")

    if cert_info['uso']['firma_digital']:
        recomendaciones.append("✓ Certificado habilitado para firma digital (XAdES)")
    else:
        recomendaciones.append("❌ Certificado NO está habilitado para firma digital")

    for rec in recomendaciones:
        print(f"  {rec}")

    print()
    print("=" * 90)
    print("  PRÓXIMOS PASOS:")
    print("=" * 90)
    print()
    print("  1. Confirme que el certificado pertenece a ECUCONDOR SAS (RUC 1793216659001)")
    print("  2. Verifique que está vinculado en el Portal SRI")
    print("  3. Ejecute: python scripts/generar_factura_prueba.py")
    print("  4. Verifique que la factura sea autorizada por el SRI")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
