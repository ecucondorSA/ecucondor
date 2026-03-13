#!/usr/bin/env python3
"""
ECUCONDOR - ATS Mensual Automatizado
Genera el ATS del mes anterior y lo sube al SRI automáticamente.

Uso:
    python scripts/ats_mensual_auto.py              # Mes anterior
    python scripts/ats_mensual_auto.py 2025 11      # Mes específico
    python scripts/ats_mensual_auto.py --solo-generar  # Solo genera, no sube
"""

import os
import sys
import time
import zipfile
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal

# Agregar src al path
PROYECTO_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROYECTO_DIR))

# Cargar .env
from dotenv import dotenv_values
env_values = dotenv_values(PROYECTO_DIR / ".env")
for key, value in env_values.items():
    if value is not None:
        os.environ[key] = value

from supabase import create_client
from src.sri.ats.models import (
    ATS, DetalleVenta, DetalleAnulado, VentaEstablecimiento,
    TipoIdentificacionATS, TipoComprobanteATS,
)
from src.sri.ats.builder import ATSBuilder
from src.config.settings import get_settings
get_settings.cache_clear()

# ── Configuración SRI Portal ──
SRI_RUC = "1391937000001"
SRI_PASSWORD = os.environ.get("SRI_PASSWORD", "Ecu081223.")
SRI_URL_ANEXOS = "https://srienlinea.sri.gob.ec/sri-en-linea/SriAnexos/EnvioConsulta/envioConsulta"
CHROME_PATH = "/opt/google/chrome/chrome"
CDP_PORT = 9222


def calcular_mes_anterior():
    """Retorna (año, mes) del mes anterior."""
    hoy = datetime.now()
    primer_dia = hoy.replace(day=1)
    mes_anterior = primer_dia - timedelta(days=1)
    return mes_anterior.year, mes_anterior.month


def mapear_tipo_id(tipo_sri: str) -> TipoIdentificacionATS:
    mapeo = {
        "04": TipoIdentificacionATS.RUC,
        "05": TipoIdentificacionATS.CEDULA,
        "06": TipoIdentificacionATS.PASAPORTE,
        "07": TipoIdentificacionATS.CONSUMIDOR_FINAL,
        "08": TipoIdentificacionATS.EXTERIOR,
    }
    return mapeo.get(tipo_sri, TipoIdentificacionATS.CEDULA)


def generar_ats(anio: int, mes: int) -> Path:
    """Genera el ATS XML+ZIP y retorna la ruta del ZIP."""
    import calendar

    settings = get_settings()
    supabase = create_client(settings.supabase_url, settings.supabase_key)

    print(f"\n{'='*60}")
    print(f"  ECUCONDOR - ATS {mes:02d}/{anio}")
    print(f"{'='*60}\n")

    fecha_inicio = f"{anio}-{mes:02d}-01"
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    fecha_fin = f"{anio}-{mes:02d}-{ultimo_dia:02d}"

    # Consultar facturas autorizadas
    facturas = supabase.table("comprobantes_electronicos").select("*").eq(
        "tipo_comprobante", "01"
    ).eq("estado", "authorized").gte(
        "fecha_emision", fecha_inicio
    ).lte("fecha_emision", fecha_fin).execute()

    print(f"  Facturas autorizadas: {len(facturas.data)}")

    # Agrupar por cliente
    ventas_por_cliente = {}
    for f in facturas.data:
        cid = f.get("cliente_identificacion", "9999999999999")
        tid = f.get("cliente_tipo_id", "05")
        if cid not in ventas_por_cliente:
            ventas_por_cliente[cid] = {
                "tipo_id": tid, "base_no_grava": Decimal("0"),
                "base_0": Decimal("0"), "base_15": Decimal("0"),
                "iva": Decimal("0"), "cantidad": 0,
            }
        ventas_por_cliente[cid]["base_15"] += Decimal(str(f.get("subtotal_15", 0) or 0))
        ventas_por_cliente[cid]["base_0"] += Decimal(str(f.get("subtotal_0", 0) or 0))
        ventas_por_cliente[cid]["iva"] += Decimal(str(f.get("iva", 0) or 0))
        ventas_por_cliente[cid]["cantidad"] += 1

    detalles_ventas = []
    for cid, d in ventas_por_cliente.items():
        detalles_ventas.append(DetalleVenta(
            tipo_id_cliente=mapear_tipo_id(d["tipo_id"]),
            id_cliente=cid,
            tipo_comprobante=TipoComprobanteATS.FACTURA_ELECTRONICA,
            tipo_emision="E",
            numero_comprobantes=d["cantidad"],
            base_no_grava_iva=d["base_no_grava"],
            base_imponible_0=d["base_0"],
            base_imponible_15=d["base_15"],
            monto_iva=d["iva"],
            formas_pago=["20"],
        ))

    # Anulados
    anulados = supabase.table("comprobantes_electronicos").select("*").eq(
        "tipo_comprobante", "01"
    ).eq("estado", "cancelled").gte(
        "fecha_emision", fecha_inicio
    ).lte("fecha_emision", fecha_fin).execute()

    detalles_anulados = []
    for a in anulados.data:
        detalles_anulados.append(DetalleAnulado(
            tipo_comprobante=TipoComprobanteATS.FACTURA_ELECTRONICA,
            establecimiento=a.get("establecimiento", "001"),
            punto_emision=a.get("punto_emision", "001"),
            secuencial_inicio=a.get("secuencial", "000000001"),
            secuencial_fin=a.get("secuencial", "000000001"),
            autorizacion=a.get("clave_acceso", "") or a.get("numero_autorizacion", ""),
        ))

    # Construir ATS
    ats = ATS(
        id_informante=settings.sri_ruc,
        razon_social=settings.sri_razon_social,
        anio=anio, mes=mes, num_estab_ruc="001",
        ventas=detalles_ventas, anulados=detalles_anulados,
    )

    # Agregar ventasEstablecimiento (requerido por SRI)
    total_ventas = ats.calcular_total_ventas()
    ats.ventas_establecimiento = [
        VentaEstablecimiento(cod_estab="001", ventas_estab=total_ventas)
    ]

    builder = ATSBuilder()
    xml_content = builder.build(ats)

    # Guardar archivos
    output_dir = PROYECTO_DIR / "output" / "ats"
    output_dir.mkdir(parents=True, exist_ok=True)
    nombre = f"ATS_{mes:02d}_{anio}"
    xml_file = output_dir / f"{nombre}.xml"
    zip_file = output_dir / f"{nombre}.zip"

    with open(xml_file, "w", encoding="utf-8") as f:
        f.write(xml_content)

    with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(xml_file, xml_file.name)

    total = ats.calcular_total_ventas()
    print(f"  Clientes: {len(detalles_ventas)}")
    print(f"  Total ventas: ${total:,.2f}")
    print(f"  ZIP: {zip_file}")

    return zip_file


