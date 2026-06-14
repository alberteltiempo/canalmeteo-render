// capturar-playwright.js — v2 (paralelo, pool de 3 pestañas)
//
// Recibe vía env var HTMLS_TO_CAPTURE un JSON array:
//   HTMLS_TO_CAPTURE='[{"in":"/path/in.html","out":"/path/out.png"},...]'
//
// Mejora vs v1: procesa capturas en paralelo (concurrency=3) reusando
// el mismo browser. Reduce ~3x el tiempo total cuando hay >3 alertas.

const { chromium } = require('playwright');

const TIMEOUT             = 60000;
const VIEWPORT            = { width: 1280, height: 2100 };
const NET_IDLE_TIMEOUT    = 8000;
const CM_READY_TIMEOUT    = 15000;
const SETTLE_BEFORE_SHOT  = 500;
const CONCURRENCY         = 3;  // 3 pestañas paralelas

const PAIRS_JSON = process.env.HTMLS_TO_CAPTURE;
if (!PAIRS_JSON) {
  console.error('❌ HTMLS_TO_CAPTURE no definido.');
  process.exit(1);
}

let pairs;
try {
  pairs = JSON.parse(PAIRS_JSON);
} catch (e) {
  console.error('❌ HTMLS_TO_CAPTURE inválido:', e.message);
  process.exit(1);
}

if (!Array.isArray(pairs) || pairs.length === 0) {
  console.error('❌ HTMLS_TO_CAPTURE vacío.');
  process.exit(1);
}

async function capturePair(pair, page, workerId) {
  const inputPath  = pair.in;
  const outputPath = pair.out;

  if (!inputPath || !outputPath) {
    console.warn(`[w${workerId}] ⚠️ Par inválido: ${JSON.stringify(pair)}`);
    return false;
  }

  const fileUrl = inputPath.startsWith('file://') ? inputPath : `file://${inputPath}`;
  const shortName = inputPath.split('/').pop();
  console.log(`[w${workerId}] 🌐 ${shortName}`);

  try {
    await page.goto(fileUrl, { waitUntil: 'domcontentloaded', timeout: TIMEOUT });
  } catch (e) {
    console.error(`[w${workerId}] ❌ goto error: ${e.message}`);
    return false;
  }

  try {
    await page.waitForLoadState('networkidle', { timeout: NET_IDLE_TIMEOUT });
  } catch { /* ok */ }

  // Esperar flag _cmMapReady (HTMLs con mapa); HTMLs sin mapa caen al timeout silenciosamente
  let hasMap = false;
  try {
    await page.waitForFunction(() => window._cmMapReady === true, null, { timeout: CM_READY_TIMEOUT });
    hasMap = true;
  } catch { /* sin mapa, ok */ }

  await page.waitForTimeout(SETTLE_BEFORE_SHOT);

  const container = page.locator('.contenedor-sismo').first();
  const count = await container.count();
  if (count === 0) {
    console.warn(`[w${workerId}] ⚠️ Sin .contenedor-sismo: ${shortName}`);
    return false;
  }

  try {
    await container.screenshot({ path: outputPath });
    console.log(`[w${workerId}] 🖼️  ${outputPath.split('/').pop()}${hasMap ? '' : ' (sin-mapa)'}`);
    return true;
  } catch (e) {
    console.error(`[w${workerId}] ❌ screenshot error: ${e.message}`);
    return false;
  }
}

(async () => {
  console.log(`📦 ${pairs.length} captura(s), concurrencia=${CONCURRENCY}`);
  const startedAt = Date.now();

  const browser = await chromium.launch({
    headless: true,
    args: [
      '--use-gl=swiftshader',
      '--enable-webgl',
      '--enable-accelerated-2d-canvas',
      '--ignore-gpu-blocklist',
      '--no-sandbox',
      '--disable-dev-shm-usage',
    ],
  });

  const queue = [...pairs];
  let ok = 0, fail = 0;

  async function worker(workerId) {
    const page = await browser.newPage({ viewport: VIEWPORT, deviceScaleFactor: 1 });
    try {
      while (queue.length > 0) {
        const pair = queue.shift();
        if (!pair) break;
        const success = await capturePair(pair, page, workerId);
        if (success) ok++; else fail++;
      }
    } finally {
      await page.close().catch(() => {});
    }
  }

  const workers = Array.from({ length: Math.min(CONCURRENCY, pairs.length) },
                             (_, i) => worker(i + 1));
  await Promise.all(workers);

  await browser.close();

  const elapsed = ((Date.now() - startedAt) / 1000).toFixed(1);
  console.log(`✅ Completado: ${ok} OK, ${fail} fallos en ${elapsed}s`);
  process.exit(fail > 0 ? 1 : 0);
})();
