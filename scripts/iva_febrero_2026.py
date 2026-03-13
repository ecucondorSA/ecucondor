#!/usr/bin/env python3
"""
IVA FEBRERO 2026 - FLUJO COMPLETO
Navigate to declarations, select Feb 2026, fill form with $147.42 base, submit.
"""

import asyncio
import base64
import sys
from pathlib import Path

from patchright.async_api import async_playwright

SCREENSHOT_DIR = Path("/home/edu/ecucondor/output/screenshots")
STEP = [100]

# February 2026 values from authorized invoices
BASE_IMPONIBLE = "147.42"
IVA_15 = "22.09"


async def ss(page, name):
    STEP[0] += 1
    path = SCREENSHOT_DIR / f"ivafeb_{STEP[0]:03d}_{name}.png"
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
    print(f"    [ss] {path.name}")
    return path


async def handle_dialogs(page):
    for _ in range(5):
        dialog = await page.evaluate("""() => {
            const dialogs = document.querySelectorAll('.ui-dialog');
            for (const d of dialogs) {
                if (d.offsetHeight > 0 && d.style.display !== 'none' &&
                    d.querySelector('.ui-dialog-content')) {
                    return {
                        visible: true,
                        text: d.querySelector('.ui-dialog-content').textContent.trim().substring(0, 500),
                        title: d.querySelector('.ui-dialog-title') ?
                               d.querySelector('.ui-dialog-title').textContent.trim() : '',
                        buttons: Array.from(d.querySelectorAll('button')).map(b => b.textContent.trim())
                    };
                }
            }
            return {visible: false};
        }""")
        if not dialog.get('visible'):
            return
        print(f"    Dialog: [{dialog.get('title','')}] {dialog['text'][:200]}")
        print(f"    Buttons: {dialog.get('buttons', [])}")
        await page.evaluate("""() => {
            const dialogs = document.querySelectorAll('.ui-dialog');
            for (const d of dialogs) {
                if (d.offsetHeight > 0 && d.style.display !== 'none') {
                    const btns = d.querySelectorAll('button');
                    for (const b of btns) {
                        const t = b.textContent.trim().toLowerCase();
                        if (['sí','si','aceptar','continuar','ok','enviar'].includes(t)) {
                            b.click(); return;
                        }
                    }
                }
            }
        }""")
        await asyncio.sleep(5)


async def set_field(page, field_id, value):
    result = await page.evaluate(f"""(val) => {{
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
        return 'ok: ' + val;
    }}""", str(value))
    return result


async def click_siguiente(page):
    await page.evaluate("""() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
            if (b.textContent.trim().includes('Siguiente') && b.offsetHeight > 0) {
                b.click(); return;
            }
        }
    }""")


