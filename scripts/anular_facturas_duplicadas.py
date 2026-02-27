#!/usr/bin/env python3
"""
ECUCONDOR - Anular Facturas Duplicadas con Notas de Crédito

Emite una Nota de Crédito (tipo "04") por cada factura duplicada (002-013),
anulando el total de cada una ante el SRI.

Uso:
    python scripts/anular_facturas_duplicadas.py --dry-run    # Ver qué se anularía
    python scripts/anular_facturas_duplicadas.py              # Emitir las 12 NC
"""

import os
import sys
import time
import logging
import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# Agregar src al path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Cargar .env
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
from src.sri.signer_sri import XAdESSigner
from src.sri.xml_builder import crear_nota_credito_xml

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("anular_facturas")

ECUADOR_TZ = timezone(timedelta(hours=-5))

# Facturas duplicadas a anular: secuenciales 002-013
SECUENCIALES_DUPLICADAS = list(range(2, 14))  # 2..13 inclusive


def obtener_facturas_duplicadas(db, settings) -> list[dict]:
    """Lee las facturas duplicadas de la BD."""
    secuenciales_str = [f"{s:09d}" for s in SECUENCIALES_DUPLICADAS]

    result = (
        db.table("comprobantes_electronicos")
        .select("*")
        .eq("tipo_comprobante", "01")
        .eq("establecimiento", settings.sri_establecimiento)
        .eq("punto_emision", settings.sri_punto_emision)
        .in_("secuencial", secuenciales_str)
        .order("secuencial")
        .execute()
    )

    return result.data or []


def siguiente_secuencial_nc(db, settings) -> int:
    """Obtiene el siguiente secuencial para notas de crédito."""
    result = (
        db.table("comprobantes_electronicos")
        .select("secuencial")
        .eq("tipo_comprobante", "04")
        .eq("establecimiento", settings.sri_establecimiento)
        .eq("punto_emision", settings.sri_punto_emision)
        .order("secuencial", desc=True)
        .limit(10)
        .execute()
    )

    if result.data:
        for row in result.data:
            sec = row["secuencial"]
            if sec.isdigit():
                return int(sec) + 1
    return 1