def subir_al_sri(zip_path: Path):
    """Sube el ATS al portal del SRI usando Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("\n  Playwright no instalado. Instalando...")
        subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        from playwright.sync_api import sync_playwright

    print(f"\n{'='*60}")
    print("  SUBIENDO AL SRI")
    print(f"{'='*60}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=500)
        page = browser.new_page()

        # 1. Login
        print("  Iniciando sesión en SRI...")
        page.goto("https://srienlinea.sri.gob.ec/sri-en-linea/inicio/NAT")
        page.wait_for_load_state("networkidle")

        # Llenar credenciales
        page.fill('input[placeholder*="RUC"], input[name*="usuario"], #usuario', SRI_RUC)
        page.fill('input[type="password"]', SRI_PASSWORD)
        page.click('button[type="submit"], .btn-primary, button:has-text("Iniciar")')
        page.wait_for_load_state("networkidle")
        time.sleep(3)

        # 2. Navegar a Anexos > ATS
        print("  Navegando a Anexos > ATS...")
        page.goto(SRI_URL_ANEXOS)
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        # Click en "Anexo Transaccional Simplificado"
        page.click('text=Anexo Transaccional Simplificado')
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        # Click en "Carga de archivo xml"
        page.click('text=Carga de archivo xml')
        time.sleep(1)

        # 3. Subir archivo
        print(f"  Subiendo {zip_path.name}...")
        page.set_input_files('input[type="file"]', str(zip_path))
        time.sleep(3)

        # 4. Verificar validación
        page_text = page.inner_text('body')
        if 'error' in page_text.lower() and 'Lista de errores' in page_text:
            print(f"  ERROR: El SRI rechazó el archivo")
            # Extraer mensaje de error
            error_lines = [l for l in page_text.split('\n') if 'Linea' in l or 'Mensaje' in l]
            for line in error_lines:
                print(f"    {line.strip()}")
            browser.close()
            return False

        # 5. Click en Cargar
        if 'Validación de esquema terminada' in page_text or 'Información del contribuyente' in page_text:
            print("  Validación OK. Cargando...")
            page.click('text=Cargar')
            time.sleep(5)

            # 6. Verificar confirmación
            page_text = page.inner_text('body')
            if 'Confirmación de Presentación' in page_text:
                print("  ATS SUBIDO EXITOSAMENTE!")
                # Click Aceptar
                page.click('text=Aceptar')
                time.sleep(1)
                browser.close()
                return True
            else:
                print("  No se pudo confirmar la carga")
                browser.close()
                return False
        else:
            print("  Respuesta inesperada del SRI")
            print(f"  Texto: {page_text[:500]}")
            browser.close()
            return False


def main():
    solo_generar = "--solo-generar" in sys.argv

    # Determinar mes
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) >= 2:
        anio, mes = int(args[0]), int(args[1])
    else:
        anio, mes = calcular_mes_anterior()

    print(f"\n  ECUCONDOR - ATS Mensual Automático")
    print(f"  Período: {mes:02d}/{anio}")
    print(f"  Modo: {'Solo generar' if solo_generar else 'Generar + Subir'}")

    # Paso 1: Generar
    zip_path = generar_ats(anio, mes)

    if solo_generar:
        print(f"\n  Archivo listo: {zip_path}")
        print("  Para subir manualmente, ve a:")
        print("  https://srienlinea.sri.gob.ec > Anexos > ATS > Carga de archivo xml")
        return 0

    # Paso 2: Subir al SRI
    ok = subir_al_sri(zip_path)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
