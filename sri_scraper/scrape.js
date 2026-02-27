const puppeteer = require('puppeteer');
const fs = require('fs');

(async () => {
    console.log('🔗 Iniciando navegador...');
    const browser = await puppeteer.launch({
        headless: "new",
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    const page = await browser.newPage();

    try {
        console.log('🌐 Navegando a srienlinea.sri.gob.ec...');
        await page.goto('https://srienlinea.sri.gob.ec/sri-en-linea/inicio/NAT', { waitUntil: 'networkidle2' });

        // Intentar hacer clic en el botón de Iniciar Sesión (ícono de candado o texto)
        console.log('🔑 Buscando botón de login...');
        const btnLogin = await page.$('a[title="Iniciar sesión"], button[title="Iniciar sesión"], a.ui-commandlink, .login-button-class');

        if (btnLogin) {
            await btnLogin.click();
            await page.waitForTimeout(2000);
        } else {
            console.log("No se encontró botón explícito, yendo directo a URL de login auth");
            await page.goto('https://srienlinea.sri.gob.ec/auth/realms/Internet/protocol/openid-connect/auth?client_id=sri-en-linea&redirect_uri=https://srienlinea.sri.gob.ec/sri-en-linea/inicio/NAT&response_mode=fragment&response_type=code&scope=openid', { waitUntil: 'networkidle2' });
        }

        console.log('✍️ Ingresando credenciales...');
        await page.waitForSelector('input[name="username"]', { visible: true });
        await page.type('input[name="username"]', '1391937000001');
        await page.type('input[name="password"]', 'Ecu081223.');

        await Promise.all([
            page.waitForNavigation({ waitUntil: 'networkidle0' }),
            page.click('input[name="login"], button.ui-button, button[id="kc-login"]')
        ]);

        console.log('✅ Login exitoso. Navegando a Obligaciones Pendientes...');

        // URL directa a las deudas/obligaciones pendientes. Depende de la estructura del SRI
        // Generalmente es un hash router, o hay que ir por el menú lateral
        await page.goto('https://srienlinea.sri.gob.ec/sri-en-linea/SriDeclaracionesWeb/ObligacionesPendientes/Consultas/consultaObligaciones', { waitUntil: 'networkidle2' });

        await page.waitForTimeout(3000);

        // Sacar screenshot explicativo para el usuario o debug
        await page.screenshot({ path: 'sri_dashboard.png', fullPage: true });

        // Extraer la tabla de obligaciones si existe
        console.log('📊 Extrayendo tabla de datos...');
        const resultados = await page.evaluate(() => {
            const filas = Array.from(document.querySelectorAll('table tbody tr'));
            if (filas.length === 0) return { error: "No se encontraron tablas de datos" };

            return filas.map(fila => {
                const celdas = Array.from(fila.querySelectorAll('td'));
                return celdas.map(celda => celda.innerText.trim());
            });
        });

        console.log('📝 Resultados guardados en resultados_sri.json');
        fs.writeFileSync('resultados_sri.json', JSON.stringify(resultados, null, 2));
        console.log(resultados);

    } catch (error) {
        console.error('❌ Error en el scraper:', error);
        await page.screenshot({ path: 'error_sri.png' });
    } finally {
        await browser.close();
    }
})();
