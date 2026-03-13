#!/usr/bin/env python3
"""
ECUCONDOR - Automatizacion Tributaria Mensual
Orquesta el ciclo fiscal completo: reconciliar depositos, facturar gaps,
calcular IVA, declarar IVA en SRI, generar ATS, subir ATS, notificar.

Uso:
    python scripts/tax_monthly.py                    # Mes anterior automatico
    python scripts/tax_monthly.py 2026 03            # Mes explicito
    python scripts/tax_monthly.py --dry-run           # Solo calcular, no enviar
    python scripts/tax_monthly.py --step submit_iva   # Solo un paso
    python scripts/tax_monthly.py --step calculate_iva --step generate_ats
"""

import argparse
import asyncio
import base64
import calendar
import json
import logging
import os
import sys
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env before anything else
from dotenv import dotenv_values

ENV_FILE = Path(__file__).parent.parent / ".env"
for k, v in dotenv_values(ENV_FILE).items():
    if v is not None:
        os.environ[k] = v

from src.config.settings import get_settings

get_settings.cache_clear()

from patchright.async_api import async_playwright
from supabase import create_client

from src.facturacion.auto_invoice import AutoInvoiceService
from src.gmail.parser_produbanco import DepositoInfo, parsear_deposito
from src.gmail.watcher import GmailWatcher
from src.notifications.telegram import enviar_alerta
from src.sri.ats.builder import ATSBuilder
from src.sri.ats.models import (
    ATS,
    DetalleAnulado,
    DetalleVenta,
    TipoComprobanteATS,
    VentaEstablecimiento,
)
from src.sri.iva.calculator import CalculadorIVA, DatosDeclaracionIVA

# Constants
ECUADOR_TZ = timezone(timedelta(hours=-5))
SCREENSHOT_DIR = Path(__file__).parent.parent / "output" / "screenshots"
LOG_DIR = Path(__file__).parent.parent / "output" / "logs"
STATE_DIR = Path(__file__).parent.parent / "output" / "tax_state"
ATS_DIR = Path(__file__).parent.parent / "output" / "ats"

STEPS = [
    "reconcile",
    "gap_invoices",
    "calculate_iva",
    "submit_iva",
    "generate_ats",
    "submit_ats",
    "notify",
]

MONTH_SHORT = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic",
}

logger = logging.getLogger("tax_monthly")


@dataclass
class StepResult:
    status: str  # "completed", "skipped", "error"
    data: dict = None
    error: str = None

    def __post_init__(self):
        if self.data is None:
            self.data = {}


