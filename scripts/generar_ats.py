#!/usr/bin/env python3
"""
ECUCONDOR - Generador de ATS (Anexo Transaccional Simplificado)

Genera el archivo XML del ATS para un mes específico basándose en:
- Facturas electrónicas autorizadas (ventas)
- Comprobantes anulados

Uso:
    python scripts/generar_ats.py <año> <mes>
    python scripts/generar_ats.py 2025 11

El archivo generado se guarda en output/ats/ y está listo para
subir al portal del SRI.
"""

import os
import sys
import zipfile
import calendar
from pathlib import Path
from datetime import datetime
from decimal import Decimal

# Agregar src al path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Cargar variables de .env
from dotenv import dotenv_values

ENV_FILE = Path(__file__).parent.parent / ".env"
env_values = dotenv_values(ENV_FILE)
for key, value in env_values.items():
    if value is not None:
        os.environ[key] = value

from supabase import create_client
from src.sri.ats.models import (
    ATS,
    DetalleVenta,
    DetalleAnulado,
    VentaEstablecimiento,
    TipoIdentificacionATS,
    TipoComprobanteATS,
)
from src.sri.ats.builder import ATSBuilder
from src.config.settings import get_settings

# Limpiar cache de settings
get_settings.cache_clear()


def mapear_tipo_identificacion(tipo_sri: str) -> TipoIdentificacionATS:
    """
    Mapea el tipo de identificación de facturación al tipo de ATS.

    Args:
        tipo_sri: Código de tipo de identificación de facturación electrónica

    Returns:
        Código de tipo de identificación para ATS
    """
    mapeo = {
        "04": TipoIdentificacionATS.RUC,
        "05": TipoIdentificacionATS.CEDULA,
        "06": TipoIdentificacionATS.PASAPORTE,
        "07": TipoIdentificacionATS.CONSUMIDOR_FINAL,
        "08": TipoIdentificacionATS.EXTERIOR,
    }
    return mapeo.get(tipo_sri, TipoIdentificacionATS.CEDULA)


