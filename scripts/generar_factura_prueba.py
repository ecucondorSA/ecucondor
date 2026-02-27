#!/usr/bin/env python3
"""
ECUCONDOR - Script para generar primera factura de prueba
Genera, firma y envía una factura al SRI ambiente de pruebas.
"""

import os
import sys
from pathlib import Path
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

# Agregar src al path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Cargar variables de .env directamente (ignorando variables del sistema)
from dotenv import dotenv_values

ENV_FILE = Path(__file__).parent.parent / ".env"

# Cargar valores del .env y forzar en os.environ (sobrescribiendo sistema)
env_values = dotenv_values(ENV_FILE)
for key, value in env_values.items():
    if value is not None:
        os.environ[key] = value

# Forzar recarga de settings (limpiar cache)
from src.config.settings import get_settings
get_settings.cache_clear()

from src.sri.models import (
    InfoTributaria,
    InfoFactura,
    DetalleFactura,
    Factura,
    Impuesto,
    TotalImpuesto,
    Pago,
    CodigoImpuesto,
    CodigoPorcentajeIVA,
    FormaPago,
    TipoIdentificacion,
)
from src.sri.xml_builder import XMLBuilder
from src.sri.access_key import generar_clave_acceso
from src.sri.signer_sri import XAdESSigner
from src.sri.client import SRIClient
from supabase import create_client
from src.config.settings import get_settings


