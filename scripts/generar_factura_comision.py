#!/usr/bin/env python3
"""
ECUCONDOR - Generador de Facturas de Comision P2P
Genera, firma y envia una factura electronica al SRI por comisiones de intermediacion.

Uso:
    python scripts/generar_factura_comision.py --base 59.40 --desc "Comisiones P2P Enero 2026"
    python scripts/generar_factura_comision.py --base 35.72 --desc "Comisiones P2P Febrero 2026"
    python scripts/generar_factura_comision.py --base 10.00 --desc "Test" --dry-run
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# Agregar src al path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Cargar variables de .env
from dotenv import dotenv_values

ENV_FILE = Path(__file__).parent.parent / ".env"
env_values = dotenv_values(ENV_FILE)
for key, value in env_values.items():
    if value is not None:
        os.environ[key] = value

# Forzar recarga de settings
from src.config.settings import get_settings
get_settings.cache_clear()

from supabase import create_client
from src.sri.access_key import generar_clave_acceso
from src.sri.client import SRIClient
from src.sri.models import FormaPago, TipoIdentificacion
from src.sri.signer_sri import XAdESSigner
from src.sri.xml_builder import crear_factura_xml

ECUADOR_TZ = timezone(timedelta(hours=-5))


def siguiente_secuencial(supabase, establecimiento: str, punto_emision: str) -> int:
    """Obtiene el siguiente secuencial para facturas."""
    result = (
        supabase.table("comprobantes_electronicos")
        .select("secuencial")
        .eq("tipo_comprobante", "01")
        .eq("establecimiento", establecimiento)
        .eq("punto_emision", punto_emision)
        .order("secuencial", desc=True)
        .limit(50)
        .execute()
    )

    if result.data:
        for row in result.data:
            sec = row["secuencial"]
            if sec.isdigit():
                return int(sec) + 1
    return 1


def main():
    parser = argparse.ArgumentParser(description="Generar factura de comision P2P")
    parser.add_argument("--base", type=float, required=True,
                        help="Base imponible (comision en USD)")
    parser.add_argument("--desc", type=str, required=True,
                        help="Descripcion del servicio")
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo generar XML, no enviar al SRI")
    args = parser.parse_args()

    settings = get_settings()
    supabase = create_client(settings.supabase_url, settings.supabase_key)

    base_imponible = Decimal(str(args.base))
    iva_porcentaje = Decimal(str(settings.iva_porcentaje))
    valor_iva = (base_imponible * iva_porcentaje / Decimal("100")).quantize(Decimal("0.01"))
    total = base_imponible + valor_iva

    fecha_emision = datetime.now(ECUADOR_TZ).date()
    establecimiento = settings.sri_establecimiento
    punto_emision = settings.sri_punto_emision
    secuencial = siguiente_secuencial(supabase, establecimiento, punto_emision)

    ambiente_str = "PRODUCCION" if settings.sri_ambiente == "2" else "PRUEBAS"

    print("=" * 60)
    print("ECUCONDOR - Factura de Comision P2P")
    print("=" * 60)
    print(f"  Ambiente: {ambiente_str}")
    print(f"  Fecha: {fecha_emision}")
    print(f"  Numero: {establecimiento}-{punto_emision}-{secuencial:09d}")
    print(f"  Descripcion: {args.desc}")
    print(f"  Base imponible: ${base_imponible:.2f}")
    print(f"  IVA {iva_porcentaje}%: ${valor_iva:.2f}")
    print(f"  TOTAL: ${total:.2f}")
    if args.dry_run:
        print(f"  MODO: DRY-RUN (no se envia al SRI)")
    print("=" * 60)
    print()

    # Generar clave de acceso
    clave_acceso = generar_clave_acceso(
        fecha_emision=fecha_emision,
        tipo_comprobante="01",
        ruc=settings.sri_ruc,
        ambiente=settings.sri_ambiente,
        establecimiento=establecimiento,
        punto_emision=punto_emision,
        secuencial=secuencial,
        tipo_emision=settings.sri_tipo_emision,
    )
    print(f"Clave de acceso: {clave_acceso}")

    # Generar XML
    print("Construyendo XML...")
    xml_sin_firmar = crear_factura_xml(
        ruc=settings.sri_ruc,
        razon_social=settings.sri_razon_social,
        nombre_comercial=settings.sri_nombre_comercial,
        direccion_matriz=settings.sri_direccion_matriz,
        ambiente=settings.sri_ambiente,
        establecimiento=establecimiento,
        punto_emision=punto_emision,
        secuencial=secuencial,
        clave_acceso=clave_acceso,
        fecha_emision=fecha_emision,
        cliente_tipo_id=TipoIdentificacion.CONSUMIDOR_FINAL,
        cliente_identificacion="9999999999999",
        cliente_razon_social="CONSUMIDOR FINAL",
        obligado_contabilidad=settings.sri_obligado_contabilidad,
        items=[
            {
                "codigo": "SRV001",
                "descripcion": args.desc,
                "cantidad": 1,
                "precio_unitario": float(base_imponible),
                "aplica_iva": True,
                "porcentaje_iva": float(iva_porcentaje),
            }
        ],
        forma_pago=FormaPago.SIN_SISTEMA_FINANCIERO,
        info_adicional={
            "Email": "ecucondor@gmail.com",
        },
    )

    # Firmar
    print(f"Firmando con certificado: {settings.sri_cert_path}")
    signer = XAdESSigner(
        cert_path=settings.sri_cert_path,
        cert_password=settings.sri_cert_password,
    )
    xml_firmado = signer.sign(xml_sin_firmar)
    print("XML firmado correctamente")

    if args.dry_run:
        print()
        print("DRY-RUN: XML generado y firmado correctamente. No se envio al SRI.")
        # Mostrar primeros 500 chars del XML sin firmar
        print()
        print("XML (primeros 500 chars):")
        print(xml_sin_firmar[:500])
        return 0

    # Enviar al SRI
    print(f"Enviando al SRI ({ambiente_str})...")
    client = SRIClient(ambiente=settings.sri_ambiente)

    try:
        resultado_recepcion = client.enviar_comprobante(xml_firmado)

        if resultado_recepcion.estado != "RECIBIDA":
            error_msg = f"SRI rechazo comprobante: {resultado_recepcion.estado}"
            if resultado_recepcion.comprobantes:
                for comp in resultado_recepcion.comprobantes:
                    for msg in comp.get("mensajes", []):
                        error_msg += f" | {msg.get('identificador')}: {msg.get('mensaje')}"
            print(f"ERROR: {error_msg}")
            return 1

        print("Comprobante RECIBIDO por SRI")

        # Consultar autorizacion
        print("Consultando autorizacion...")
        time.sleep(3)
        resultado_auth = client.consultar_autorizacion(clave_acceso)

        numero_autorizacion = None
        fecha_autorizacion = None
        estado_final = "sent"

        if resultado_auth.autorizaciones and len(resultado_auth.autorizaciones) > 0:
            auth = resultado_auth.autorizaciones[0]
            if auth.estado == "AUTORIZADO":
                numero_autorizacion = auth.numero_autorizacion
                fecha_autorizacion = auth.fecha_autorizacion
                estado_final = "authorized"
                print(f"FACTURA AUTORIZADA: {numero_autorizacion}")
            else:
                estado_final = "error"
                error_msg = f"No autorizada: {auth.estado}"
                if auth.mensajes:
                    for msg in auth.mensajes:
                        error_msg += f" | {msg.identificador}: {msg.mensaje}"
                print(f"ADVERTENCIA: {error_msg}")

        # Guardar en BD
        print("Guardando en base de datos...")
        comprobante_data = {
            "tipo_comprobante": "01",
            "establecimiento": establecimiento,
            "punto_emision": punto_emision,
            "secuencial": f"{secuencial:09d}",
            "clave_acceso": clave_acceso,
            "fecha_emision": fecha_emision.isoformat(),
            "cliente_tipo_id": "07",
            "cliente_identificacion": "9999999999999",
            "cliente_razon_social": "CONSUMIDOR FINAL",
            "subtotal_sin_impuestos": float(base_imponible),
            "total_descuento": 0.0,
            "subtotal_15": float(base_imponible),
            "subtotal_0": 0.0,
            "iva": float(valor_iva),
            "importe_total": float(total),
            "estado": estado_final,
            "xml_firmado": xml_firmado,
            "intentos_envio": 1,
            "ultimo_intento_at": datetime.now(ECUADOR_TZ).isoformat(),
        }

        if numero_autorizacion:
            comprobante_data["numero_autorizacion"] = numero_autorizacion
        if fecha_autorizacion:
            comprobante_data["fecha_autorizacion"] = (
                fecha_autorizacion.isoformat()
                if hasattr(fecha_autorizacion, "isoformat")
                else str(fecha_autorizacion)
            )

        response = supabase.table("comprobantes_electronicos").insert(comprobante_data).execute()
        comprobante_id = response.data[0]["id"] if response.data else "?"

        # Resumen final
        numero_factura = f"{establecimiento}-{punto_emision}-{secuencial:09d}"
        print()
        print("=" * 60)
        print("FACTURA GENERADA EXITOSAMENTE")
        print("=" * 60)
        print(f"  Numero: {numero_factura}")
        print(f"  Clave acceso: {clave_acceso}")
        print(f"  Estado: {estado_final.upper()}")
        if numero_autorizacion:
            print(f"  Autorizacion: {numero_autorizacion}")
        print(f"  Base: ${base_imponible:.2f}")
        print(f"  IVA: ${valor_iva:.2f}")
        print(f"  Total: ${total:.2f}")
        print(f"  BD ID: {comprobante_id}")
        print("=" * 60)

        return 0

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
