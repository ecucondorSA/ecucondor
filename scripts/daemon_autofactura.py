#!/usr/bin/env python3
"""
ECUCONDOR - Daemon de Auto-Facturación P2P
Monitorea Gmail para depósitos Produbanco y genera facturas electrónicas automáticamente.

Uso:
    python scripts/daemon_autofactura.py              # Modo daemon (loop continuo)
    python scripts/daemon_autofactura.py --once       # Procesar una vez y salir
    python scripts/daemon_autofactura.py --dry-run    # Ver emails sin facturar
"""

import os
import sys
import time
import signal
import logging
import argparse
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
from src.gmail.watcher import GmailWatcher
from src.gmail.parser_produbanco import parsear_deposito
from src.facturacion.auto_invoice import AutoInvoiceService
from src.notifications.telegram import enviar_alerta

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("autofactura")

# Flag para shutdown limpio
shutdown_requested = False


def signal_handler(signum, frame):
    global shutdown_requested
    logger.info("Señal %s recibida, cerrando...", signal.Signals(signum).name)
    shutdown_requested = True


def procesar_ciclo(watcher: GmailWatcher, invoicer: AutoInvoiceService, dry_run: bool = False) -> int:
    """
    Ejecuta un ciclo de procesamiento.

    Returns:
        Número de facturas generadas
    """
    # 0. Reintentar facturas pendientes de autorización
    if not dry_run:
        try:
            retry_result = invoicer.reintentar_pendientes()
            if retry_result["reautorizadas"] or retry_result["errores"]:
                logger.info(
                    "Reintentos: %d reautorizadas, %d pendientes, %d errores",
                    retry_result["reautorizadas"],
                    retry_result["aun_pendientes"],
                    retry_result["errores"],
                )
        except Exception as e:
            logger.warning("Error en reintentos: %s", str(e))

    # 1. Buscar emails nuevos
    emails = watcher.buscar_depositos_nuevos()

    if not emails:
        return 0

    facturas_generadas = 0

    for email_data in emails:
        msg_id = email_data["message_id"]

        # 2. Verificar deduplicación
        if invoicer.ya_procesado(msg_id):
            logger.debug("Email %s ya procesado, saltando", msg_id)
            continue

        # 3. Parsear email
        deposito = parsear_deposito(
            html_body=email_data["html_body"],
            subject=email_data["subject"],
            message_id=msg_id,
        )

        if deposito is None:
            logger.info(
                "Email %s descartado (transferencia propia o no parseable): %s",
                msg_id, email_data["subject"],
            )
            # Marcar como leído para no reprocesar
            if not dry_run:
                watcher.marcar_procesado(msg_id)
            continue

        logger.info(
            "Depósito detectado: $%.2f de %s (ref: %s)",
            deposito.monto, deposito.nombre_remitente, deposito.referencia,
        )

        if dry_run:
            logger.info("[DRY-RUN] Se generaría factura por comisión: $%.2f",
                       deposito.monto * 15 / 1000)  # 1.5% aprox
            continue

        # 4. Generar factura
        try:
            resultado = invoicer.procesar_deposito(deposito)

            if resultado["estado"] == "duplicado":
                logger.info("Depósito ya facturado, saltando")
            elif resultado["estado"] == "authorized":
                logger.info(
                    "FACTURA AUTORIZADA: %s | Total: $%.2f | Auth: %s",
                    resultado["numero"],
                    resultado["total"],
                    resultado.get("numero_autorizacion", "N/A"),
                )
                facturas_generadas += 1
            else:
                logger.warning(
                    "Factura generada pero no autorizada: %s | Estado: %s",
                    resultado["numero"], resultado["estado"],
                )
                facturas_generadas += 1

            # Marcar email como leído
            watcher.marcar_procesado(msg_id)

        except Exception as e:
            logger.error(
                "Error procesando depósito de %s ($%.2f): %s",
                deposito.nombre_remitente, deposito.monto, str(e),
            )
            # NO marcar como leído para reintentar

    return facturas_generadas


def main():
    parser = argparse.ArgumentParser(description="ECUCONDOR Auto-Factura P2P")
    parser.add_argument("--once", action="store_true", help="Procesar una vez y salir")
    parser.add_argument("--dry-run", action="store_true", help="Ver emails sin generar facturas")
    args = parser.parse_args()

    settings = get_settings()

    print("=" * 60)
    print("ECUCONDOR - Daemon de Auto-Facturación P2P")
    print("=" * 60)
    print(f"  Ambiente SRI: {'PRODUCCIÓN' if settings.sri_ambiente == '2' else 'PRUEBAS'}")
    print(f"  RUC: {settings.sri_ruc}")
    print(f"  Comisión: {settings.comision_porcentaje}%")
    print(f"  IVA: {settings.iva_porcentaje}%")
    print(f"  Intervalo: {settings.gmail_poll_interval}s")
    if args.dry_run:
        print("  MODO: DRY-RUN (no se generan facturas)")
    elif args.once:
        print("  MODO: Una vez y salir")
    else:
        print("  MODO: Daemon continuo")
    print("=" * 60)
    print()

    # Inicializar servicios
    watcher = GmailWatcher(token_path=settings.gmail_token_path)
    supabase = create_client(settings.supabase_url, settings.supabase_key)
    invoicer = AutoInvoiceService(settings=settings, supabase=supabase)

    # Verificar certificado
    from src.sri.signer_sri import XAdESSigner
    try:
        signer = XAdESSigner(settings.sri_cert_path, settings.sri_cert_password)
        if hasattr(signer, 'is_certificate_valid') and not signer.is_certificate_valid():
            logger.error("CERTIFICADO EXPIRADO - No se pueden firmar facturas")
            return 1
        logger.info("Certificado electrónico válido")
    except Exception as e:
        logger.error("Error con certificado: %s", str(e))
        return 1

    # Registrar señales
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if args.once or args.dry_run:
        # Modo una vez
        n = procesar_ciclo(watcher, invoicer, dry_run=args.dry_run)
        if args.dry_run:
            logger.info("Dry-run completado")
        else:
            logger.info("Ciclo completado: %d facturas generadas", n)
        return 0

    # Modo daemon
    ambiente = "PRODUCCION" if settings.sri_ambiente == "2" else "PRUEBAS"
    enviar_alerta(
        f"Daemon auto-factura INICIADO ({ambiente})",
        token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
    )
    logger.info("Daemon iniciado. Ctrl+C para detener.")
    total_facturas = 0

    while not shutdown_requested:
        try:
            n = procesar_ciclo(watcher, invoicer)
            total_facturas += n
            if n > 0:
                logger.info("Ciclo: %d facturas | Total sesión: %d", n, total_facturas)
        except Exception as e:
            logger.error("Error en ciclo: %s", str(e), exc_info=True)
            enviar_alerta(
                f"ERROR en ciclo daemon: {str(e)[:300]}",
                token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
            )

        # Esperar hasta el siguiente ciclo
        for _ in range(settings.gmail_poll_interval):
            if shutdown_requested:
                break
            time.sleep(1)

    logger.info("Daemon detenido. Total facturas generadas: %d", total_facturas)
    return 0


if __name__ == "__main__":
    sys.exit(main())