def main():
    """Genera una factura de prueba."""
    print("=" * 60)
    print("ECUCONDOR - Generación de Primera Factura Electrónica")
    print("=" * 60)
    print()

    # Configuración
    settings = get_settings()
    # Usar service_role key para operaciones de escritura
    supabase = create_client(settings.supabase_url, settings.supabase_key)

    # Datos de la factura
    # Usar zona horaria de Ecuador (UTC-5) para evitar problemas con fecha extemporánea
    ecuador_tz = timezone(timedelta(hours=-5))
    fecha_emision = datetime.now(ecuador_tz).date()
    establecimiento = "001"
    punto_emision = "001"
    secuencial = 1

    print(f"📄 Datos de la factura:")
    print(f"   Establecimiento: {establecimiento}")
    print(f"   Punto Emisión: {punto_emision}")
    print(f"   Secuencial: {secuencial:09d}")
    print(f"   Fecha: {fecha_emision}")
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

    print(f"🔑 Clave de Acceso: {clave_acceso}")
    print()

    # Construir información tributaria
    info_tributaria = InfoTributaria(
        ambiente=settings.sri_ambiente,
        tipo_emision=settings.sri_tipo_emision,
        razon_social=settings.sri_razon_social,
        nombre_comercial=settings.sri_nombre_comercial,
        ruc=settings.sri_ruc,
        clave_acceso=clave_acceso,
        cod_doc="01",
        estab=establecimiento,
        pto_emi=punto_emision,
        secuencial=f"{secuencial:09d}",
        dir_matriz=settings.sri_direccion_matriz,
    )

    # Valores de la factura (comisión de intermediación P2P)
    base_imponible = Decimal("10.00")
    porcentaje_iva = Decimal("15.00")
    valor_iva = base_imponible * porcentaje_iva / 100
    total = base_imponible + valor_iva

    print(f"Valores:")
    print(f"   Base Imponible: ${base_imponible:.2f}")
    print(f"   IVA 15%: ${valor_iva:.2f}")
    print(f"   TOTAL: ${total:.2f}")
    print()

    # Construir detalle
    detalle = DetalleFactura(
        codigo_principal="SRV001",
        descripcion="Comision por intermediacion P2P",
        cantidad=Decimal("1"),
        precio_unitario=base_imponible,
        descuento=Decimal("0"),
        precio_total_sin_impuesto=base_imponible,
        impuestos=[
            Impuesto(
                codigo=CodigoImpuesto.IVA,
                codigo_porcentaje=CodigoPorcentajeIVA.IVA_15,
                tarifa=porcentaje_iva,
                base_imponible=base_imponible,
                valor=valor_iva,
            )
        ],
    )

    # Construir información de la factura
    info_factura = InfoFactura(
        fecha_emision=fecha_emision,
        dir_establecimiento=settings.sri_direccion_matriz,
        obligado_contabilidad=settings.sri_obligado_contabilidad,
        tipo_identificacion_comprador=TipoIdentificacion.CONSUMIDOR_FINAL,
        razon_social_comprador="CONSUMIDOR FINAL",
        identificacion_comprador="9999999999999",
        total_sin_impuestos=base_imponible,
        total_descuento=Decimal("0"),
        total_con_impuestos=[
            TotalImpuesto(
                codigo=CodigoImpuesto.IVA,
                codigo_porcentaje=CodigoPorcentajeIVA.IVA_15,
                base_imponible=base_imponible,
                tarifa=porcentaje_iva,
                valor=valor_iva,
            )
        ],
        importe_total=total,
        moneda="DOLAR",
        pagos=[
            Pago(
                forma_pago=FormaPago.SIN_SISTEMA_FINANCIERO,
                total=total,
            )
        ],
    )

    # Construir factura completa
    factura = Factura(
        info_tributaria=info_tributaria,
        info_factura=info_factura,
        detalles=[detalle],
        info_adicional={
            "Email": "ecucondor@gmail.com",
            "Observacion": "Comision por intermediacion P2P",
        },
    )

    # Generar XML
    print("🔨 Construyendo XML...")
    builder = XMLBuilder()
    xml_sin_firmar = builder.build_factura(factura)

    # Firmar digitalmente
    print(f"🔏 Firmando con certificado: {settings.sri_cert_path}")
    signer = XAdESSigner(
        cert_path=settings.sri_cert_path,
        cert_password=settings.sri_cert_password,
    )
    xml_firmado = signer.sign(xml_sin_firmar)
    print("✅ XML firmado correctamente")
    print()

    # Enviar al SRI
    ambiente_str = "producción" if settings.sri_ambiente == "2" else "pruebas"
    print(f"📤 Enviando al SRI (ambiente de {ambiente_str})...")
    client = SRIClient(ambiente=settings.sri_ambiente)

    try:
        # Envío
        print("   1. Enviando comprobante...")
        resultado_recepcion = client.enviar_comprobante(xml_firmado)

        if resultado_recepcion.estado == "RECIBIDA":
            print(f"   ✅ Comprobante RECIBIDO por el SRI")
            print()

            # Autorización
            print("   2. Consultando autorización...")
            import time
            time.sleep(3)  # Esperar antes de consultar
            resultado_autorizacion = client.consultar_autorizacion(clave_acceso)

            # Verificar si hay autorizaciones
            if resultado_autorizacion.autorizaciones and len(resultado_autorizacion.autorizaciones) > 0:
                autorizacion = resultado_autorizacion.autorizaciones[0]

                if autorizacion.estado == "AUTORIZADO":
                    print(f"   ✅ Factura AUTORIZADA")
                    print(f"   📋 Número de Autorización: {autorizacion.numero_autorizacion}")
                    print(f"   📅 Fecha: {autorizacion.fecha_autorizacion}")
                    print()

                    # Guardar en base de datos
                    print("💾 Guardando en base de datos...")
                    data = {
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
                        "estado": "authorized",
                        "numero_autorizacion": autorizacion.numero_autorizacion,
                        "fecha_autorizacion": autorizacion.fecha_autorizacion.isoformat() if autorizacion.fecha_autorizacion else None,
                        "xml_firmado": xml_firmado,
                    }

                    response = supabase.table("comprobantes_electronicos").insert(data).execute()
                    print(f"   ✅ Factura guardada en BD (ID: {response.data[0]['id']})")
                    print()

                    # Resumen final
                    print("=" * 60)
                    print("✨ FACTURA GENERADA EXITOSAMENTE")
                    print("=" * 60)
                    print(f"Número: {establecimiento}-{punto_emision}-{secuencial:09d}")
                    print(f"Cliente: CONSUMIDOR FINAL")
                    print(f"Total: ${total:.2f}")
                    print(f"Estado: AUTORIZADO")
                    print(f"Autorización: {autorizacion.numero_autorizacion}")
                    print("=" * 60)

                    return 0
                else:
                    print(f"   ❌ Factura NO AUTORIZADA: {autorizacion.estado}")
                    if autorizacion.mensajes:
                        for msg in autorizacion.mensajes:
                            print(f"      - {msg.identificador}: {msg.mensaje}")
                    return 1
            else:
                print(f"   ❌ Sin respuesta de autorización")
                return 1
        else:
            print(f"   ❌ Comprobante RECHAZADO en recepción: {resultado_recepcion.estado}")
            if resultado_recepcion.comprobantes:
                for comp in resultado_recepcion.comprobantes:
                    if comp.get("mensajes"):
                        for msg in comp["mensajes"]:
                            print(f"      - {msg.get('identificador')}: {msg.get('mensaje')}")
            return 1

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
