<?php
/**
 * Escaleta — editor VISUAL de los plots de datos (v2, WYSIWYG).
 *
 * Vale para todas las escenas con chips/cajas por punto (condiciones, UV, AQI,
 * aeropuertos, máximas, variación). Sobre un FONDO LIMPIO (render real del mapa
 * sin chips, <escena>-base.png) el navegador pinta los chips como salen en
 * antena, con los DATOS VIVOS de los feeds del CDN, y coloca los no fijados con
 * el MISMO colocador anti-solape del render (placeChips portado a JS, con los
 * lados forzados/empujones del catálogo). Mover una caja se ve al instante.
 *
 *  - Posiciones fijadas RELATIVAS al punto {dx,dy}: sobreviven a cambios de
 *    cámara y de escala (las antiguas [x,y] se migran al cargar).
 *  - Ciudades: apagar/encender las del catálogo y AÑADIR de un catálogo maestro
 *    (unión de las 9 regiones; los feeds ya publican esas ciudades).
 *  - Solapes entre cajas finales marcados en rojo antes de guardar.
 *
 * Guardar hace read-modify-write del JSON publicado (solo toca
 * placement.<escena>, cities.<juego> y ui.chipScale), con historial y
 * detección de guardado concurrente, y encola una preview nueva.
 */
require_once dirname(__DIR__) . '/includes/auth.php';
requireSection('escaleta');
require_once __DIR__ . '/lib.php';

$slug = $_GET['p'] ?? '';
$scene = $_GET['scene'] ?? 'condiciones';
$catalog = esc_catalog();
$product = $catalog['products'][$slug] ?? null;
$plots = $product['plots'][$scene] ?? [];
if (!$product || !$plots) { http_response_code(404); exit('Producto o escena sin editor de plots'); }
$set = esc_city_set($scene);
$master = $catalog['master'][$set] ?? [];
$box = $product['box'][$scene] ?? null;
$layout = $product['layout'][$scene] ?? ['top' => 135, 'force' => [], 'nudge' => []];

$user = getCurrentUserName();
$self = 'placement.php?p=' . rawurlencode($slug) . '&scene=' . rawurlencode($scene);
$catalogIds = array_column($plots, 'id');
$sceneLabel = $product['scenes'][$scene]['label'] ?? $scene;
$error = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    csrfCheck();
    $action = $_POST['action'] ?? '';
    if ($action === 'save') {
        $prev = esc_config($slug);
        $error = esc_conflict($prev, (string) ($_POST['base_updated'] ?? ''), isset($_POST['force']));
        if (!$error) {
            $cities = esc_clean_cities(json_decode($_POST['cities'] ?? '', true) ?: [], $catalogIds, $master);
            $validIds = esc_scene_ids($plots, $cities);
            $clean = esc_clean_placement(json_decode($_POST['placement'] ?? '', true) ?: [], $validIds);
            // Read-modify-write del JSON publicado: SOLO placement.<escena>,
            // cities.<juego> y ui.chipScale — escenas, cámara y umbrales quedan.
            $cfg = $prev ?? ['version' => 1];
            unset($cfg['history']);
            if ($clean) $cfg['placement'][$scene] = $clean;
            else { unset($cfg['placement'][$scene]); if (empty($cfg['placement'])) unset($cfg['placement']); }
            if ($cities) $cfg['cities'][$set] = $cities;
            else { unset($cfg['cities'][$set]); if (empty($cfg['cities'])) unset($cfg['cities']); }
            $sc = $_POST['chipScale'] ?? '';
            if ($sc !== '' && is_numeric($sc) && (float) $sc >= 0.7 && (float) $sc <= 1.4) {
                if (abs((float) $sc - 1.0) < 0.001) { unset($cfg['ui']['chipScale']); if (empty($cfg['ui'])) unset($cfg['ui']); }
                else $cfg['ui']['chipScale'] = (float) $sc;
            }
            $n = count($clean); $off = count($cities['off'] ?? []); $ex = count($cities['extra'] ?? []);
            $note = trim((string) ($_POST['note'] ?? ''));
            if ($note === '') $note = "Plots «{$sceneLabel}»: {$n} fijados" . ($off ? ", {$off} apagadas" : '') . ($ex ? ", {$ex} añadidas" : '');
            if (esc_save_config($slug, $cfg, $prev, $user, $note)) {
                // Preview nueva con margen para que el push publique el JSON antes.
                esc_request_preview($slug, $scene, $user, false, 60);
                header('Location: ' . $self . '&m=saved'); exit;
            }
            header('Location: ' . $self . '&m=spoolerr'); exit;
        }
    } elseif ($action === 'preview') {
        esc_request_preview($slug, $scene, $user);
        header('Location: ' . $self . '&m=prev'); exit;
    } elseif ($action === 'base') {
        $ok = esc_request_preview($slug, $scene, $user, true);
        if (isset($_POST['ajax'])) { header('Content-Type: text/plain'); echo $ok ? 'ok' : 'err'; exit; }
        header('Location: ' . $self . '&m=base'); exit;
    }
}