class TaxMonthlyOrchestrator:
    """Orquestador de declaraciones tributarias mensuales."""

    def __init__(self, year: int, month: int, dry_run: bool = False):
        self.year = year
        self.month = month
        self.dry_run = dry_run
        self.settings = get_settings()
        self.supabase = create_client(self.settings.supabase_url, self.settings.supabase_key)
        self.ss_counter = 0
        self.state_file = STATE_DIR / f"{year}_{month:02d}.json"
        self.state = self._load_state()
        self.results = {}

    def _load_state(self) -> dict:
        if self.state_file.exists():
            return json.loads(self.state_file.read_text())
        return {"year": self.year, "month": self.month, "steps": {}}

    def _save_state(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.state, indent=2, default=str))

    async def _screenshot(self, page, name: str) -> Path:
        self.ss_counter += 1
        path = SCREENSHOT_DIR / f"tax_{self.year}_{self.month:02d}_{self.ss_counter:03d}_{name}.png"
        try:
            await page.screenshot(path=str(path), full_page=False, timeout=10000)
        except Exception:
            try:
                client = await page.context.new_cdp_session(page)
                result = await client.send("Page.captureScreenshot", {"format": "png"})
                path.write_bytes(base64.b64decode(result["data"]))
                await client.detach()
            except Exception:
                pass
        logger.debug(f"Screenshot: {path.name}")
        return path

    async def _handle_dialogs(self, page):
        for _ in range(5):
            dialog = await page.evaluate("""() => {
                const dialogs = document.querySelectorAll('.ui-dialog');
                for (const d of dialogs) {
                    if (d.offsetHeight > 0 && d.style.display !== 'none' &&
                        d.querySelector('.ui-dialog-content')) {
                        return {
                            visible: true,
                            text: d.querySelector('.ui-dialog-content').textContent.trim().substring(0, 300)
                        };
                    }
                }
                return {visible: false};
            }""")
            if not dialog.get("visible"):
                return
            logger.info(f"Dialog: {dialog['text'][:150]}")
            await page.evaluate("""() => {
                const dialogs = document.querySelectorAll('.ui-dialog');
                for (const d of dialogs) {
                    if (d.offsetHeight > 0 && d.style.display !== 'none') {
                        for (const b of d.querySelectorAll('button')) {
                            const t = b.textContent.trim().toLowerCase();
                            if (['sí','si','aceptar','continuar','ok','enviar'].includes(t)) {
                                b.click(); return;
                            }
                        }
                    }
                }
            }""")
            await asyncio.sleep(5)

    async def _set_field(self, page, field_id: str, value: str):
        return await page.evaluate(f"""(val) => {{
            const inp = document.getElementById('{field_id}');
            if (!inp) return 'not found';
            if (inp.readOnly) return 'readonly';
            inp.focus();
            inp.dispatchEvent(new Event('focus', {{bubbles: true}}));
            inp.value = '';
            inp.value = val;
            inp.dispatchEvent(new Event('input', {{bubbles: true}}));
            inp.dispatchEvent(new Event('change', {{bubbles: true}}));
            inp.dispatchEvent(new Event('blur', {{bubbles: true}}));
            inp.dispatchEvent(new KeyboardEvent('keyup', {{bubbles: true, key: 'Tab'}}));
            return 'ok';
        }}""", value)

    async def _click_siguiente(self, page):
        await page.evaluate("""() => {
            for (const b of document.querySelectorAll('button')) {
                if (b.textContent.trim().includes('Siguiente') && b.offsetHeight > 0) {
                    b.click(); return;
                }
            }
        }""")

    async def _ensure_sri_session(self, page) -> bool:
        """Navegar a declaraciones y verificar/restaurar sesion SRI."""
        decl_url = "https://srienlinea.sri.gob.ec/sri-declaraciones-web-internet/pages/recepcion/recibirDeclaracion.jsf"
        await page.goto(decl_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(5)

        if "login" not in page.url.lower():
            body = await page.evaluate("document.body.innerText")
            if "iniciar sesión" not in body.lower():
                return True

        logger.info("Sesion SRI expirada, re-login...")
        sri_password = self.settings.sri_password
        if not sri_password:
            logger.error("SRI_PASSWORD no configurada en .env")
            return False

        await page.goto(
            "https://srienlinea.sri.gob.ec/sri-en-linea/inicio/NAT",
            wait_until="networkidle",
            timeout=30000,
        )
        await asyncio.sleep(3)

        # Fill login
        try:
            await page.fill('input[name*="usuario"], input[placeholder*="RUC"], #usuario', self.settings.sri_ruc)
            await page.fill('input[type="password"]', sri_password)
            await page.click('button[type="submit"], .btn-primary')
        except Exception as e:
            logger.error(f"Error llenando login: {e}")
            await self._screenshot(page, "login_error")
            return False

        await asyncio.sleep(8)

        if "login" in page.url.lower():
            await self._screenshot(page, "login_failed")
            return False

        logger.info("Login SRI exitoso")
        return True

    def _notify(self, message: str):
        """Enviar notificacion Telegram."""
        enviar_alerta(
            message,
            token=self.settings.telegram_bot_token,
            chat_id=self.settings.telegram_chat_id,
        )

    # ===================================================================
    # STEP 1: RECONCILE
    # ===================================================================
    async def step_reconcile(self) -> StepResult:
        """Reconciliar depositos Produbanco del mes contra facturas emitidas."""
        logger.info("PASO 1: Reconciliando depositos...")

        try:
            watcher = GmailWatcher(token_path=self.settings.gmail_token_path)
            service = watcher._get_service()

            # Query ALL Produbanco deposit emails for the target month
            ultimo_dia = calendar.monthrange(self.year, self.month)[1]
            query = (
                f"from:bancaenlinea@produbanco.com "
                f"after:{self.year}/{self.month:02d}/01 "
                f"before:{self.year}/{self.month:02d}/{ultimo_dia:02d}"
            )
            result = service.users().messages().list(userId="me", q=query, maxResults=100).execute()
            messages = result.get("messages", [])
            logger.info(f"  Emails encontrados: {len(messages)}")

            deposits = []
            for msg_info in messages:
                msg = service.users().messages().get(
                    userId="me", id=msg_info["id"], format="full"
                ).execute()
                subject = ""
                for h in msg.get("payload", {}).get("headers", []):
                    if h["name"].lower() == "subject":
                        subject = h["value"]
                        break
                html = watcher._extract_html_body(msg.get("payload", {}))
                if html:
                    dep = parsear_deposito(html, subject, msg_info["id"])
                    if dep:
                        deposits.append(dep)

            total_deposited = sum(d.monto for d in deposits)
            logger.info(f"  Depositos parseados: {len(deposits)}, total: ${total_deposited}")

            # Cross-reference against invoices
            fecha_inicio = f"{self.year}-{self.month:02d}-01"
            fecha_fin = f"{self.year}-{self.month:02d}-{ultimo_dia:02d}"
            invoices = (
                self.supabase.table("comprobantes_electronicos")
                .select("subtotal_sin_impuestos, estado, clave_acceso")
                .eq("tipo_comprobante", "01")
                .eq("estado", "authorized")
                .gte("fecha_emision", fecha_inicio)
                .lte("fecha_emision", fecha_fin)
                .execute()
                .data
            )
            total_invoiced = sum(
                Decimal(str(i.get("subtotal_sin_impuestos", 0)))
                for i in invoices
            )
            logger.info(f"  Facturas autorizadas: {len(invoices)}, base total: ${total_invoiced}")

            # Check for already-processed emails
            processed = set()
            try:
                proc_data = (
                    self.supabase.table("gmail_facturas_procesadas")
                    .select("gmail_message_id")
                    .execute()
                    .data
                )
                processed = {p["gmail_message_id"] for p in proc_data}
            except Exception:
                pass

            unmatched = [d for d in deposits if d.gmail_message_id not in processed]
            logger.info(f"  Sin procesar: {len(unmatched)}")

            return StepResult(
                status="completed",
                data={
                    "total_emails": len(messages),
                    "total_deposits": len(deposits),
                    "total_deposited": float(total_deposited),
                    "total_invoices": len(invoices),
                    "total_invoiced": float(total_invoiced),
                    "unmatched": len(unmatched),
                    "unmatched_deposits": unmatched,
                },
            )
        except Exception as e:
            logger.error(f"  Error reconciliando: {e}")
            return StepResult(status="error", error=str(e))

    # ===================================================================
    # STEP 2: GAP INVOICES
    # ===================================================================
    async def step_gap_invoices(self, unmatched: list) -> StepResult:
        """Generar facturas para depositos sin factura."""
        if not unmatched:
            logger.info("PASO 2: No hay gaps, skip")
            return StepResult(status="skipped", data={"reason": "no gaps"})

        if self.dry_run:
            logger.info(f"PASO 2: DRY-RUN - {len(unmatched)} depositos sin factura")
            return StepResult(
                status="skipped",
                data={"reason": "dry-run", "would_invoice": len(unmatched)},
            )

        logger.info(f"PASO 2: Facturando {len(unmatched)} gaps...")
        invoicer = AutoInvoiceService(self.settings, self.supabase)
        generated = 0
        errors = 0

        for dep in unmatched:
            try:
                result = invoicer.procesar_deposito(dep)
                if result.get("estado") in ("authorized", "sent"):
                    generated += 1
                    logger.info(f"  Factura {result.get('numero')}: ${result.get('total')}")
                elif result.get("estado") == "duplicado":
                    logger.info(f"  Duplicado: {dep.gmail_message_id[:20]}")
                else:
                    errors += 1
                    logger.warning(f"  Error: {result}")
            except Exception as e:
                errors += 1
                logger.error(f"  Error procesando deposito: {e}")

        return StepResult(
            status="completed",
            data={"generated": generated, "errors": errors},
        )

    # ===================================================================
    # STEP 3: CALCULATE IVA
    # ===================================================================
    def step_calculate_iva(self) -> StepResult:
        """Calcular IVA del periodo desde la BD."""
        logger.info("PASO 3: Calculando IVA...")

        try:
            calc = CalculadorIVA(self.supabase)
            datos = calc.calcular_periodo(
                anio=self.year,
                mes=self.month,
                ruc=self.settings.sri_ruc,
                razon_social=self.settings.sri_razon_social,
            )

            logger.info(f"  Base imponible: ${datos.ventas_locales_gravadas}")
            logger.info(f"  IVA 15%: ${datos.iva_ventas}")
            logger.info(f"  Facturas: {datos.total_facturas_emitidas}")
            logger.info(datos.to_text())

            return StepResult(
                status="completed",
                data={
                    "base_imponible": float(datos.ventas_locales_gravadas),
                    "iva": float(datos.iva_ventas),
                    "facturas": datos.total_facturas_emitidas,
                    "datos_iva": datos,
                },
            )
        except Exception as e:
            logger.error(f"  Error calculando IVA: {e}")
            return StepResult(status="error", error=str(e))

    # ===================================================================
    # STEP 4: SUBMIT IVA
    # ===================================================================
    async def step_submit_iva(self, datos_iva: DatosDeclaracionIVA) -> StepResult:
        """Declarar IVA en el portal SRI via Patchright."""
        base = str(datos_iva.ventas_locales_gravadas)
        iva = str(datos_iva.iva_ventas)
        logger.info(f"PASO 4: Declarando IVA (base=${base}, iva=${iva})...")

        if datos_iva.ventas_locales_gravadas == 0 and datos_iva.iva_ventas == 0:
            logger.info("  IVA en cero, skip submit")
            return StepResult(status="skipped", data={"reason": "zero IVA"})

        try:
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp("http://localhost:9222")
                context = browser.contexts[0]

                page = None
                for pg in context.pages:
                    if "sri" in pg.url.lower():
                        page = pg
                        break
                if not page:
                    page = context.pages[0] if context.pages else await context.new_page()

                # Ensure SRI session
                if not await self._ensure_sri_session(page):
                    return StepResult(status="error", error="SRI login failed")

                await asyncio.sleep(3)
                await self._screenshot(page, "iva_step1")

                # Select obligation "2011 DECLARACION DE IVA"
                await page.evaluate("""() => {
                    const menus = document.querySelectorAll('.ui-selectonemenu');
                    for (const menu of menus) {
                        const select = menu.querySelector('select');
                        if (select) {
                            const hasIVA = Array.from(select.options).some(o =>
                                o.text.includes('IVA') || o.text.includes('2011'));
                            if (hasIVA) {
                                const trigger = menu.querySelector('.ui-selectonemenu-trigger');
                                if (trigger) trigger.click();
                                return;
                            }
                        }
                    }
                }""")
                await asyncio.sleep(1)
                await page.evaluate("""() => {
                    const panels = document.querySelectorAll('.ui-selectonemenu-panel');
                    for (const panel of panels) {
                        if (panel.offsetHeight > 0) {
                            for (const item of panel.querySelectorAll('li')) {
                                if (item.textContent.includes('IVA') || item.textContent.includes('2011')) {
                                    item.click(); return;
                                }
                            }
                        }
                    }
                }""")
                await asyncio.sleep(3)

                # Select month in MonthPicker
                month_short = MONTH_SHORT[self.month]
                period_str = f"{self.month:02d}/{self.year}"

                await page.evaluate("""() => {
                    const input = document.getElementById('frmFlujoDeclaracion:calPeriodo');
                    if (input) input.click();
                }""")
                await asyncio.sleep(2)

                await page.evaluate(f"""() => {{
                    const mp = document.querySelector('[id*="MonthPicker"]');
                    if (!mp) return;
                    for (const td of mp.querySelectorAll('td')) {{
                        if (td.textContent.trim().toLowerCase() === '{month_short}') {{
                            td.click(); return;
                        }}
                    }}
                }}""")
                await asyncio.sleep(2)

                await page.evaluate(f"""() => {{
                    const input = document.getElementById('frmFlujoDeclaracion:calPeriodo');
                    if (input) {{
                        input.value = '{period_str}';
                        input.dispatchEvent(new Event('change', {{bubbles: true}}));
                    }}
                }}""")
                await asyncio.sleep(2)

                # Step 1 → Step 2
                await self._click_siguiente(page)
                await asyncio.sleep(8)
                await self._handle_dialogs(page)

                body = await page.evaluate("document.body.innerText")
                if "Preguntas" not in body and "informar" not in body.lower():
                    await self._screenshot(page, "iva_not_step2")
                    return StepResult(status="error", error="No llegamos a Step 2")

                # Answer questions: Q0=SI, Q1-Q14=NO
                radio_count = await page.evaluate(
                    "document.querySelectorAll('.ui-radiobutton').length"
                )
                if radio_count == 0:
                    await asyncio.sleep(5)
                    radio_count = await page.evaluate(
                        "document.querySelectorAll('.ui-radiobutton').length"
                    )

                # Q0 = SI
                await page.evaluate("""() => {
                    const radios = document.querySelectorAll('.ui-radiobutton');
                    if (radios.length > 0) {
                        const box = radios[0].querySelector('.ui-radiobutton-box');
                        if (box && !box.classList.contains('ui-state-active')) box.click();
                    }
                }""")
                await asyncio.sleep(4)

                radio_count = await page.evaluate(
                    "document.querySelectorAll('.ui-radiobutton').length"
                )
                for q in range(1, 15):
                    no_idx = q * 2 + 1
                    if no_idx >= radio_count:
                        break
                    await page.evaluate(f"""() => {{
                        const radios = document.querySelectorAll('.ui-radiobutton');
                        if ({no_idx} < radios.length) {{
                            const box = radios[{no_idx}].querySelector('.ui-radiobutton-box');
                            if (box && !box.classList.contains('ui-state-active')) box.click();
                        }}
                    }}""")
                    await asyncio.sleep(0.5)

                await asyncio.sleep(3)
                await self._screenshot(page, "iva_questions")

                # Step 2 → Step 3
                await self._click_siguiente(page)
                await asyncio.sleep(8)
                await self._handle_dialogs(page)

                body = await page.evaluate("document.body.innerText")
                if "VENTAS" not in body and "Formulario" not in body:
                    await self._screenshot(page, "iva_not_step3")
                    return StepResult(status="error", error="No llegamos a Step 3 Formulario")

                # Fill form
                await self._set_field(page, "concepto450", base)
                await asyncio.sleep(2)
                await self._set_field(page, "concepto460", base)
                await asyncio.sleep(2)
                await self._set_field(page, "concepto470", iva)
                await asyncio.sleep(2)
                await self._screenshot(page, "iva_form_filled")

                # Step 3 → Step 4
                await self._click_siguiente(page)
                await asyncio.sleep(8)
                await self._handle_dialogs(page)

                body = await page.evaluate("document.body.innerText")
                if "Total a pagar" not in body:
                    await self._screenshot(page, "iva_not_step4")
                    return StepResult(status="error", error="No llegamos a Step 4 Pago")

                # Extract payment summary
                amounts = await page.evaluate(r"""() => {
                    const text = document.body.innerText;
                    return {
                        impuesto: (text.match(/Impuesto:\s*USD\s*([\d.]+)/) || [])[1] || '?',
                        interes: (text.match(/Interés:\s*USD\s*([\d.]+)/) || [])[1] || '0',
                        multa: (text.match(/Multa:\s*USD\s*([\d.]+)/) || [])[1] || '0',
                        total: (text.match(/Total a pagar:\s*USD\s*([\d.]+)/) || [])[1] || '?'
                    };
                }""")
                logger.info(f"  Impuesto: ${amounts['impuesto']}")
                logger.info(f"  Interes: ${amounts['interes']}")
                logger.info(f"  Multa: ${amounts['multa']}")
                logger.info(f"  TOTAL: ${amounts['total']}")

                await self._screenshot(page, "iva_pago_summary")

                if self.dry_run:
                    logger.info("  DRY-RUN: No se envia la declaracion")
                    return StepResult(
                        status="skipped",
                        data={"reason": "dry-run", "amounts": amounts},
                    )

                # Firma de contador = No
                await page.evaluate("""() => {
                    const radios = document.querySelectorAll('.ui-radiobutton');
                    for (let i = 0; i < radios.length; i++) {
                        const label = radios[i].nextElementSibling;
                        if (label && label.textContent.trim() === 'No') {
                            const box = radios[i].querySelector('.ui-radiobutton-box');
                            if (box && !box.classList.contains('ui-state-active')) box.click();
                            return;
                        }
                    }
                }""")
                await asyncio.sleep(3)

                # Submit
                await self._click_siguiente(page)
                await asyncio.sleep(10)
                await self._handle_dialogs(page)

                body = await page.evaluate("document.body.innerText")
                await self._screenshot(page, "iva_submitted")

                success = "procesada satisfactoriamente" in body.lower()
                if success:
                    logger.info("  IVA declarada exitosamente!")
                else:
                    logger.warning("  IVA: resultado incierto, revisar screenshot")

                return StepResult(
                    status="completed" if success else "error",
                    data={"amounts": amounts, "success": success},
                    error=None if success else "Resultado incierto",
                )

        except Exception as e:
            logger.error(f"  Error en submit IVA: {e}")
            return StepResult(status="error", error=str(e))

    # ===================================================================
    # STEP 5: GENERATE ATS
    # ===================================================================
    def step_generate_ats(self) -> StepResult:
        """Generar ATS XML+ZIP para el periodo."""
        logger.info("PASO 5: Generando ATS...")

        try:
            ultimo_dia = calendar.monthrange(self.year, self.month)[1]
            fecha_inicio = f"{self.year}-{self.month:02d}-01"
            fecha_fin = f"{self.year}-{self.month:02d}-{ultimo_dia:02d}"

            # Query authorized invoices
            facturas = (
                self.supabase.table("comprobantes_electronicos")
                .select(
                    "secuencial, fecha_emision, cliente_tipo_id, "
                    "cliente_identificacion, cliente_razon_social, "
                    "subtotal_15, subtotal_0, iva, importe_total, "
                    "estado, numero_autorizacion"
                )
                .eq("tipo_comprobante", "01")
                .eq("estado", "authorized")
                .gte("fecha_emision", fecha_inicio)
                .lte("fecha_emision", fecha_fin)
                .execute()
                .data
            )

            if not facturas:
                logger.info("  No hay facturas autorizadas para ATS")
                return StepResult(status="skipped", data={"reason": "no invoices"})

            logger.info(f"  Facturas: {len(facturas)}")

            # Group by client
            clientes = {}
            for f in facturas:
                cid = f.get("cliente_identificacion", "9999999999999")
                if cid not in clientes:
                    clientes[cid] = {
                        "tipo_id": f.get("cliente_tipo_id", "07"),
                        "identificacion": cid,
                        "base_15": Decimal("0"),
                        "base_0": Decimal("0"),
                        "iva": Decimal("0"),
                        "num_comprobantes": 0,
                    }
                clientes[cid]["base_15"] += Decimal(str(f.get("subtotal_15", 0) or 0))
                clientes[cid]["base_0"] += Decimal(str(f.get("subtotal_0", 0) or 0))
                clientes[cid]["iva"] += Decimal(str(f.get("iva", 0) or 0))
                clientes[cid]["num_comprobantes"] += 1

            ventas = []
            for cid, c in clientes.items():
                ventas.append(
                    DetalleVenta(
                        tipo_comprobante=TipoComprobanteATS.FACTURA_ELECTRONICA,
                        tipo_id_cliente=c["tipo_id"],
                        id_cliente=cid,
                        parte_relacionada="NO",
                        base_imponible_15=c["base_15"],
                        base_imponible_0=c["base_0"],
                        monto_iva=c["iva"],
                        numero_comprobantes=c["num_comprobantes"],
                    )
                )

            # Query cancelled invoices
            anulados_data = (
                self.supabase.table("comprobantes_electronicos")
                .select("secuencial, numero_autorizacion")
                .eq("tipo_comprobante", "01")
                .eq("estado", "cancelled")
                .gte("fecha_emision", fecha_inicio)
                .lte("fecha_emision", fecha_fin)
                .execute()
                .data
            )
            anulados = [
                DetalleAnulado(
                    tipo_comprobante=TipoComprobanteATS.FACTURA_ELECTRONICA,
                    establecimiento=self.settings.sri_establecimiento,
                    punto_emision=self.settings.sri_punto_emision,
                    secuencial_inicio=a["secuencial"],
                    secuencial_fin=a["secuencial"],
                    autorizacion=a.get("numero_autorizacion", ""),
                )
                for a in anulados_data
            ]

            # Build ATS
            total_ventas = sum(
                v.base_imponible_15 + v.base_imponible_0 + v.monto_iva
                for v in ventas
            )
            ats = ATS(
                tipo_id_informante="R",
                id_informante=self.settings.sri_ruc,
                razon_social=self.settings.sri_razon_social,
                anio=self.year,
                mes=self.month,
                num_estab_ruc="001",
                codigo_operativo="IVA",
                ventas=ventas,
                anulados=anulados,
                ventas_establecimiento=[
                    VentaEstablecimiento(
                        cod_estab=self.settings.sri_establecimiento,
                        ventas_estab=total_ventas,
                    )
                ],
            )

            builder = ATSBuilder()
            xml_content = builder.build(ats)

            # Save XML and ZIP
            ATS_DIR.mkdir(parents=True, exist_ok=True)
            xml_path = ATS_DIR / f"ATS_{self.month:02d}_{self.year}.xml"
            zip_path = ATS_DIR / f"ATS_{self.month:02d}_{self.year}.zip"

            xml_path.write_text(xml_content, encoding="ISO-8859-1")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(xml_path, xml_path.name)

            logger.info(f"  ATS generado: {zip_path}")
            logger.info(f"  Ventas: {len(ventas)} clientes, Anulados: {len(anulados)}")

            return StepResult(
                status="completed",
                data={
                    "zip_path": str(zip_path),
                    "xml_path": str(xml_path),
                    "num_ventas": len(ventas),
                    "num_facturas": len(facturas),
                    "num_anulados": len(anulados),
                },
            )
        except Exception as e:
            logger.error(f"  Error generando ATS: {e}")
            return StepResult(status="error", error=str(e))

    # ===================================================================
    # STEP 6: SUBMIT ATS
    # ===================================================================
    async def step_submit_ats(self, zip_path: str) -> StepResult:
        """Subir ATS ZIP al portal SRI."""
        logger.info(f"PASO 6: Subiendo ATS {zip_path}...")

        if self.dry_run:
            logger.info("  DRY-RUN: No se sube el ATS")
            return StepResult(status="skipped", data={"reason": "dry-run"})

        if not Path(zip_path).exists():
            return StepResult(status="error", error=f"ZIP no encontrado: {zip_path}")

        try:
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp("http://localhost:9222")
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else await context.new_page()

                # Navigate to ATS upload portal
                ats_url = "https://srienlinea.sri.gob.ec/sri-en-linea/SriAnexos/EnvioConsulta/envioConsulta"
                await page.goto(ats_url, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(5)

                # Check session
                if "login" in page.url.lower():
                    if not await self._ensure_sri_session(page):
                        return StepResult(status="error", error="SRI login failed for ATS")
                    await page.goto(ats_url, wait_until="networkidle", timeout=30000)
                    await asyncio.sleep(5)

                await self._screenshot(page, "ats_portal")

                # Find file upload input and upload
                file_input = await page.query_selector('input[type="file"]')
                if file_input:
                    await file_input.set_input_files(zip_path)
                    await asyncio.sleep(5)
                    await self._screenshot(page, "ats_file_selected")

                    # Click upload/send button
                    await page.evaluate("""() => {
                        for (const b of document.querySelectorAll('button, .ui-button')) {
                            const t = b.textContent.trim().toLowerCase();
                            if ((t.includes('cargar') || t.includes('enviar') || t.includes('subir'))
                                && b.offsetHeight > 0) {
                                b.click(); return;
                            }
                        }
                    }""")
                    await asyncio.sleep(10)
                    await self._handle_dialogs(page)
                    await self._screenshot(page, "ats_uploaded")

                    body = await page.evaluate("document.body.innerText")
                    success = "procesado" in body.lower() or "recibido" in body.lower()

                    return StepResult(
                        status="completed" if success else "error",
                        data={"success": success},
                        error=None if success else "ATS upload resultado incierto",
                    )
                else:
                    await self._screenshot(page, "ats_no_file_input")
                    return StepResult(status="error", error="No se encontro input de archivo")

        except Exception as e:
            logger.error(f"  Error subiendo ATS: {e}")
            return StepResult(status="error", error=str(e))

    # ===================================================================
    # STEP 7: NOTIFY
    # ===================================================================
    def step_notify(self) -> StepResult:
        """Enviar resumen por Telegram."""
        logger.info("PASO 7: Notificando...")

        lines = [
            f"DECLARACION MENSUAL {self.month:02d}/{self.year}",
            "",
        ]

        for step_name, result in self.results.items():
            status_icon = {"completed": "+", "skipped": "~", "error": "X"}.get(
                result.status, "?"
            )
            lines.append(f"[{status_icon}] {step_name}: {result.status}")
            if result.data:
                for k, v in result.data.items():
                    if k not in ("datos_iva", "unmatched_deposits") and v:
                        lines.append(f"    {k}: {v}")
            if result.error:
                lines.append(f"    ERROR: {result.error[:100]}")

        if self.dry_run:
            lines.append("\n(DRY-RUN - no se envio nada al SRI)")

        message = "\n".join(lines)
        logger.info(f"\n{message}")
        self._notify(message)

        return StepResult(status="completed")

    # ===================================================================
    # MAIN RUN
    # ===================================================================
    async def run(self, only_steps: list[str] | None = None):
        """Ejecutar el pipeline completo o pasos seleccionados."""
        logger.info(f"{'DRY-RUN ' if self.dry_run else ''}Pipeline {self.month:02d}/{self.year}")
        logger.info("=" * 60)

        steps_to_run = only_steps or STEPS
        unmatched = []
        datos_iva = None
        zip_path = None

        for step_name in STEPS:
            if step_name not in steps_to_run:
                continue

            # Check if already completed in state
            if (
                step_name in self.state.get("steps", {})
                and self.state["steps"][step_name].get("status") == "completed"
                and not only_steps  # If explicit steps, always re-run
            ):
                logger.info(f"  {step_name}: ya completado, skip")
                continue

            try:
                if step_name == "reconcile":
                    result = await self.step_reconcile()
                    if result.status == "completed":
                        unmatched = result.data.get("unmatched_deposits", [])

                elif step_name == "gap_invoices":
                    result = await self.step_gap_invoices(unmatched)

                elif step_name == "calculate_iva":
                    result = self.step_calculate_iva()
                    if result.status == "completed":
                        datos_iva = result.data.get("datos_iva")

                elif step_name == "submit_iva":
                    if not datos_iva:
                        # Calculate first if not done
                        calc_result = self.step_calculate_iva()
                        if calc_result.status == "completed":
                            datos_iva = calc_result.data.get("datos_iva")
                    if datos_iva:
                        result = await self.step_submit_iva(datos_iva)
                    else:
                        result = StepResult(status="error", error="No IVA data")

                elif step_name == "generate_ats":
                    result = self.step_generate_ats()
                    if result.status == "completed":
                        zip_path = result.data.get("zip_path")

                elif step_name == "submit_ats":
                    if not zip_path:
                        # Generate first if not done
                        gen_result = self.step_generate_ats()
                        if gen_result.status == "completed":
                            zip_path = gen_result.data.get("zip_path")
                    if zip_path:
                        result = await self.step_submit_ats(zip_path)
                    else:
                        result = StepResult(status="error", error="No ATS ZIP")

                elif step_name == "notify":
                    result = self.step_notify()

                else:
                    continue

                self.results[step_name] = result
                self.state["steps"][step_name] = {
                    "status": result.status,
                    "error": result.error,
                    "data": {
                        k: v
                        for k, v in (result.data or {}).items()
                        if k not in ("datos_iva", "unmatched_deposits")
                    },
                }
                self._save_state()

                if result.status == "error" and step_name in ("calculate_iva",):
                    logger.error(f"  Paso critico falló: {step_name}. Abortando.")
                    self._notify(
                        f"ERROR CRITICO en {step_name} para {self.month:02d}/{self.year}: "
                        f"{result.error}"
                    )
                    break

            except Exception as e:
                logger.error(f"  Excepcion en {step_name}: {e}")
                self.results[step_name] = StepResult(status="error", error=str(e))
                self._notify(f"EXCEPCION en {step_name}: {str(e)[:200]}")

        logger.info("=" * 60)
        logger.info("Pipeline completado")


def parse_args():
    parser = argparse.ArgumentParser(description="ECUCONDOR - Automatizacion Tributaria Mensual")
    parser.add_argument("year", nargs="?", type=int, help="Año (ej: 2026)")
    parser.add_argument("month", nargs="?", type=int, help="Mes (1-12)")
    parser.add_argument("--auto", action="store_true", help="Mes anterior automatico")
    parser.add_argument("--dry-run", action="store_true", help="Solo calcular, no enviar al SRI")
    parser.add_argument("--step", action="append", dest="steps", help="Ejecutar solo paso(s) especifico(s)")
    return parser.parse_args()


def setup_logging(year: int, month: int):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"tax_monthly_{year}_{month:02d}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main():
    args = parse_args()

    if args.auto or (args.year is None and args.month is None):
        now = datetime.now(ECUADOR_TZ)
        if now.month == 1:
            year, month = now.year - 1, 12
        else:
            year, month = now.year, now.month - 1
    else:
        year = args.year
        month = args.month

    if not year or not month or month < 1 or month > 12:
        print("Uso: python scripts/tax_monthly.py [YEAR MONTH] [--auto] [--dry-run] [--step STEP]")
        return 1

    setup_logging(year, month)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    orchestrator = TaxMonthlyOrchestrator(year, month, dry_run=args.dry_run)
    asyncio.run(orchestrator.run(only_steps=args.steps))
    return 0


if __name__ == "__main__":
    sys.exit(main())