def main():
    parser = argparse.ArgumentParser(description="ECUCONDOR - Anular Facturas Duplicadas")
    parser.add_argument("--dry-run", action="store_true", help="Ver facturas sin emitir NC")
    args = parser.parse_args()

    settings = get_settings()
    db = create_client(settings.supabase_url, settings.supabase_key)

    print("=" * 60)
    print("ECUCONDOR - Anular Facturas Duplicadas con Notas de Crédito")
    print("=" * 60)
    print(f"  Ambiente SRI: {'PRODUCCIÓN' if settings.sri_ambiente == '2' else 'PRUEBAS'}")
    print(f"  RUC: {settings.sri_ruc}")
    print(f"  Facturas a anular: {SECUENCIALES_DUPLICADAS[0]:09d} - {SECUENCIALES_DUPLICADAS[-1]:09d}")
    if args.dry_run:
        print("  MODO: DRY-RUN (no se emiten NC)")
    print("=" * 60)
    print()

    # 1. Leer facturas duplicadas
    facturas = obtener_facturas_duplicadas(db, settings)
    logger.info("Facturas duplicadas encontradas: %d", len(facturas))

    if not facturas:
        logger.warning("No se encontraron facturas duplicadas en la BD")
        return 1

    for f in facturas:
        num = f"{f['establecimiento']}-{f['punto_emision']}-{f['secuencial']}"
        logger.info(
            "  Factura %s | Total: $%.2f | Cliente: %s | Estado: %s",
            num, f["importe_total"], f["cliente_razon_social"], f["estado"],
        )

    if args.dry_run:
        total_a_anular = sum(Decimal(str(f["importe_total"])) for f in facturas)
        logger.info("Total a anular: $%.2f en %d notas de crédito", total_a_anular, len(facturas))
        logger.info("Ejecute sin --dry-run para emitir las NC")
        return 0

    # 2. Inicializar servicios
    signer = XAdESSigner(settings.sri_cert_path, settings.sri_cert_password)
    sri_client = SRIClient(ambiente=settings.sri_ambiente)

    # 3. Procesar cada factura
    nc_secuencial = siguiente_secuencial_nc(db, settings)
    fecha_emision = datetime.now(ECUADOR_TZ).date()
    nc_exitosas = 0
    nc_errores = 0

    for factura in facturas:
        num_factura = f"{factura['establecimiento']}-{factura['punto_emision']}-{factura['secuencial']}"
        logger.info("--- Procesando NC para factura %s ---", num_factura)

        # Datos de la factura original
        subtotal = Decimal(str(factura["subtotal_sin_impuestos"]))
        iva = Decimal(str(factura["iva"]))
        total = Decimal(str(factura["importe_total"]))
        fecha_factura_str = factura["fecha_emision"]

        # Parsear fecha de la factura original
        if isinstance(fecha_factura_str, str):
            fecha_factura = date.fromisoformat(fecha_factura_str)
        else:
            fecha_factura = fecha_factura_str

        # Generar clave de acceso para NC
        clave_acceso = generar_clave_acceso(
            fecha_emision=fecha_emision,
            tipo_comprobante="04",
            ruc=settings.sri_ruc,
            ambiente=settings.sri_ambiente,
            establecimiento=settings.sri_establecimiento,
            punto_emision=settings.sri_punto_emision,
            secuencial=nc_secuencial,
            tipo_emision=settings.sri_tipo_emision,
        )

        logger.info(
            "NC %s-%s-%09d | Clave: %s...",
            settings.sri_establecimiento,
            settings.sri_punto_emision,
            nc_secuencial,
            clave_acceso[:20],
        )

        # Generar XML de NC
        xml_sin_firmar = crear_nota_credito_xml(
            ruc=settings.sri_ruc,
            razon_social=settings.sri_razon_social,
            nombre_comercial=settings.sri_nombre_comercial,
            direccion_matriz=settings.sri_direccion_matriz,
            ambiente=settings.sri_ambiente,
            establecimiento=settings.sri_establecimiento,
            punto_emision=settings.sri_punto_emision,
            secuencial=nc_secuencial,
            clave_acceso=clave_acceso,
            fecha_emision=fecha_emision,
            cliente_tipo_id=factura["cliente_tipo_id"],
            cliente_identificacion=factura["cliente_identificacion"],
            cliente_razon_social=factura["cliente_razon_social"],
            obligado_contabilidad=settings.sri_obligado_contabilidad,
            cod_doc_modificado="01",
            num_doc_modificado=num_factura,
            fecha_emision_doc_sustento=fecha_factura,
            motivo="Anulacion por duplicidad de factura",
            items=[
                {
                    "codigo": "SRV001",
                    "descripcion": f"Anulacion factura {num_factura} - Comision P2P duplicada",
                    "cantidad": 1,
                    "precio_unitario": float(subtotal),
                    "aplica_iva": True,
                    "porcentaje_iva": 15,
                }
            ],
            info_adicional={
                "Email": "ecucondor@gmail.com",
                "FacturaAnulada": num_factura,
                "MotivoAnulacion": "Duplicidad por error en sistema de deduplicacion",
            },
        )

        # Firmar
        try:
            xml_firmado = signer.sign(xml_sin_firmar)
            logger.info("XML firmado correctamente")
        except Exception as e:
            logger.error("Error firmando NC: %s", str(e))
            nc_errores += 1
            nc_secuencial += 1
            continue

        # Enviar al SRI
        try:
            resultado = sri_client.enviar_comprobante(xml_firmado)
            if resultado.estado != "RECIBIDA":
                error_msg = f"SRI rechazó NC: {resultado.estado}"
                if resultado.comprobantes:
                    for comp in resultado.comprobantes:
                        for msg in comp.get("mensajes", []):
                            error_msg += f" | {msg.get('identificador')}: {msg.get('mensaje')}"
                logger.error(error_msg)
                nc_errores += 1
                nc_secuencial += 1
                continue

            logger.info("NC RECIBIDA por SRI")
        except Exception as e:
            logger.error("Error enviando NC al SRI: %s", str(e))
            nc_errores += 1
            nc_secuencial += 1
            continue

        # Consultar autorización
        time.sleep(3)
        try:
            resultado_auth = sri_client.consultar_autorizacion(clave_acceso)
        except Exception as e:
            logger.error("Error consultando autorización: %s", str(e))
            resultado_auth = None

        numero_autorizacion = None
        fecha_autorizacion = None
        estado_final = "sent"

        if resultado_auth and resultado_auth.autorizaciones:
            auth = resultado_auth.autorizaciones[0]
            if auth.estado == "AUTORIZADO":
                numero_autorizacion = auth.numero_autorizacion
                fecha_autorizacion = auth.fecha_autorizacion
                estado_final = "authorized"
                logger.info("NC AUTORIZADA: %s", numero_autorizacion)
            else:
                estado_final = "error"
                error_msg = f"NC no autorizada: {auth.estado}"
                if auth.mensajes:
                    for msg in auth.mensajes:
                        error_msg += f" | {msg.identificador}: {msg.mensaje}"
                logger.warning(error_msg)

        # Guardar NC en BD
        numero_nc = f"{settings.sri_establecimiento}-{settings.sri_punto_emision}-{nc_secuencial:09d}"

        nc_data = {
            "tipo_comprobante": "04",
            "establecimiento": settings.sri_establecimiento,
            "punto_emision": settings.sri_punto_emision,
            "secuencial": f"{nc_secuencial:09d}",
            "clave_acceso": clave_acceso,
            "fecha_emision": fecha_emision.isoformat(),
            "cliente_tipo_id": factura["cliente_tipo_id"],
            "cliente_identificacion": factura["cliente_identificacion"],
            "cliente_razon_social": factura["cliente_razon_social"],
            "subtotal_sin_impuestos": float(subtotal),
            "total_descuento": 0.0,
            "subtotal_15": float(subtotal),
            "subtotal_0": 0.0,
            "iva": float(iva),
            "importe_total": float(total),
            "estado": estado_final,
            "xml_firmado": xml_firmado,
        }

        if numero_autorizacion:
            nc_data["numero_autorizacion"] = numero_autorizacion
        if fecha_autorizacion:
            nc_data["fecha_autorizacion"] = (
                fecha_autorizacion.isoformat()
                if hasattr(fecha_autorizacion, "isoformat")
                else str(fecha_autorizacion)
            )

        try:
            db.table("comprobantes_electronicos").insert(nc_data).execute()
            logger.info("NC %s guardada en BD", numero_nc)
        except Exception as e:
            logger.error("Error guardando NC en BD: %s", str(e))

        if estado_final == "authorized":
            nc_exitosas += 1
        else:
            nc_errores += 1

        nc_secuencial += 1
        logger.info("")

    # Resumen
    print()
    print("=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"  NC autorizadas: {nc_exitosas}")
    print(f"  NC con error:   {nc_errores}")
    print(f"  Total:          {nc_exitosas + nc_errores}")
    print("=" * 60)

    return 0 if nc_errores == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
