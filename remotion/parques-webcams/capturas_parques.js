// capturas_parques.js — Canal Meteo · capturas de cámaras de parques en lote
// ═══════════════════════════════════════════════════════════════════════════
// 12/09/2026: `remotion still` recompila el proyecto ENTERO con webpack en cada
// llamada (~6 s de los ~7 s que tarda cada imagen). Con 15 parques × 4 variantes
// eso eran 60 compilaciones y ~10 min de ciclo. Aquí se compila UNA vez, se abre
// UN Chrome y se sacan todas las capturas reutilizando ambos.
//
// Uso:  node capturas_parques.js trabajos.json
//   trabajos.json = [{"code":"yose","lang":"es","comp":"Mockup-camara","out":"/ruta.jpg"}, ...]
// Salida: una línea JSON por trabajo → {"out":..., "ok":true|false, "ms":1234, "error":"..."}
// Lo llama scripts/parques_lynx.py, que sigue decidiendo qué renderizar y subiendo.

const fs = require('fs');
const path = require('path');
const {bundle} = require('@remotion/bundler');
const {selectComposition, renderStill, openBrowser} = require('@remotion/renderer');

const RAIZ = __dirname;
const ENTRADA = path.join(RAIZ, 'src', 'index.ts');
const PUBLIC_DIR = path.join(RAIZ, 'public');
const CACHE_BUNDLE = '/opt/canalmeteo/data/temp/bundle-parques';

const ficheroTrabajos = process.argv[2];
if (!ficheroTrabajos) {
    console.error('falta el JSON de trabajos');
    process.exit(2);
}
const trabajos = JSON.parse(fs.readFileSync(ficheroTrabajos, 'utf8'));
if (!Array.isArray(trabajos) || trabajos.length === 0) {
    console.error('sin trabajos');
    process.exit(0);
}

const CHROMIUM = {gl: 'vulkan', headless: true};
// 4.0.452: sin logLevel, selectComposition/renderStill revientan con
// "Cannot destructure property 'silent' of 'undefined'".
const LOG = 'error';

(async () => {
    const t0 = Date.now();
    // 1) UNA sola compilación para todas las capturas
    const serveUrl = await bundle({
        entryPoint: ENTRADA,
        publicDir: PUBLIC_DIR,
        outDir: CACHE_BUNDLE,
        onProgress: () => {},
    });
    const tBundle = Date.now() - t0;
    console.error(`[capturas] bundle en ${(tBundle / 1000).toFixed(1)} s`);

    // 2) UN solo navegador para todas
    const browser = await openBrowser('chrome', {chromiumOptions: CHROMIUM, logLevel: LOG});
    console.error(`[capturas] navegador abierto (+${((Date.now() - t0 - tBundle) / 1000).toFixed(1)} s)`);

    let ok = 0;
    let fallos = 0;
    for (const t of trabajos) {
        const ti = Date.now();
        const inputProps = {code: t.code, lang: t.lang};
        try {
            // La composición se re-selecciona por trabajo porque calculateMetadata
            // baja los datos de ESA cámara (foto, METAR, radar) según inputProps.
            const composition = await selectComposition({serveUrl, id: t.comp, inputProps, logLevel: LOG});
            await renderStill({
                composition,
                serveUrl,
                output: t.out,
                frame: t.frame ?? 180,
                inputProps,
                imageFormat: 'jpeg',
                jpegQuality: t.quality ?? 85,
                scale: t.scale ?? 0.6667,
                puppeteerInstance: browser,
                chromiumOptions: CHROMIUM,
                logLevel: LOG,
            });
            ok++;
            console.log(JSON.stringify({out: t.out, ok: true, ms: Date.now() - ti}));
        } catch (e) {
            fallos++;
            console.log(JSON.stringify({
                out: t.out,
                ok: false,
                ms: Date.now() - ti,
                error: String(e && e.message ? e.message : e).slice(0, 200),
            }));
        }
    }

    try {
        await browser.close();
    } catch (e) {
        // close() revienta con el mismo bug de opciones; da igual, ya hemos terminado
    }
    console.error(`[capturas] ${ok} ok, ${fallos} fallos · total ${((Date.now() - t0) / 1000).toFixed(1)} s`);
    process.exit(fallos ? 1 : 0);
})().catch((e) => {
    console.error('[capturas] ERROR general:', e && e.message ? e.message : e);
    process.exit(2);
});