$cfg = esc_config($slug);
$placed = $cfg['placement'][$scene] ?? [];
$cities = $cfg['cities'][$set] ?? [];
$chipScale = $cfg['ui']['chipScale'] ?? 1;
// Cámara efectiva para reproyectar los puntos: overrides de la escaleta sobre
// los valores por defecto del catálogo (mismo orden que applyEscaletaRuntime).
$cam = $product['camera'] ?? [];
$cc = $cfg['camera'] ?? [];
if (isset($cc['west'], $cc['south'], $cc['east'], $cc['north'])) {
    foreach (['west', 'south', 'east', 'north'] as $k) $cam[$k] = $cc[$k];
}
foreach (['padTop', 'padBottom', 'padLeft', 'padRight'] as $k) {
    if (isset($cc[$k]) && is_numeric($cc[$k])) $cam[$k] = $cc[$k];
}
$prevDir = ESC_CDN . '/previews/' . rawurlencode($slug) . '/' . rawurlencode($scene);
$msg = [
    'saved' => 'Guardado. Se publica en ≤1 min y se ha encolado una preview de confirmación (pestaña «Ver» de la escaleta en ~2-3 min).',
    'prev' => 'Vista previa solicitada: calamarsa la renderiza en 1-3 min.',
    'base' => 'Fondo limpio solicitado: calamarsa lo renderiza en 1-3 min (recarga la página).',
    'spoolerr' => 'No se pudo escribir en el buzón (outbox no accesible)',
][$_GET['m'] ?? ''] ?? null;
$isErr = ($_GET['m'] ?? '') === 'spoolerr';
// Feeds que alimentan los chips en vivo (CDN público, CORS abierto).
$feedBase = 'https://canalmeteo-public.sfo3.digitaloceanspaces.com/data';
$feedUrl = [
    'condiciones' => "$feedBase/cities/weather.json", 'aeropuertos' => "$feedBase/airports/delays.json",
    'uv' => "$feedBase/uv/cities.json", 'aqi' => "$feedBase/aqi/cities.json",
    'tmax_today' => "$feedBase/tmax/cities.json", 'tmax_tomorrow' => "$feedBase/tmax/cities.json", 'tvar' => "$feedBase/tmax/cities.json",
][$scene] ?? null;
?>
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title><?= htmlspecialchars($product['nombre']) ?> · <?= htmlspecialchars($sceneLabel) ?> · Plots</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;600;700;800;900&family=JetBrains+Mono:wght@600;800;900&display=swap" rel="stylesheet">
<style>
  body{font-family:Outfit,system-ui,sans-serif;background:#0d1a26;color:#eef4f8;margin:0;padding:24px 28px}
  a{color:#7cc4ff;text-decoration:none}
  h1{font-size:22px;margin:0 0 4px}
  .sub{color:#9db4c4;margin-bottom:12px;font-size:14px}
  .tabs{margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap}
  .tabs a{background:#16324a;border-radius:8px;padding:5px 12px;font-size:13px;font-weight:700;color:#cfe4f5}
  .tabs a.cur{background:#1f5f9e;color:#fff}
  .msg{padding:10px 16px;border-radius:10px;margin-bottom:14px;max-width:1400px;font-size:15px}
  .ok{background:#123a24;border:1px solid #2ecc71}
  .err{background:#3a1212;border:1px solid #e74c3c}
  .warn{background:#3a2a12;border:1px solid #f4a020}
  .cols{display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap}
  /* Escenario 16:9 SIEMPRE: dentro, un lienzo de 1920×1080 escalado con
     transform, así fuentes y cajas salen a tamaño real proporcional. */
  #stage{position:relative;flex:1 1 760px;max-width:1400px;aspect-ratio:16/9;background:#08131c;
         border:1px solid rgba(255,255,255,.2);border-radius:10px;overflow:hidden;cursor:crosshair;user-select:none}
  #bg{position:absolute;inset:0;width:100%;height:100%;display:block;pointer-events:none}
  #bg.stale{filter:saturate(.4) brightness(.55)}
  #canvas{position:absolute;left:0;top:0;width:1920px;height:1080px;transform-origin:0 0;pointer-events:none}
  #lines{position:absolute;inset:0;width:1920px;height:1080px;pointer-events:none}
  .pt{position:absolute;width:12px;height:12px;border-radius:50%;background:#fff;border:2px solid rgba(0,0,0,.6);
      transform:translate(-50%,-50%);box-shadow:0 0 6px rgba(0,0,0,.6);z-index:3}
  .pt.sel{background:#ffd24a}
  .chip{position:absolute;transform:translate(-50%,-50%);z-index:5;pointer-events:auto;cursor:grab;font-family:Outfit,system-ui,sans-serif}
  .chip.drag{cursor:grabbing;z-index:9}
  .chip .frame{position:absolute;inset:-6px;border:2px dashed transparent;border-radius:12px;pointer-events:none}
  .chip.pinned .frame{border-color:rgba(46,230,214,.75)}
  .chip.sel .frame{border-color:#ffd24a;border-style:solid}
  .chip.ov .frame{border-color:#ff3b3b;border-style:solid;box-shadow:0 0 0 4px rgba(255,59,59,.35)}
  .chip.ghost{opacity:.45}
  .chip .tag{position:absolute;left:50%;top:-30px;transform:translateX(-50%);font-size:16px;font-weight:700;color:#0d1a26;background:#ffd24a;
             border-radius:6px;padding:1px 8px;white-space:nowrap;pointer-events:none;display:none}
  .chip.sel .tag,.chip.ov .tag{display:block}
  .chip.ov:not(.sel) .tag{background:#ff3b3b;color:#fff}
  #stageNote{position:absolute;left:12px;bottom:10px;background:rgba(13,26,38,.85);border:1px solid rgba(255,255,255,.2);border-radius:8px;
             padding:6px 10px;font-size:13px;color:#ffd7a0;display:none;z-index:20}
  .panel{flex:0 0 340px;background:#10222f;border:1px solid rgba(255,255,255,.14);border-radius:12px;padding:14px 16px}
  .panel h2{font-size:14px;margin:14px 0 8px;color:#9db4c4;text-transform:uppercase;letter-spacing:1px}
  .panel h2:first-child{margin-top:0}
  .scale input[type=range]{width:100%}
  .scale .val{font-family:'JetBrains Mono',monospace;color:#2ee6d6}
  #cityList{max-height:380px;overflow:auto}
  .city{display:flex;align-items:center;gap:6px;padding:4px 6px;border-radius:8px;cursor:pointer;font-size:14px}
  .city:hover{background:rgba(255,255,255,.06)}
  .city.sel{background:#1f5f9e33;outline:1px solid #7cc4ff}
  .city.off{opacity:.5}
  .city .nm{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .city .nm small{color:#9db4c4;font-weight:400}
  .city .pos{font-family:'JetBrains Mono',monospace;font-size:11px;color:#2ee6d6}
  .city .auto{font-size:11px;color:#5f7787}
  .city .nodata{font-size:11px;color:#f4a020}
  .city button{background:none;border:0;cursor:pointer;font-size:15px;padding:0 3px;color:#cfe4f5}
  .city button.rm{color:#e74c3c}
  .city button.eye{color:#9db4c4}
  .add{display:flex;gap:6px;margin-top:6px}
  .add select{flex:1;background:#12283a;color:#fff;border:1px solid rgba(255,255,255,.25);border-radius:8px;padding:6px;font-family:Outfit;font-size:13px}
  input[type=text]{background:#12283a;color:#fff;border:1px solid rgba(255,255,255,.25);border-radius:8px;padding:7px 9px;font-family:Outfit;font-size:13px;width:100%;box-sizing:border-box}
  .btn{background:#1f5f9e;color:#fff;border:0;border-radius:10px;padding:10px 22px;font-family:Outfit;font-weight:700;font-size:16px;cursor:pointer}
  .btn.sm{padding:5px 12px;font-size:13px;background:#16324a}
  .btn:hover{filter:brightness(1.15)}
  .hint{color:#9db4c4;font-size:12.5px;margin-top:8px;line-height:1.5}
  #ovBox{display:none;background:#3a1212;border:1px solid #e74c3c;border-radius:8px;padding:6px 10px;font-size:13px;margin-top:8px}
</style>
</head>
<body>
<h1><?= htmlspecialchars($product['nombre']) ?> <span style="color:#9db4c4">· plots · <?= htmlspecialchars($sceneLabel) ?></span></h1>
<div class="sub"><a href="edit.php?p=<?= rawurlencode($slug) ?>">← Escaleta del producto</a> ·
  Lo que ves es lo que sale: chips con los datos de ahora mismo, colocados por el mismo colocador que la antena. Arrastra cualquier caja; el punto (su ciudad) no se mueve.</div>

<div class="tabs">
<?php foreach (($product['plots'] ?? []) as $k => $pl): if (!$pl) continue; ?>
  <a class="<?= $k === $scene ? 'cur' : '' ?>" href="placement.php?p=<?= rawurlencode($slug) ?>&scene=<?= rawurlencode($k) ?>">
    <?= htmlspecialchars($product['scenes'][$k]['label'] ?? $k) ?></a>
<?php endforeach; ?>
</div>

<?php if ($msg): ?><div class="msg <?= $isErr ? 'err' : 'ok' ?>"><?= htmlspecialchars($msg) ?></div><?php endif; ?>
<?php if ($error): ?><div class="msg err"><?= htmlspecialchars($error) ?></div><?php endif; ?>

<div class="cols">
  <div id="stage">
    <img id="bg" src="<?= htmlspecialchars($prevDir . '-base.png?ts=' . time()) ?>" alt="">
    <div id="canvas">
      <svg id="lines" viewBox="0 0 1920 1080"></svg>
    </div>
    <div id="stageNote"></div>
  </div>

  <div class="panel">
    <div class="scale">
      <h2>Tamaño de los plots ×<span class="val" id="scaleVal"><?= htmlspecialchars(number_format((float) $chipScale, 2)) ?></span></h2>
      <input type="range" id="chipScale" min="0.7" max="1.4" step="0.05" value="<?= htmlspecialchars((string) $chipScale) ?>">
      <div class="hint" style="margin-top:2px">Escala GLOBAL de chips/cajas del producto (todas las escenas).</div>
    </div>
    <h2>Ciudades <span id="counts" style="color:#5f7787;text-transform:none;letter-spacing:0"></span></h2>
    <div id="cityList"></div>
    <div class="add">
      <select id="addSel"><option value="">+ Añadir del catálogo nacional…</option></select>
      <button class="btn sm" type="button" id="addBtn">Añadir</button>
    </div>
    <details id="newCity" style="margin-top:8px">
      <summary style="cursor:pointer;font-size:13px;color:#7cc4ff">+ Ciudad nueva (no está en ningún catálogo)</summary>
      <div class="hint" style="margin-top:6px">Los pipelines de nimbus empiezan a publicar su dato en la siguiente pasada (1–2 h)<?= $scene === 'aeropuertos' ? '; el aeropuerto debe existir en el sistema de la FAA' : '' ?>. Hasta entonces sale como «sin dato».</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:6px">
        <input type="text" id="ncLabel" placeholder="Nombre en antena (p. ej. Yuma)" style="grid-column:1/3">
        <?php if ($scene === 'aeropuertos'): ?>
          <input type="text" id="ncIata" placeholder="Código IATA (3 letras)" maxlength="3" style="text-transform:uppercase">
          <input type="text" id="ncCity" placeholder="Ciudad en inglés (p. ej. Yuma)">
        <?php else: ?>
          <input type="text" id="ncCity" placeholder="Ciudad en inglés (p. ej. Yuma)" style="grid-column:1/3">
        <?php endif; ?>
        <select id="ncState" style="background:#12283a;color:#fff;border:1px solid rgba(255,255,255,.25);border-radius:8px;padding:6px;font-family:Outfit;font-size:13px"><option value="">Estado…</option></select>
        <button class="btn sm" type="button" id="ncGeo" title="Busca lat/lon en OpenStreetMap (Nominatim)">Buscar coordenadas</button>
        <input type="text" id="ncLat" placeholder="Latitud (p. ej. 32.69)">
        <input type="text" id="ncLon" placeholder="Longitud (p. ej. −114.63)">
        <button class="btn sm" type="button" id="ncAdd" style="grid-column:1/3;background:#1f5f9e">Añadir ciudad nueva</button>
      </div>
      <div class="hint" id="ncMsg" style="margin-top:4px"></div>
    </details>
    <div id="ovBox"></div>
    <form method="post" id="saveForm" style="margin-top:14px">
      <?= csrfField() ?>
      <input type="hidden" name="action" value="save">
      <input type="hidden" name="placement" id="placementJson" value="">
      <input type="hidden" name="cities" id="citiesJson" value="">
      <input type="hidden" name="chipScale" id="chipScaleField" value="">
      <input type="hidden" name="base_updated" value="<?= htmlspecialchars((string) ($cfg['updated'] ?? '')) ?>">
      <input type="text" name="note" placeholder="Nota para el historial (opcional)">
      <?php if ($error && strncmp($error, '⚠', strlen('⚠')) === 0): ?>
        <label style="display:block;margin-top:8px;font-size:13px"><input type="checkbox" name="force"> <b>Sobrescribir</b> lo que guardó la otra persona</label>
      <?php endif; ?>
      <p style="margin:10px 0 0"><button class="btn" type="submit">Guardar y publicar</button></p>
    </form>
    <div style="display:flex;gap:6px;margin-top:8px">
      <form method="post" style="margin:0"><?= csrfField() ?><input type="hidden" name="action" value="base"><button class="btn sm" type="submit" title="Vuelve a renderizar el mapa de fondo (sin chips) con los datos de ahora">Actualizar fondo</button></form>
      <form method="post" style="margin:0"><?= csrfField() ?><input type="hidden" name="action" value="preview"><button class="btn sm" type="submit" title="Render real completo, para la pestaña «Ver» de la escaleta">Preview real</button></form>
    </div>
    <div class="hint">
      · Arrastra una caja (o elígela en la lista y haz clic en el mapa). Contorno cian = fijada; «×» la devuelve al colocador automático.<br>
      · 👁 apaga/enciende una ciudad en esta escena<?= $set === 'tmax' ? ' (las 3 de temperatura comparten ciudades)' : '' ?>; «Añadir» trae una del catálogo nacional.<br>
      · Rojo = dos cajas se pisan. Se guarda igual, pero mejor arreglarlo.
    </div>
  </div>
</div>

<script>
const SCENE = <?= json_encode($scene) ?>;
const PLOTS = <?= json_encode(array_values($plots), JSON_UNESCAPED_UNICODE) ?>;   // catálogo: {id,label,name,key,lon,lat,w,h}
const MASTER = <?= json_encode(array_values($master), JSON_UNESCAPED_UNICODE) ?>; // unión nacional: {id,label,name,key,lon,lat}
const BOX = <?= json_encode($box) ?>;                                            // {base,mn,mult,add,h}
const LAYOUT = <?= json_encode($layout, JSON_UNESCAPED_UNICODE) ?>;              // {top, force, nudge}
const CAM = <?= json_encode($cam) ?>;
const FEED = <?= json_encode($feedUrl) ?>;
const PREV_FULL = <?= json_encode($prevDir . '.png?ts=' . time()) ?>;
const CSRF = document.querySelector('#saveForm input[name=csrf]');
let PL = <?= json_encode((object) $placed, JSON_UNESCAPED_UNICODE) ?>;           // {id: {dx,dy}} (o [x,y] antiguo → se migra)
let OFF = new Set(<?= json_encode(array_values($cities['off'] ?? [])) ?>);
let EXTRA = <?= json_encode(array_values($cities['extra'] ?? []), JSON_UNESCAPED_UNICODE) ?>; // [{id,label,name,key,lon,lat}]
let SCALE = <?= json_encode((float) $chipScale) ?>;
let SEL = null;
let DATA = null; // valores del feed por key

const stage = document.getElementById('stage');
const canvas = document.getElementById('canvas');
const lines = document.getElementById('lines');
const list = document.getElementById('cityList');
const bg = document.getElementById('bg');
const note = document.getElementById('stageNote');

// ── Reproyección mercator con el MISMO encuadre que el render (fitBounds con
// padding: bbox centrado e íntegro dentro del área útil). ──
const merc = lat => { const s = Math.sin(lat * Math.PI / 180); return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI); };
const mx0 = (CAM.west + 180) / 360, mx1 = (CAM.east + 180) / 360;
const my0 = merc(CAM.north), my1 = merc(CAM.south);
const availW = 1920 - (CAM.padLeft || 0) - (CAM.padRight || 0);
const availH = 1080 - (CAM.padTop || 0) - (CAM.padBottom || 0);
const sc = Math.min(availW / (mx1 - mx0), availH / (my1 - my0));
const offX = (CAM.padLeft || 0) + (availW - (mx1 - mx0) * sc) / 2 - mx0 * sc;
const offY = (CAM.padTop || 0) + (availH - (my1 - my0) * sc) / 2 - my0 * sc;
const proj = p => [((p.lon + 180) / 360) * sc + offX, merc(p.lat) * sc + offY];

// ── Escalado del lienzo 1920×1080 al tamaño del escenario ──
function fitCanvas() {
  const r = stage.getBoundingClientRect();
  canvas.style.transform = `scale(${r.width / 1920})`;
}
new ResizeObserver(fitCanvas).observe(stage);
fitCanvas();
function toCanvas(ev) {
  const r = stage.getBoundingClientRect();
  return [Math.round(Math.max(0, Math.min(1920, (ev.clientX - r.left) / r.width * 1920))),
          Math.round(Math.max(0, Math.min(1080, (ev.clientY - r.top) / r.height * 1080)))];
}

// ── Fondo: <escena>-base.png (mapa sin chips). Si no existe, se pide UNA vez
// (máx. cada 5 min) y mientras tanto se usa la preview completa atenuada. ──
bg.addEventListener('error', () => {
  if (bg.dataset.fallback) { bg.style.display = 'none'; note.textContent = 'Sin fondo todavía: pídelo con «Actualizar fondo» (1-3 min). Los puntos blancos sitúan cada ciudad.'; note.style.display = 'block'; return; }
  bg.dataset.fallback = '1';
  bg.src = PREV_FULL;
  bg.classList.add('stale');
  note.textContent = 'Fondo provisional (preview antigua con sus chips, atenuada). Se está generando el fondo limpio: recarga en 1-3 min.';
  note.style.display = 'block';
  const k = 'escBase:' + location.search;
  try {
    const last = +sessionStorage.getItem(k) || 0;
    if (Date.now() - last > 5 * 60 * 1000) {
      sessionStorage.setItem(k, String(Date.now()));
      const fd = new FormData(); fd.append(CSRF.name, CSRF.value); fd.append('action', 'base'); fd.append('ajax', '1');
      fetch(location.href, { method: 'POST', body: fd });
    }
  } catch (e) { /* sin sessionStorage: nada */ }
});

// ── Colores/escala (réplica de lib/conditions.ts y ServicesMockups.tsx) ──
const hex = h => { const m = h.replace('#', ''); return [parseInt(m.slice(0, 2), 16), parseInt(m.slice(2, 4), 16), parseInt(m.slice(4, 6), 16)]; };
const lerp = (a, b, t) => { const pa = hex(a), pb = hex(b); return `rgb(${Math.round(pa[0] + (pb[0] - pa[0]) * t)},${Math.round(pa[1] + (pb[1] - pa[1]) * t)},${Math.round(pa[2] + (pb[2] - pa[2]) * t)})`; };
function tempColor(f) {
  const st = [[10, '#7c4dff'], [32, '#3d7bff'], [45, '#21b6c9'], [55, '#2ecc71'], [68, '#f4d03f'], [80, '#ef8e2d'], [92, '#e74c3c'], [104, '#c0298a']];
  if (f <= st[0][0]) return st[0][1];
  if (f >= st[st.length - 1][0]) return st[st.length - 1][1];
  for (let i = 0; i < st.length - 1; i++) { const [a, ca] = st[i], [b, cb] = st[i + 1]; if (f >= a && f <= b) return lerp(ca, cb, (f - a) / (b - a)); }
  return st[st.length - 1][1];
}
function textOn(bg) {
  let r, g, b; const m = bg.match(/rgba?\(([^)]+)\)/i);
  if (m) { const p = m[1].split(',').map(parseFloat); [r, g, b] = [p[0] / 255, p[1] / 255, p[2] / 255]; }
  else { const h = hex(bg); [r, g, b] = [h[0] / 255, h[1] / 255, h[2] / 255]; }
  return (0.299 * r + 0.587 * g + 0.114 * b) < 0.55 ? '#fff' : '#10202c';
}
const uvColor = uv => uv <= 2 ? '#2ecc71' : uv <= 5 ? '#f4d03f' : uv <= 7 ? '#ef8e2d' : uv <= 10 ? '#e74c3c' : '#8e44ad';
const uvCat = uv => uv <= 2 ? 'Bajo' : uv <= 5 ? 'Moderado' : uv <= 7 ? 'Alto' : uv <= 10 ? 'Muy alto' : 'Extremo';
const aqiColor = a => a <= 50 ? '#2ecc71' : a <= 100 ? '#f4d03f' : a <= 150 ? '#ef8e2d' : a <= 200 ? '#e74c3c' : a <= 300 ? '#8e44ad' : '#7e0023';
const aqiCat = a => a <= 50 ? 'Buena' : a <= 100 ? 'Moderada' : a <= 150 ? 'Sensibles' : a <= 200 ? 'Dañina' : a <= 300 ? 'Muy dañina' : 'Peligrosa';
const AIR_COLOR = { open: '#2ecc71', delay: '#f4a020', closed: '#e74c3c' };
const DELTA = ['#123f8f', '#1a52ad', '#2767c4', '#3a7ed8', '#5497e6', '#74b1ef', '#9acaf5', '#c4e0fa', '#c9ced4', '#ffe0a8', '#ffc873', '#ffab42', '#ff8c1a', '#f76b00', '#e64f00', '#cf3600', '#b32000'];
const deltaColor = d => DELTA[Math.max(-8, Math.min(8, Math.round(d))) + 8];
const COMPASS = { N: 0, NNE: 22.5, NE: 45, ENE: 67.5, E: 90, ESE: 112.5, SE: 135, SSE: 157.5, S: 180, SSW: 202.5, SW: 225, WSW: 247.5, W: 270, WNW: 292.5, NW: 315, NNW: 337.5 };
const windDeg = d => ((COMPASS[(d || '').toUpperCase()] ?? 0) + 180) % 360;
function sky(es, night) {
  const s = (es || '').toLowerCase();
  if (/tormenta|eléctric/.test(s)) return 'tormenta';
  if (/nieve|nevad/.test(s)) return 'nieve';
  if (/lluvia|chubasc|llovizn|aguacero/.test(s)) return 'lluvia';
  if (/niebla|neblin|bruma/.test(s)) return 'nublado';
  if (/parcial/.test(s)) return 'nubes-claros';
  if (/mayormente nublado|nublado|cubierto/.test(s)) return 'nublado';
  if (/soleado|despejado|sol/.test(s)) return 'sol';
  return night ? 'nubes-claros' : 'sol';
}
// Icono de cielo (réplica del SkyIcon SVG de components/CondBox.tsx).
function skyIcon(k, size) {
  const sun = '#FFC83D', cloud = '#E7EDF2', cloudDark = '#B7C2cc', drop = '#5BA6FF', bolt = '#FFD23D', snow = '#DDE9F5';
  const C = (x, y, fill = cloud) => `<path d="M${x + 7} ${y + 22} a7 7 0 0 1 1 -13 a9 9 0 0 1 17 -2 a6 6 0 0 1 2 15 z" fill="${fill}"/>`;
  let inner = '';
  if (k === 'sol') inner = [...Array(8)].map((_, i) => `<rect x="17" y="2" width="2" height="6" rx="1" fill="${sun}" transform="rotate(${i * 45} 18 18)"/>`).join('') + `<circle cx="18" cy="18" r="8" fill="${sun}"/>`;
  else if (k === 'nubes-claros') inner = [...Array(8)].map((_, i) => `<rect x="11" y="1" width="1.6" height="4.5" rx="1" fill="${sun}" transform="rotate(${i * 45} 12 12)"/>`).join('') + `<circle cx="12" cy="12" r="6" fill="${sun}"/>` + C(6, 9);
  else if (k === 'nublado') inner = C(2, 4, cloudDark) + C(8, 9);
  else if (k === 'lluvia') inner = C(5, 3) + [10, 17, 24].map(x => `<rect x="${x}" y="26" width="2.4" height="7" rx="1.2" fill="${drop}" transform="rotate(15 ${x} 28)"/>`).join('');
  else if (k === 'tormenta') inner = C(5, 3, cloudDark) + `<polygon points="18,25 13,33 17,33 14,40 24,30 19,30 22,25" fill="${bolt}"/>`;
  else if (k === 'nieve') inner = C(5, 3) + [11, 18, 25].map(x => `<text x="${x}" y="33" font-size="9" fill="${snow}" text-anchor="middle">❄</text>`).join('');
  return `<svg width="${size}" height="${size}" viewBox="0 0 36 36" style="display:block">${inner}</svg>`;
}
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// ── Chips: mismo HTML/CSS que los componentes de la antena ──
function chipHTML(p, v) {
  const MONO = "font-family:'JetBrains Mono',monospace";
  if (SCENE === 'condiciones') {
    const t = v ? v.temp : 72, accent = tempColor(t);
    return `<div style="background:rgba(13,24,34,0.86);border:1px solid rgba(255,255,255,0.16);border-left:5px solid ${accent};border-radius:14px;padding:12px 17px 13px 16px;box-shadow:0 10px 26px rgba(0,0,0,0.5);min-width:185px">
      <div style="display:flex;align-items:center;gap:11px">${skyIcon(v ? sky(v.conditionEs, v.isNight) : 'sol', 65)}<span style="font-size:58px;font-weight:800;color:#fff;line-height:1;${MONO}">${v ? Math.round(t) + '°' : '—'}</span></div>
      <div style="font-size:33px;font-weight:700;color:#fff;margin-top:6px;white-space:nowrap">${esc(p.name)}</div>
      <div style="display:flex;align-items:center;gap:8px;margin-top:4px"><span style="display:inline-block;font-size:28px;color:#cfe0ee;transform:rotate(${v ? windDeg(v.windDir) : 0}deg)">↑</span><span style="font-size:28px;color:rgba(255,255,255,0.85)">${v ? Math.round(v.windSpeed || 0) : '–'} mph</span></div></div>`;
  }
  if (SCENE === 'aeropuertos') {
    const st = v ? v.status : 'open', color = AIR_COLOR[st] || AIR_COLOR.open;
    const lbl = st === 'closed' ? 'Cerrado' : st === 'delay' ? `${v.delayMin} min` : 'Normal';
    const plane = `<svg width="34" height="34" viewBox="0 0 24 24" style="display:block"><path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L11 19v-5.5z" fill="${color}"/></svg>`;
    return `<div style="background:rgba(13,24,34,0.88);border:1px solid rgba(255,255,255,0.16);border-left:7px solid ${color};border-radius:13px;padding:10px 17px 12px 15px;box-shadow:0 8px 22px rgba(0,0,0,0.5);min-width:145px">
      <div style="display:flex;align-items:center;gap:10px">${plane}<span style="font-size:39px;font-weight:900;color:#fff;line-height:1;letter-spacing:1px">${esc(p.id)}</span></div>
      <div style="font-size:24px;font-weight:700;color:#fff;margin-top:5px;white-space:nowrap">${esc(p.name)}</div>
      <div style="display:inline-block;background:${color};color:${textOn(color)};font-size:22px;font-weight:800;letter-spacing:.2px;padding:4px 14px;border-radius:999px;margin-top:7px;box-shadow:0 2px 8px rgba(0,0,0,0.45)">${v ? lbl : '—'}</div></div>`;
  }
  if (SCENE === 'uv' || SCENE === 'aqi') {
    const isUv = SCENE === 'uv', val = v ? (isUv ? v.uv : v.aqi) : null;
    const color = val == null ? '#5f7787' : (isUv ? uvColor(val) : aqiColor(val));
    const cat = val == null ? '' : (isUv ? uvCat(val) : aqiCat(val));
    return `<div style="display:flex;flex-direction:column;align-items:center;gap:6px">
      <div style="width:104px;height:104px;border-radius:50%;background:${color};border:4px solid rgba(255,255,255,0.95);box-shadow:0 6px 18px rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;color:${textOn(color)};font-weight:900;font-size:48px;line-height:1;${MONO}">${val == null ? '—' : val}</div>
      <div style="color:#fff;font-size:33px;font-weight:800;white-space:nowrap;text-shadow:0 2px 6px rgba(0,0,0,0.95),0 0 12px rgba(0,0,0,0.9)">${esc(p.name)}</div>
      ${cat ? `<div style="background:${color};color:${textOn(color)};font-size:21px;font-weight:800;letter-spacing:.2px;padding:4px 14px;border-radius:999px;box-shadow:0 2px 8px rgba(0,0,0,0.5);margin-top:1px">${cat}</div>` : ''}</div>`;
  }
  if (SCENE === 'tvar') {
    const d = v ? v.delta : 0, color = deltaColor(d), fg = textOn(color);
    return `<div style="background:${color};border:1px solid rgba(255,255,255,0.55);border-radius:14px;padding:10px 21px 12px;box-shadow:0 8px 22px rgba(0,0,0,0.45);text-align:center">
      <div style="display:flex;align-items:center;justify-content:center;gap:7px"><span style="font-size:43px;line-height:1;color:${fg}">${d >= 0 ? '▲' : '▼'}</span><span style="font-size:54px;font-weight:900;color:${fg};line-height:1;${MONO}">${v ? (d > 0 ? '+' : '') + Math.round(d) + '°' : '—'}</span></div>
      <div style="font-size:27px;font-weight:800;color:${fg};margin-top:4px;white-space:nowrap;opacity:.95">${esc(p.name)}</div></div>`;
  }
  // tmax_today / tmax_tomorrow
  const t = v ? v.tmax : 75, color = v ? tempColor(t) : '#5f7787', fg = textOn(color);
  return `<div style="background:${color};border:1px solid rgba(255,255,255,0.55);border-radius:14px;padding:10px 22px 12px;box-shadow:0 8px 22px rgba(0,0,0,0.45);text-align:center">
    <div style="font-size:62px;font-weight:900;color:${fg};line-height:1;${MONO}">${v ? Math.round(t) + '°' : '—'}</div>
    <div style="font-size:27px;font-weight:800;color:${fg};margin-top:4px;white-space:nowrap;opacity:.95">${esc(p.name)}</div></div>`;
}

// ── Datos vivos del feed → valor por key ──
async function loadFeed() {
  if (!FEED) return;
  try {
    const d = await (await fetch(FEED + '?ts=' + Date.now())).json();
    const m = {};
    if (SCENE === 'condiciones') (d.data || []).forEach(r => { if (typeof r.temp === 'number') m[`${r.city}|${r.state}`] = r; });
    else if (SCENE === 'aeropuertos') (d.airports || []).forEach(r => { m[r.iata] = r; });
    else if (SCENE === 'uv') (d.cities || []).forEach(r => { if (typeof r.uv === 'number') m[r.id] = r; });
    else if (SCENE === 'aqi') (d.cities || []).forEach(r => { if (typeof r.aqi === 'number') m[r.id] = r; });
    else if (SCENE === 'tmax_today') (d.today || []).forEach(r => { if (typeof r.tmax === 'number') m[r.id] = r; });
    else if (SCENE === 'tmax_tomorrow') (d.tomorrow || []).forEach(r => { if (typeof r.tmax === 'number') m[r.id] = r; });
    else if (SCENE === 'tvar') {
      const today = {}; (d.today || []).forEach(r => { if (typeof r.tmax === 'number') today[r.id] = r.tmax; });
      (d.tomorrow || []).forEach(r => { if (typeof r.tmax === 'number' && today[r.id] != null) m[r.id] = { delta: r.tmax - today[r.id] }; });
    }
    DATA = m;
  } catch (e) { DATA = {}; }
  render();
}

// ── Lista efectiva de plots (catálogo − apagadas + añadidas) ──
const boxOf = name => ({ w: Math.round(BOX.base + Math.max(BOX.mn, name.length * BOX.mult + BOX.add)), h: Math.round(BOX.h) });
function activePlots() {
  const out = PLOTS.filter(p => !OFF.has(p.id));
  for (const e of EXTRA) if (!PLOTS.some(p => p.id === e.id)) out.push({ ...e, ...boxOf(e.name || e.label) });
  return out;
}
// Migración del formato antiguo [x,y] → {dx,dy} respecto al punto (una vez).
(function migrate() {
  const byId = Object.fromEntries([...PLOTS, ...EXTRA].map(p => [p.id, p]));
  for (const [id, v] of Object.entries(PL)) {
    if (Array.isArray(v) && byId[id]) { const [px, py] = proj(byId[id]); PL[id] = { dx: v[0] - px, dy: v[1] - py }; }
    else if (!v || typeof v !== 'object' || typeof v.dx !== 'number') delete PL[id];
  }
})();

// ── Colocador anti-solape: port literal de placeChips (ServicesMockups.tsx) ──
function overlap(a, b, pad = 6) {
  const ix = Math.min(a.x1, b.x1 + pad) - Math.max(a.x0, b.x0 - pad);
  const iy = Math.min(a.y1, b.y1 + pad) - Math.max(a.y0, b.y0 - pad);
  return ix > 0 && iy > 0 ? ix * iy : 0;
}
function placeChips(items, W, H, top, bottom, force, pinned) {
  const margin = 18, gap = 9, taken = [], out = [];
  const pinnedItems = items.filter(c => pinned[c.id]);
  items = items.filter(c => !pinned[c.id]);
  for (const c of pinnedItems) {
    const { w, h } = c, pp = pinned[c.id];
    const [px, py] = Array.isArray(pp) ? pp : [c.x + pp.dx, c.y + pp.dy];
    const cx = Math.max(margin + w / 2, Math.min(W - margin - w / 2, px));
    const cy = Math.max(top + h / 2, Math.min(bottom - h / 2, py));
    taken.push({ x0: cx - w / 2, y0: cy - h / 2, x1: cx + w / 2, y1: cy + h / 2 });
    out.push({ ...c, bx: cx, by: cy, pinned: true });
  }
  const forced = items.filter(c => force[c.id]);
  const auto = items.filter(c => !force[c.id]);
  for (const c of forced) {
    const { w, h } = c, d = force[c.id];
    const [ux, uy] = d === 'left' ? [-1, 0] : d === 'right' ? [1, 0] : d === 'up' ? [0, -1] : [0, 1];
    const off = gap + (Math.abs(ux) * w + Math.abs(uy) * h) / 2;
    const cx = Math.max(margin + w / 2, Math.min(W - margin - w / 2, c.x + ux * off));
    const cy = Math.max(top + h / 2, Math.min(bottom - h / 2, c.y + uy * off));
    taken.push({ x0: cx - w / 2, y0: cy - h / 2, x1: cx + w / 2, y1: cy + h / 2 });
    out.push({ ...c, bx: cx, by: cy });
  }
  items = auto;
  const n = Math.max(1, items.length);
  const cxAll = items.reduce((s, c) => s + c.x, 0) / n, cyAll = items.reduce((s, c) => s + c.y, 0) / n;
  const dirs = [];
  for (let a = 0; a < 12; a++) { const ang = (a / 12) * Math.PI * 2 - Math.PI / 2; dirs.push([Math.cos(ang), Math.sin(ang)]); }
  for (const c of items) {
    const { w, h } = c;
    let ax = c.x - cxAll, ay = c.y - cyAll; const al = Math.hypot(ax, ay) || 1; ax /= al; ay /= al;
    let best = null, bestScore = Infinity;
    for (const k of [1.0, 1.5, 2.05]) {
      for (const [ux, uy] of dirs) {
        const off = gap + (Math.abs(ux) * w + Math.abs(uy) * h) / 2, r = off * k;
        const cx0 = c.x + ux * r, cy0 = c.y + uy * r;
        const cx = Math.max(margin + w / 2, Math.min(W - margin - w / 2, cx0));
        const cy = Math.max(top + h / 2, Math.min(bottom - h / 2, cy0));
        const rect = { x0: cx - w / 2, y0: cy - h / 2, x1: cx + w / 2, y1: cy + h / 2 };
        let ov = 0; for (const t of taken) ov += overlap(rect, t);
        const dist = Math.hypot(cx - c.x, cy - c.y), clampDrift = Math.abs(cx - cx0) + Math.abs(cy - cy0);
        const outward = Math.max(0, ux * ax + uy * ay);
        const score = ov * 1000 + dist + clampDrift * 1.2 + outward * 55;
        if (score < bestScore) { bestScore = score; best = { cx, cy, rect }; }
      }
      if (bestScore < 1000) break;
    }
    if (best) { taken.push(best.rect); out.push({ ...c, bx: best.cx, by: best.cy }); }
  }
  return out;
}

// ── Render completo: puntos, líneas, chips y lista ──
function layout() {
  const plots = activePlots();
  // Como en la antena: las ciudades SIN dato hoy no se dibujan → no ocupan
  // sitio en el colocador. Aquí se muestran como "fantasma" (fuera del cálculo)
  // para poder fijarlas igualmente.
  const withData = p => DATA == null || DATA[p.key] != null;
  const projected = plots.filter(withData).map(p => { const [x, y] = proj(p); return { ...p, x, y, w: p.w * SCALE, h: p.h * SCALE }; });
  const placed = placeChips(projected, 1920, 1080, LAYOUT.top, 1080 - 56, LAYOUT.force || {}, PL).map(b => {
    const d = (LAYOUT.nudge || {})[b.id];
    return d && !PL[b.id] ? { ...b, bx: b.bx + d[0], by: b.by + d[1] } : b;
  });
  const ghosts = plots.filter(p => !withData(p)).map(p => { const [x, y] = proj(p); const pp = PL[p.id];
    return { ...p, x, y, w: p.w * SCALE, h: p.h * SCALE, bx: pp ? x + pp.dx : x, by: pp ? y + pp.dy : y - p.h * SCALE / 2 - 9, ghost: true, pinned: !!pp }; });
  // Solapes reales entre cajas finales (sin margen): en rojo.
  const rect = b => ({ x0: b.bx - b.w / 2, y0: b.by - b.h / 2, x1: b.bx + b.w / 2, y1: b.by + b.h / 2 });
  const ov = new Set();
  for (let i = 0; i < placed.length; i++) for (let j = i + 1; j < placed.length; j++) {
    if (overlap(rect(placed[i]), rect(placed[j]), 0) > 0) { ov.add(placed[i].id); ov.add(placed[j].id); }
  }
  return { placed: [...placed, ...ghosts], ov };
}

function render() {
  canvas.querySelectorAll('.pt,.chip').forEach(m => m.remove());
  lines.innerHTML = '';
  const { placed, ov } = layout();
  for (const c of placed) {
    const dist = Math.hypot(c.bx - c.x, c.by - c.y);
    if (dist >= 16) for (const [color, w] of [['rgba(0,0,0,0.55)', 4], ['rgba(255,255,255,0.92)', 1.7]]) {
      const l = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      l.setAttribute('x1', c.x); l.setAttribute('y1', c.y); l.setAttribute('x2', c.bx); l.setAttribute('y2', c.by);
      l.setAttribute('stroke', color); l.setAttribute('stroke-width', w); l.setAttribute('stroke-linecap', 'round');
      lines.appendChild(l);
    }
    const chip = document.createElement('div');
    chip.className = 'chip' + (c.pinned ? ' pinned' : '') + (c.id === SEL ? ' sel' : '') + (ov.has(c.id) ? ' ov' : '') + (c.ghost ? ' ghost' : '');
    chip.style.left = c.bx + 'px'; chip.style.top = c.by + 'px';
    chip.style.transform = `translate(-50%,-50%) scale(${SCALE})`;
    chip.innerHTML = chipHTML(c, DATA ? DATA[c.key] : null) + `<div class="frame"></div><div class="tag">${esc(c.label)}${ov.has(c.id) ? ' · se pisa' : ''}${c.ghost ? ' · sin dato hoy' : ''}</div>`;
    chip.addEventListener('pointerdown', ev => startDrag(ev, c.id, chip));
    canvas.appendChild(chip);
    const dot = document.createElement('div');
    dot.className = 'pt' + (c.id === SEL ? ' sel' : '');
    dot.style.left = c.x + 'px'; dot.style.top = c.y + 'px'; dot.title = c.label;
    canvas.appendChild(dot);
  }
  // Panel: lista de ciudades (activas, apagadas) + selector de añadir.
  list.innerHTML = '';
  const extraIds = new Set(EXTRA.map(e => e.id));
  const rows = [...PLOTS.map(p => ({ ...p, extra: false })), ...EXTRA.filter(e => !PLOTS.some(p => p.id === e.id)).map(e => ({ ...e, extra: true }))];
  let nOn = 0;
  for (const p of rows) {
    const off = OFF.has(p.id) && !p.extra;
    if (!off) nOn++;
    const row = document.createElement('div');
    row.className = 'city' + (p.id === SEL ? ' sel' : '') + (off ? ' off' : '');
    const eye = document.createElement('button'); eye.type = 'button'; eye.className = 'eye';
    eye.textContent = off ? '🚫' : '👁'; eye.title = off ? 'Encender en esta escena' : 'Apagar en esta escena';
    eye.addEventListener('click', ev => { ev.stopPropagation(); if (off) OFF.delete(p.id); else { OFF.add(p.id); delete PL[p.id]; if (SEL === p.id) SEL = null; } render(); });
    row.appendChild(eye);
    const nm = document.createElement('span'); nm.className = 'nm';
    nm.innerHTML = esc(p.label) + (p.extra ? (p.custom ? ' <small>nueva</small>' : ' <small>añadida</small>') : '');
    row.appendChild(nm);
    if (!off) {
      if (DATA && DATA[p.key] == null) { const nd = document.createElement('span'); nd.className = 'nodata'; nd.textContent = 'sin dato'; row.appendChild(nd); }
      if (PL[p.id]) {
        const pos = document.createElement('span'); pos.className = 'pos'; pos.textContent = `${Math.round(PL[p.id].dx)},${Math.round(PL[p.id].dy)}`; row.appendChild(pos);
        const rm = document.createElement('button'); rm.className = 'rm'; rm.type = 'button'; rm.textContent = '×'; rm.title = 'Volver al colocador automático';
        rm.addEventListener('click', ev => { ev.stopPropagation(); delete PL[p.id]; render(); }); row.appendChild(rm);
      } else { const a = document.createElement('span'); a.className = 'auto'; a.textContent = 'auto'; row.appendChild(a); }
    }
    if (p.extra) {
      const rm = document.createElement('button'); rm.className = 'rm'; rm.type = 'button'; rm.textContent = '🗑'; rm.title = 'Quitar esta ciudad añadida';
      rm.addEventListener('click', ev => { ev.stopPropagation(); EXTRA = EXTRA.filter(e => e.id !== p.id); delete PL[p.id]; if (SEL === p.id) SEL = null; render(); }); row.appendChild(rm);
    }
    row.addEventListener('click', () => { if (off) return; SEL = (SEL === p.id ? null : p.id); render(); });
    list.appendChild(row);
  }
  document.getElementById('counts').textContent = `${nOn} en antena · ${rows.length - nOn} apagadas`;
  const sel = document.getElementById('addSel');
  const present = new Set(rows.map(r => r.id));
  sel.innerHTML = '<option value="">+ Añadir ciudad…</option>' + MASTER.filter(m => !present.has(m.id)).map(m => `<option value="${esc(m.id)}">${esc(m.label)}</option>`).join('');
  const ovBox = document.getElementById('ovBox');
  ovBox.style.display = ov.size ? 'block' : 'none';
  ovBox.textContent = ov.size ? `⚠ ${ov.size} cajas se pisan: ${[...ov].join(', ')}. Muévelas o apaga alguna.` : '';
}

function startDrag(ev, id, chip) {
  ev.preventDefault(); ev.stopPropagation();
  SEL = id; chip.classList.add('drag'); chip.setPointerCapture(ev.pointerId);
  const p = [...PLOTS, ...EXTRA].find(x => x.id === id), [px, py] = proj(p);
  const start = toCanvas(ev), startPos = { x: parseFloat(chip.style.left), y: parseFloat(chip.style.top) };
  const move = e => {
    const [x, y] = toCanvas(e);
    const nx = startPos.x + (x - start[0]), ny = startPos.y + (y - start[1]);
    PL[id] = { dx: Math.round(nx - px), dy: Math.round(ny - py) };
    chip.style.left = nx + 'px'; chip.style.top = ny + 'px';
  };
  const up = e => { chip.releasePointerCapture(e.pointerId); chip.removeEventListener('pointermove', move); chip.removeEventListener('pointerup', up); render(); };
  chip.addEventListener('pointermove', move); chip.addEventListener('pointerup', up);
}
stage.addEventListener('click', ev => {
  if (ev.target.closest('.chip') || !SEL) return;
  const p = [...PLOTS, ...EXTRA].find(x => x.id === SEL); if (!p) return;
  const [px, py] = proj(p), [x, y] = toCanvas(ev);
  PL[SEL] = { dx: Math.round(x - px), dy: Math.round(y - py) };
  render();
});
document.getElementById('addBtn').addEventListener('click', () => {
  const sel = document.getElementById('addSel'), m = MASTER.find(x => x.id === sel.value);
  if (!m) return;
  EXTRA.push({ id: m.id, label: m.label, name: m.name || m.label, key: m.key || m.id, lon: m.lon, lat: m.lat });
  SEL = m.id; render();
});

// ── Ciudad NUEVA (fuera de todos los catálogos): la producen los pipelines de
// nimbus (escaleta_cities.py). Clave de condiciones = "City|Estado completo"
// (así publica weather.json); en el resto la clave es el id. ──
const STATES = { AL: 'Alabama', AK: 'Alaska', AZ: 'Arizona', AR: 'Arkansas', CA: 'California', CO: 'Colorado', CT: 'Connecticut', DE: 'Delaware', DC: 'District of Columbia', FL: 'Florida', GA: 'Georgia', HI: 'Hawaii', ID: 'Idaho', IL: 'Illinois', IN: 'Indiana', IA: 'Iowa', KS: 'Kansas', KY: 'Kentucky', LA: 'Louisiana', ME: 'Maine', MD: 'Maryland', MA: 'Massachusetts', MI: 'Michigan', MN: 'Minnesota', MS: 'Mississippi', MO: 'Missouri', MT: 'Montana', NE: 'Nebraska', NV: 'Nevada', NH: 'New Hampshire', NJ: 'New Jersey', NM: 'New Mexico', NY: 'New York', NC: 'North Carolina', ND: 'North Dakota', OH: 'Ohio', OK: 'Oklahoma', OR: 'Oregon', PA: 'Pennsylvania', RI: 'Rhode Island', SC: 'South Carolina', SD: 'South Dakota', TN: 'Tennessee', TX: 'Texas', UT: 'Utah', VT: 'Vermont', VA: 'Virginia', WA: 'Washington', WV: 'West Virginia', WI: 'Wisconsin', WY: 'Wyoming', PR: 'Puerto Rico' };
const ncState = document.getElementById('ncState');
ncState.innerHTML += Object.entries(STATES).map(([c, n]) => `<option value="${c}">${n} (${c})</option>`).join('');
const ncMsg = document.getElementById('ncMsg');
const $ = id => document.getElementById(id);
document.getElementById('ncGeo').addEventListener('click', async () => {
  const q = ($('ncCity').value || $('ncLabel').value).trim(), st = ncState.value;
  if (!q) { ncMsg.textContent = 'Escribe la ciudad primero.'; return; }
  ncMsg.textContent = 'Buscando…';
  try {
    const url = `https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=us&q=${encodeURIComponent(q + (st ? ', ' + STATES[st] : '') + ', USA')}`;
    const r = await (await fetch(url, { headers: { 'Accept-Language': 'en' } })).json();
    if (!r.length) { ncMsg.textContent = 'No se encontró. Escribe lat/lon a mano.'; return; }
    $('ncLat').value = (+r[0].lat).toFixed(4); $('ncLon').value = (+r[0].lon).toFixed(4);
    ncMsg.textContent = 'Encontrado: ' + r[0].display_name;
  } catch (e) { ncMsg.textContent = 'Geocodificador no disponible; escribe lat/lon a mano.'; }
});
document.getElementById('ncAdd').addEventListener('click', () => {
  const label = $('ncLabel').value.trim(), city = ($('ncCity').value || label).trim(), st = ncState.value;
  const lat = parseFloat($('ncLat').value), lon = parseFloat($('ncLon').value);
  if (!label || !city || !st || isNaN(lat) || isNaN(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) { ncMsg.textContent = 'Faltan datos: nombre, ciudad en inglés, estado y lat/lon.'; return; }
  let id, key;
  if (SCENE === 'condiciones') { id = label; key = `${city}|${STATES[st]}`; }
  else if (SCENE === 'aeropuertos') { id = ($('ncIata').value || '').trim().toUpperCase(); if (!/^[A-Z]{3}$/.test(id)) { ncMsg.textContent = 'IATA de 3 letras.'; return; } key = id; }
  else { id = 'x-' + city.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); key = id; }
  if ([...PLOTS, ...EXTRA].some(p => p.id === id)) { ncMsg.textContent = 'Ya existe una ciudad con ese id.'; return; }
  EXTRA.push({ id, label, name: label, key, lon, lat, custom: true, city, state: st });
  ncMsg.textContent = `«${label}» añadida (sin dato hasta la próxima pasada de los pipelines).`;
  SEL = id; render();
});
const slider = document.getElementById('chipScale');
slider.addEventListener('input', () => { SCALE = parseFloat(slider.value); document.getElementById('scaleVal').textContent = SCALE.toFixed(2); render(); });
document.getElementById('saveForm').addEventListener('submit', () => {
  document.getElementById('placementJson').value = JSON.stringify(PL);
  // Del maestro basta el id (el PHP copia sus datos); las nuevas van completas.
  document.getElementById('citiesJson').value = JSON.stringify({ off: [...OFF], extra: EXTRA.map(e => e.custom ? e : e.id) });
  document.getElementById('chipScaleField').value = slider.value;
});
render();
loadFeed();
</script>
</body>
</html>