def main(anio: int, mes: int):
    """
    Genera el ATS para el período especificado.

    Args:
        anio: Año del período (ej: 2025)
        mes: Mes del período (1-12)
    """
    settings = get_settings()
    supabase = create_client(settings.supabase_url, settings.supabase_key)

    print("=" * 60)
    print(f"ECUCONDOR - Generación de ATS {mes:02d}/{anio}")
    print("=" * 60)
    print()
    print(f"RUC: {settings.sri_ruc}")
    print(f"Razón Social: {settings.sri_razon_social}")
    print()

    # Calcular rango de fechas del mes
    fecha_inicio = f"{anio}-{mes:02d}-01"
    # Obtener el último día real del mes
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    fecha_fin = f"{anio}-{mes:02d}-{ultimo_dia:02d}"

    print(f"Período: {fecha_inicio} al {fecha_fin}")
    print()

    # =================================================================
    # OBTENER FACTURAS AUTORIZADAS DEL MES
    # =================================================================
    print("📊 Consultando facturas autorizadas...")

    facturas = supabase.table("comprobantes_electronicos").select("*").eq(
        "tipo_comprobante", "01"  # Facturas
    ).eq(
        "estado", "authorized"
    ).gte(
        "fecha_emision", fecha_inicio
    ).lte(
        "fecha_emision", fecha_fin
    ).execute()

    print(f"   Facturas encontradas: {len(facturas.data)}")

    # Agrupar ventas por cliente
    ventas_por_cliente = {}

    for f in facturas.data:
        cliente_id = f.get("cliente_identificacion", "9999999999999")
        tipo_id = f.get("cliente_tipo_id", "05")

        if cliente_id not in ventas_por_cliente:
            ventas_por_cliente[cliente_id] = {
                "tipo_id": tipo_id,
                "base_no_grava": Decimal("0"),
                "base_0": Decimal("0"),
                "base_15": Decimal("0"),
                "iva": Decimal("0"),
                "cantidad": 0,
            }

        # Sumar montos (columnas correctas de la BD)
        base_15 = Decimal(str(f.get("subtotal_15", 0) or 0))
        base_0 = Decimal(str(f.get("subtotal_0", 0) or 0))
        iva = Decimal(str(f.get("iva", 0) or 0))

        ventas_por_cliente[cliente_id]["base_15"] += base_15
        ventas_por_cliente[cliente_id]["base_0"] += base_0
        ventas_por_cliente[cliente_id]["iva"] += iva
        ventas_por_cliente[cliente_id]["cantidad"] += 1

    print(f"   Clientes únicos: {len(ventas_por_cliente)}")

    # Crear detalles de venta para el ATS
    detalles_ventas = []

    for cliente_id, datos in ventas_por_cliente.items():
        detalle = DetalleVenta(
            tipo_id_cliente=mapear_tipo_identificacion(datos["tipo_id"]),
            id_cliente=cliente_id,
            parte_relacionada="NO",
            tipo_comprobante=TipoComprobanteATS.FACTURA_ELECTRONICA,
            tipo_emision="E",
            numero_comprobantes=datos["cantidad"],
            base_no_grava_iva=datos["base_no_grava"],
            base_imponible_0=datos["base_0"],
            base_imponible_15=datos["base_15"],
            monto_iva=datos["iva"],
            monto_ice=Decimal("0"),
            valor_ret_iva=Decimal("0"),
            valor_ret_renta=Decimal("0"),
            formas_pago=["20"],  # Otros sin sistema financiero
        )
        detalles_ventas.append(detalle)

    # =================================================================
    # OBTENER COMPROBANTES ANULADOS DEL MES
    # =================================================================
    print()
    print("🚫 Consultando comprobantes anulados...")

    anulados = supabase.table("comprobantes_electronicos").select("*").eq(
        "tipo_comprobante", "01"
    ).eq(
        "estado", "cancelled"
    ).gte(
        "fecha_emision", fecha_inicio
    ).lte(
        "fecha_emision", fecha_fin
    ).execute()

    print(f"   Anulados encontrados: {len(anulados.data)}")

    # Crear detalles de anulados
    detalles_anulados = []

    for a in anulados.data:
        detalle = DetalleAnulado(
            tipo_comprobante=TipoComprobanteATS.FACTURA_ELECTRONICA,
            establecimiento=a.get("establecimiento", "001"),
            punto_emision=a.get("punto_emision", "001"),
            secuencial_inicio=a.get("secuencial", "000000001"),
            secuencial_fin=a.get("secuencial", "000000001"),
            autorizacion=a.get("clave_acceso", "") or a.get("numero_autorizacion", ""),
        )
        detalles_anulados.append(detalle)

    # =================================================================
    # CREAR MODELO ATS
    # =================================================================
    print()
    print("🔨 Generando XML del ATS...")

    ats = ATS(
        tipo_id_informante="R",
        id_informante=settings.sri_ruc,
        razon_social=settings.sri_razon_social,
        anio=anio,
        mes=mes,
        num_estab_ruc="001",
        ventas=detalles_ventas,
        anulados=detalles_anulados,
    )

    # Agregar ventasEstablecimiento (requerido por SRI)
    total_ventas = ats.calcular_total_ventas()
    ats.ventas_establecimiento = [
        VentaEstablecimiento(
            cod_estab="001",
            ventas_estab=total_ventas,
        )
    ]

    # Generar XML
    builder = ATSBuilder()
    xml_content = builder.build(ats)

    # =================================================================
    # GUARDAR ARCHIVOS
    # =================================================================
    output_dir = Path(__file__).parent.parent / "output" / "ats"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Nombre del archivo según especificación SRI: ATS_MM_YYYY
    nombre_base = f"ATS_{mes:02d}_{anio}"
    xml_file = output_dir / f"{nombre_base}.xml"
    zip_file = output_dir / f"{nombre_base}.zip"

    # Guardar XML
    with open(xml_file, "w", encoding="utf-8") as f:
        f.write(xml_content)
        f.flush()  # Asegurar que se escriba en disco
        os.fsync(f.fileno())  # Forzar sincronización del sistema de archivos

    print(f"   XML guardado: {xml_file}")

    # Crear ZIP (requerido por SRI)
    with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(xml_file, xml_file.name)

    print(f"   ZIP guardado: {zip_file}")

    # =================================================================
    # RESUMEN
    # =================================================================
    total_ventas = ats.calcular_total_ventas()
    total_base = ats.calcular_base_gravada_total()
    total_iva = ats.calcular_iva_total()

    print()
    print("=" * 60)
    print("✅ ATS GENERADO EXITOSAMENTE")
    print("=" * 60)
    print()
    print(f"📊 RESUMEN DEL PERÍODO {mes:02d}/{anio}")
    print(f"   Clientes con ventas: {len(detalles_ventas)}")
    print(f"   Facturas emitidas: {sum(v.numero_comprobantes for v in detalles_ventas)}")
    print(f"   Comprobantes anulados: {len(detalles_anulados)}")
    print()
    print(f"💰 TOTALES:")
    print(f"   Base IVA 15%: ${total_base:,.2f}")
    print(f"   IVA: ${total_iva:,.2f}")
    print(f"   Total Ventas: ${total_ventas:,.2f}")
    print()
    print(f"📁 ARCHIVOS GENERADOS:")
    print(f"   {xml_file}")
    print(f"   {zip_file} ← Subir este archivo al SRI")
    print()
    print("📤 INSTRUCCIONES PARA SUBIR AL SRI:")
    print("   1. Ingresar a: https://srienlinea.sri.gob.ec")
    print("   2. Ir a: DECLARACIONES > Anexo Transaccional Simplificado")
    print(f"   3. Seleccionar período: {mes:02d}/{anio}")
    print(f"   4. Cargar archivo: {zip_file.name}")
    print("   5. Validar y enviar")
    print()

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("ECUCONDOR - Generador de ATS")
        print()
        print("Uso: python scripts/generar_ats.py <año> <mes>")
        print()
        print("Ejemplos:")
        print("  python scripts/generar_ats.py 2025 11  # Noviembre 2025")
        print("  python scripts/generar_ats.py 2025 12  # Diciembre 2025")
        print()
        sys.exit(1)

    try:
        anio = int(sys.argv[1])
        mes = int(sys.argv[2])

        if not (2020 <= anio <= 2100):
            print(f"Error: Año inválido ({anio}). Debe estar entre 2020 y 2100.")
            sys.exit(1)

        if not (1 <= mes <= 12):
            print(f"Error: Mes inválido ({mes}). Debe estar entre 1 y 12.")
            sys.exit(1)

        sys.exit(main(anio, mes))

    except ValueError as e:
        print(f"Error: Argumentos inválidos. Año y mes deben ser números enteros.")
        print(f"Detalle: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error inesperado: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