async def main():
    print("=" * 60)
    print("IVA FEBRERO 2026 - DECLARACIÓN COMPLETA")
    print(f"  Base: ${BASE_IMPONIBLE}  IVA: ${IVA_15}")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]

        # Find SRI tab
        page = None
        for pg in context.pages:
            if "sri" in pg.url.lower():
                page = pg
                break
        if not page:
            print("ERROR: No SRI tab")
            return 1

        # ===== Navigate to declarations =====
        print("\n[1] Navegando a declaraciones...")
        decl_url = "https://srienlinea.sri.gob.ec/sri-declaraciones-web-internet/pages/recepcion/recibirDeclaracion.jsf"
        await page.goto(decl_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(5)

        body = await page.evaluate("document.body.innerText")
        if "login" in page.url.lower() or "iniciar sesión" in body.lower():
            print("  ERROR: Sesión expirada, hacer login manualmente")
            await ss(page, "login_needed")
            return 1

        print(f"  URL: {page.url[:80]}")
        await ss(page, "step1")

        # ===== STEP 1: Select obligation + period =====
        print("\n[2] Seleccionando obligación IVA...")
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
                    const items = panel.querySelectorAll('li');
                    for (const item of items) {
                        if (item.textContent.includes('IVA') || item.textContent.includes('2011')) {
                            item.click(); return;
                        }
                    }
                }
            }
        }""")
        await asyncio.sleep(3)

        # Select FEBRUARY in MonthPicker
        print("\n[3] Seleccionando período FEBRERO 2026...")
        await page.evaluate("""() => {
            const input = document.getElementById('frmFlujoDeclaracion:calPeriodo');
            if (input) input.click();
        }""")
        await asyncio.sleep(2)

        # Click "Feb" in MonthPicker
        clicked = await page.evaluate("""() => {
            const mp = document.querySelector('[id*="MonthPicker"]');
            if (!mp) return 'no monthpicker';
            const tds = mp.querySelectorAll('td');
            for (const td of tds) {
                const text = td.textContent.trim().toLowerCase();
                if (text === 'feb' || text === 'febrero') {
                    td.click();
                    return 'clicked: ' + td.textContent.trim();
                }
            }
            return 'feb not found. TDs: ' + Array.from(tds).map(td => td.textContent.trim()).join(', ');
        }""")
        print(f"    {clicked}")
        await asyncio.sleep(2)

        # Force set value
        await page.evaluate("""() => {
            const input = document.getElementById('frmFlujoDeclaracion:calPeriodo');
            if (input) {
                input.value = '02/2026';
                input.dispatchEvent(new Event('change', {bubbles: true}));
            }
        }""")
        await asyncio.sleep(2)

        # Verify period
        period_val = await page.evaluate("""() => {
            const input = document.getElementById('frmFlujoDeclaracion:calPeriodo');
            return input ? input.value : 'not found';
        }""")
        print(f"    Período: {period_val}")
        await ss(page, "period_selected")

        # Click Siguiente → Step 2
        print("\n[4] STEP 1 → STEP 2 (Preguntas)...")
        await click_siguiente(page)
        await asyncio.sleep(8)
        await handle_dialogs(page)

        body = await page.evaluate("document.body.innerText")
        on_step2 = "Preguntas" in body or "informar" in body.lower()
        print(f"    On Step 2: {on_step2}")

        if not on_step2:
            print(f"    Body: {body[:300]}")
            await ss(page, "not_step2")
            return 1

        await ss(page, "step2")

        # ===== STEP 2: Set questions =====
        print("\n[5] Configurando preguntas...")
        radio_count = await page.evaluate("document.querySelectorAll('.ui-radiobutton').length")
        print(f"    Radios: {radio_count}")

        if radio_count == 0:
            await asyncio.sleep(5)
            radio_count = await page.evaluate("document.querySelectorAll('.ui-radiobutton').length")
            print(f"    Radios after wait: {radio_count}")

        # Q0 = SÍ (informar valores)
        print("    Q0 = SÍ (informar valores)...")
        await page.evaluate("""() => {
            const radios = document.querySelectorAll('.ui-radiobutton');
            if (radios.length > 0) {
                const box = radios[0].querySelector('.ui-radiobutton-box');
                if (box && !box.classList.contains('ui-state-active')) box.click();
            }
        }""")
        await asyncio.sleep(4)

        # Re-count after Q0=Sí
        radio_count = await page.evaluate("document.querySelectorAll('.ui-radiobutton').length")
        print(f"    Radios after Q0=Sí: {radio_count}")

        # All other questions = NO
        print("    Setting Q1-Q14 = NO...")
        for q in range(1, 15):
            no_idx = q * 2 + 1
            if no_idx >= radio_count:
                break
            await page.evaluate(f"""() => {{
                const radios = document.querySelectorAll('.ui-radiobutton');
                const idx = {no_idx};
                if (idx < radios.length) {{
                    const box = radios[idx].querySelector('.ui-radiobutton-box');
                    if (box && !box.classList.contains('ui-state-active')) box.click();
                }}
            }}""")
            await asyncio.sleep(0.5)

        await asyncio.sleep(3)

        # Verify
        unanswered = await page.evaluate("""() => {
            const radios = document.querySelectorAll('.ui-radiobutton');
            let unanswered = 0;
            for (let i = 0; i < radios.length; i += 2) {
                const si = radios[i]?.querySelector('.ui-radiobutton-box');
                const no = radios[i+1]?.querySelector('.ui-radiobutton-box');
                if (!si?.classList.contains('ui-state-active') && !no?.classList.contains('ui-state-active')) {
                    unanswered++;
                }
            }
            return unanswered;
        }""")
        print(f"    Sin responder: {unanswered}")

        if unanswered > 0:
            print("    WARNING: Hay preguntas sin responder!")

        await ss(page, "questions_done")

        # Click Siguiente → Step 3
        print("\n[6] STEP 2 → STEP 3 (Formulario)...")
        await click_siguiente(page)
        await asyncio.sleep(8)
        await handle_dialogs(page)

        body = await page.evaluate("document.body.innerText")
        on_step3 = "Formulario" in body and ("VENTAS" in body or "TOTALES" in body)
        print(f"    On Step 3: {on_step3}")

        if not on_step3:
            if "sin transaccionalidad" in body.lower():
                print("    ERROR: Sin transaccionalidad - bounced back")
            print(f"    Body: {body[:400]}")
            await ss(page, "not_step3")
            return 1

        await ss(page, "step3")

        # ===== STEP 3: Fill form =====
        print("\n[7] Llenando formulario...")

        # Check if SRI pre-filled values
        prefilled = await page.evaluate("""() => {
            const c450 = document.getElementById('concepto450');
            return c450 ? c450.value : 'not found';
        }""")
        print(f"    concepto450 pre-filled: {prefilled}")

        if prefilled != '0.00' and prefilled != 'not found':
            print(f"    SRI pre-filled with: {prefilled}")
            # Use pre-filled values
        else:
            # Fill manually
            r = await set_field(page, "concepto450", BASE_IMPONIBLE)
            print(f"    concepto450 (401 bruto) = {r}")
            await asyncio.sleep(2)

            r = await set_field(page, "concepto460", BASE_IMPONIBLE)
            print(f"    concepto460 (411 neto)  = {r}")
            await asyncio.sleep(2)

            r = await set_field(page, "concepto470", IVA_15)
            print(f"    concepto470 (421 IVA)   = {r}")
            await asyncio.sleep(2)

        # Verify values
        vals = await page.evaluate("""() => ({
            c450: document.getElementById('concepto450')?.value,
            c460: document.getElementById('concepto460')?.value,
            c470: document.getElementById('concepto470')?.value
        })""")
        print(f"\n    Valores finales:")
        print(f"      401 (bruto): ${vals.get('c450')}")
        print(f"      411 (neto):  ${vals.get('c460')}")
        print(f"      421 (IVA):   ${vals.get('c470')}")

        await ss(page, "form_filled")

        # Click Siguiente → Step 4
        print("\n[8] STEP 3 → STEP 4 (Pago)...")
        await click_siguiente(page)
        await asyncio.sleep(8)
        await handle_dialogs(page)

        body = await page.evaluate("document.body.innerText")
        on_step4 = "Total a pagar" in body or "Pago" in body
        print(f"    On Step 4: {on_step4}")

        if not on_step4:
            print(f"    Body: {body[:400]}")
            await ss(page, "not_step4")
            return 1

        await ss(page, "step4_top")

        # Extract payment summary
        amounts = await page.evaluate(r"""() => {
            const text = document.body.innerText;
            const result = {};
            const impMatch = text.match(/Impuesto:\s*USD\s*([\d.]+)/);
            const intMatch = text.match(/Interés:\s*USD\s*([\d.]+)/);
            const mulMatch = text.match(/Multa:\s*USD\s*([\d.]+)/);
            const totMatch = text.match(/Total a pagar:\s*USD\s*([\d.]+)/);
            if (impMatch) result.impuesto = impMatch[1];
            if (intMatch) result.interes = intMatch[1];
            if (mulMatch) result.multa = mulMatch[1];
            if (totMatch) result.total = totMatch[1];
            return result;
        }""")

        print(f"\n    Resumen de pago:")
        print(f"      Impuesto: ${amounts.get('impuesto', '?')}")
        print(f"      Interés:  ${amounts.get('interes', '?')}")
        print(f"      Multa:    ${amounts.get('multa', '?')}")
        print(f"      TOTAL:    ${amounts.get('total', '?')}")

        # Answer "No" to firma de contador
        print("\n[9] Firma de contador = No...")
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

        await ss(page, "firma_no")

        # Click Siguiente to submit
        print("\n[10] Siguiente (enviar declaración)...")
        await click_siguiente(page)
        await asyncio.sleep(10)

        await ss(page, "after_submit")

        # Handle confirmation dialogs
        await handle_dialogs(page)

        body = await page.evaluate("document.body.innerText")
        await ss(page, "final")

        # Check result
        print(f"\n[11] Resultado:")
        lines = body.split('\n')
        for line in lines:
            line = line.strip()
            if line and len(line) > 2 and len(line) < 200:
                lower = line.lower()
                if any(kw in lower for kw in ['enviar', 'pago', 'débito', 'convenio', 'forma',
                                                'impuesto', 'total', 'multa', 'interés',
                                                'declaración', 'confirmación', 'firma',
                                                'recibida', 'procesada', 'exitosa', 'acuerdo',
                                                '147', '22.09', 'banco', 'cuenta']):
                    print(f"    >>> {line}")

        # Check for visible buttons
        btns = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('button, .ui-button'))
                .filter(b => b.offsetHeight > 0)
                .map(b => ({text: b.textContent.trim(), id: b.id}));
        }""")
        print(f"\n  Botones: {[b['text'] for b in btns]}")

        # Check for radio/dropdown (payment method)
        radios = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('.ui-radiobutton'))
                .filter(r => r.offsetHeight > 0)
                .map((r, i) => ({
                    i: i,
                    label: r.nextElementSibling ? r.nextElementSibling.textContent.trim() : '',
                    active: r.querySelector('.ui-radiobutton-box')?.classList.contains('ui-state-active') || false
                }));
        }""")
        if radios:
            print(f"\n  Radio buttons:")
            for r in radios:
                marker = " <<ACTIVE>>" if r['active'] else ""
                print(f"    [{r['i']}] '{r['label']}'{marker}")

        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1)
        await ss(page, "final_scroll")

        print(f"\n  Screenshots en: {SCREENSHOT_DIR}")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
