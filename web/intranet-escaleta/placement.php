<?php
/**
 * Escaleta — editor VISUAL de posición y tamaño de los plots de datos.
 *
 * Vale para todas las escenas con chips/cajas por punto (condiciones, UV, AQI,
 * aeropuertos, máximas, variación): el catálogo publica products[slug].plots
 * con {id, label, lon, lat, w, h} por escena. Sobre la vista previa real se
 * arrastra el CONTORNO de cada caja (tamaño real a escala) y se ve la línea
 * que la conecta con su punto; el punto se calcula reproyectando lon/lat con
 * la misma cámara del render (mercator + fitBounds con padding, en JS).
 *
 * Guardar hace read-modify-write del JSON publicado (solo toca
 * placement.<escena> y ui.chipScale) y encola una preview nueva.
 */
require_once dirname(__DIR__) . '/includes/auth.php';
requireSection('escaleta');
require_once __DIR__ . '/lib.php';

$slug = $_GET['p'] ?? '';
$scene = $_GET['scene'] ?? 'condiciones';
$catalog = esc_catalog();
$product = $catalog['products'][$slug] ?? null;
$plots = $product['plots'][$scene] ?? [];
if (!$product || !$plots) { http_response_code(404); exit('Producto o escena sin editor de posición'); }

$user = getCurrentUserName();
$self = 'placement.php?p=' . rawurlencode($slug) . '&scene=' . rawurlencode($scene);
$ids = array_column($plots, 'id');

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    csrfCheck();
    $action = $_POST['action'] ?? '';
    if ($action === 'save') {
        $raw = json_decode($_POST['placement'] ?? '', true);
        $clean = esc_clean_placement(is_array($raw) ? $raw : [], $ids);
        // Read-modify-write del JSON publicado: SOLO placement.<escena> y
        // ui.chipScale — escenas, cámara y umbrales quedan como estaban.
        $cfg = esc_config($slug) ?? ['version' => 1];
        $cfg['updated'] = gmdate('c');
        $cfg['updatedBy'] = $user;
        if ($clean) {
            $cfg['placement'][$scene] = $clean;
        } else {
            unset($cfg['placement'][$scene]);
            if (empty($cfg['placement'])) unset($cfg['placement']);
        }
        $sc = $_POST['chipScale'] ?? '';
        if ($sc !== '' && is_numeric($sc) && (float) $sc >= 0.7 && (float) $sc <= 1.4) {
            if (abs((float) $sc - 1.0) < 0.001) {
                unset($cfg['ui']['chipScale']);
                if (empty($cfg['ui'])) unset($cfg['ui']);
            } else {
                $cfg['ui']['chipScale'] = (float) $sc;
            }
        }
        if (esc_spool("{$slug}.json", $cfg)) {
            // Preview nueva con margen para que el push publique el JSON antes.
            esc_spool("preview_{$slug}_{$scene}.json", ['slug' => $slug, 'scene' => $scene, 'ts' => time() + 60, 'by' => $user]);
            header('Location: ' . $self . '&m=saved'); exit;
        }
        header('Location: ' . $self . '&m=spoolerr'); exit;
    }
    if ($action === 'preview') {
        esc_spool("preview_{$slug}_{$scene}.json", ['slug' => $slug, 'scene' => $scene, 'ts' => time(), 'by' => $user]);
        header('Location: ' . $self . '&m=prev'); exit;
    }
}

$cfg = esc_config($slug);
$placed = $cfg['placement'][$scene] ?? [];
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
$sceneLabel = $product['scenes'][$scene]['label'] ?? $scene;
$previewUrl = ESC_CDN . '/previews/' . rawurlencode($slug) . '/' . rawurlencode($scene) . '.png?ts=' . time();
$msg = [
    'saved' => 'Guardado. Se publica en ≤1 min y se ha encolado una preview nueva (recarga en ~2-3 min para verla).',
    'prev' => 'Vista previa solicitada: calamarsa la renderiza en 1-3 min (recarga la página).',
    'spoolerr' => 'No se pudo escribir en el buzón (outbox no accesible)',
][$_GET['m'] ?? ''] ?? null;
$isErr = ($_GET['m'] ?? '') === 'spoolerr';
?>
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title><?= htmlspecialchars($product['nombre']) ?> · <?= htmlspecialchars($sceneLabel) ?> · Posición</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;600;700&family=JetBrains+Mono:wght@600&display=swap" rel="stylesheet">
<style>
  body{font-family:Outfit,system-ui,sans-serif;background:#0d1a26;color:#eef4f8;margin:0;padding:32px}
  a{color:#7cc4ff;text-decoration:none}
  h1{font-size:24px;margin:0 0 4px}
  .sub{color:#9db4c4;margin-bottom:14px;font-size:14px}
  .tabs{margin-bottom:14px;display:flex;gap:8px;flex-wrap:wrap}
  .tabs a{background:#16324a;border-radius:8px;padding:5px 12px;font-size:13px;font-weight:700;color:#cfe4f5}
  .tabs a.cur{background:#1f5f9e;color:#fff}
  .msg{padding:10px 16px;border-radius:10px;margin-bottom:18px;max-width:1200px;font-size:15px}
  .ok{background:#123a24;border:1px solid #2ecc71}
  .err{background:#3a1212;border:1px solid #e74c3c}
  .cols{display:flex;gap:22px;align-items:flex-start;flex-wrap:wrap}
  /* Escenario 16:9 SIEMPRE (aunque falte la imagen): clics y cajas en px del
     lienzo 1920×1080 con regla de tres sobre el tamaño en pantalla. */
  #stage{position:relative;flex:1 1 720px;max-width:1180px;aspect-ratio:16/9;background:#08131c;
         border:1px solid rgba(255,255,255,.2);border-radius:10px;overflow:hidden;cursor:crosshair;user-select:none}
  #stage img{position:absolute;inset:0;width:100%;height:100%;display:block;pointer-events:none}
  #noimg{position:absolute;inset:0;display:none;align-items:center;justify-content:center;color:#9db4c4;font-size:15px;text-align:center;padding:30px}
  #lines{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
  .pt{position:absolute;width:10px;height:10px;border-radius:50%;background:#fff;border:2px solid rgba(0,0,0,.65);
      transform:translate(-50%,-50%);box-shadow:0 0 6px rgba(0,0,0,.7);pointer-events:none;z-index:3}
  .pt.sel{background:#ffd24a}
  .box{position:absolute;transform:translate(-50%,-50%);border:2px solid #2ee6d6;border-radius:8px;
       background:rgba(9,30,40,.35);display:flex;align-items:center;justify-content:center;text-align:center;
       color:#d9fffa;font-size:12px;font-weight:700;cursor:grab;z-index:5;overflow:hidden;padding:2px}
  .box.drag{cursor:grabbing;z-index:9}
  .box.sel{border-color:#ffd24a;color:#fff2c4}
  .panel{flex:0 0 320px;background:#10222f;border:1px solid rgba(255,255,255,.14);border-radius:12px;padding:14px 16px}
  .panel h2{font-size:15px;margin:0 0 10px;color:#9db4c4;text-transform:uppercase;letter-spacing:1px}
  .scale{margin:0 0 14px;padding-bottom:12px;border-bottom:1px solid rgba(255,255,255,.12)}
  .scale input[type=range]{width:100%}
  .scale .val{font-family:'JetBrains Mono',monospace;color:#2ee6d6}
  #cityList{max-height:430px;overflow:auto}
  .city{display:flex;align-items:center;gap:8px;padding:5px 8px;border-radius:8px;cursor:pointer;font-size:14px}
  .city:hover{background:rgba(255,255,255,.06)}
  .city.sel{background:#1f5f9e33;outline:1px solid #7cc4ff}
  .city .pos{margin-left:auto;font-family:'JetBrains Mono',monospace;font-size:11px;color:#2ee6d6}
  .city .auto{margin-left:auto;font-size:11px;color:#5f7787}
  .city .rm{background:none;border:0;color:#e74c3c;font-size:15px;cursor:pointer;padding:0 2px}
  .btn{background:#1f5f9e;color:#fff;border:0;border-radius:10px;padding:10px 22px;font-family:Outfit;font-weight:700;font-size:16px;cursor:pointer}
  .btn.sm{padding:5px 12px;font-size:13px;background:#16324a}
  .btn:hover{filter:brightness(1.15)}
  .hint{color:#9db4c4;font-size:13px;margin-top:10px;line-height:1.5}
</style>
</head>
<body>
<h1><?= htmlspecialchars($product['nombre']) ?> <span style="color:#9db4c4">· posición de plots · <?= htmlspecialchars($sceneLabel) ?></span></h1>
<div class="sub"><a href="edit.php?p=<?= rawurlencode($slug) ?>">← Escaleta del producto</a> ·
  El contorno es la caja a tamaño real; la línea la une con su punto de datos (que no se mueve).</div>

<div class="tabs">
<?php foreach (($product['plots'] ?? []) as $k => $pl): if (!$pl) continue; ?>
  <a class="<?= $k === $scene ? 'cur' : '' ?>" href="placement.php?p=<?= rawurlencode($slug) ?>&scene=<?= rawurlencode($k) ?>">
    <?= htmlspecialchars($product['scenes'][$k]['label'] ?? $k) ?></a>
<?php endforeach; ?>
</div>

<?php if ($msg): ?><div class="msg <?= $isErr ? 'err' : 'ok' ?>"><?= htmlspecialchars($msg) ?></div><?php endif; ?>

<div class="cols">
  <div id="stage">
    <img id="prevImg" src="<?= htmlspecialchars($previewUrl) ?>" alt=""
         onerror="this.style.display='none';document.getElementById('noimg').style.display='flex'">
    <div id="noimg">Aún no hay vista previa de esta escena.<br>
      Pide una con «Regenerar preview» y recarga en ~2 min.<br>
      Mientras tanto los puntos blancos te sitúan cada ciudad.</div>
    <svg id="lines" viewBox="0 0 1920 1080" preserveAspectRatio="none"></svg>
  </div>

  <div class="panel">
    <div class="scale">
      <b>Tamaño de los plots</b> ×<span class="val" id="scaleVal"><?= htmlspecialchars(number_format((float) $chipScale, 2)) ?></span>
      <input type="range" id="chipScale" min="0.7" max="1.4" step="0.05" value="<?= htmlspecialchars((string) $chipScale) ?>">
      <div class="hint" style="margin-top:2px">Escala GLOBAL de chips/cajas del producto (todas las escenas). Los contornos del lienzo escalan en vivo; el render aplica el mismo factor.</div>
    </div>
    <h2>Plots</h2>
    <div id="cityList"></div>
    <form method="post" id="saveForm" style="margin-top:14px">
      <?= csrfField() ?>
      <input type="hidden" name="action" value="save">
      <input type="hidden" name="placement" id="placementJson" value="">
      <input type="hidden" name="chipScale" id="chipScaleField" value="">
      <button class="btn" type="submit">Guardar y publicar</button>
    </form>
    <form method="post" style="margin-top:8px">
      <?= csrfField() ?>
      <input type="hidden" name="action" value="preview">
      <button class="btn sm" type="submit">Regenerar preview</button>
    </form>
    <div class="hint">
      1. Elige un plot de la lista (o pincha su contorno).<br>
      2. Clic en el mapa donde quieras la caja, o arrastra el contorno.<br>
      3. «×» lo devuelve al colocador automático.<br>
      Al guardar se encola una preview nueva.
    </div>
  </div>
</div>

<script>
const PLOTS = <?= json_encode(array_values($plots), JSON_UNESCAPED_UNICODE) ?>; // {id,label,lon,lat,w,h}
const PL = <?= json_encode((object) $placed, JSON_UNESCAPED_UNICODE) ?>;        // {id: [x,y]} px 1920×1080
const CAM = <?= json_encode($cam) ?>;
let SCALE = <?= json_encode((float) $chipScale) ?>;
let SEL = null;

const stage = document.getElementById('stage');
const list = document.getElementById('cityList');
const lines = document.getElementById('lines');
const byId = Object.fromEntries(PLOTS.map(p => [p.id, p]));

// Reproyección mercator con el MISMO encuadre que el render: fitBounds del
// bbox con padding (bbox centrado e íntegro dentro del área útil).
const merc = lat => { const s = Math.sin(lat * Math.PI / 180); return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI); };
const mx0 = (CAM.west + 180) / 360, mx1 = (CAM.east + 180) / 360;
const my0 = merc(CAM.north), my1 = merc(CAM.south);
const availW = 1920 - (CAM.padLeft || 0) - (CAM.padRight || 0);
const availH = 1080 - (CAM.padTop || 0) - (CAM.padBottom || 0);
const sc = Math.min(availW / (mx1 - mx0), availH / (my1 - my0));
const offX = (CAM.padLeft || 0) + (availW - (mx1 - mx0) * sc) / 2 - mx0 * sc;
const offY = (CAM.padTop || 0) + (availH - (my1 - my0) * sc) / 2 - my0 * sc;
const proj = p => [((p.lon + 180) / 360) * sc + offX, merc(p.lat) * sc + offY];

function toCanvas(ev) {
  const r = stage.getBoundingClientRect();
  const x = Math.max(0, Math.min(1920, (ev.clientX - r.left) / r.width * 1920));
  const y = Math.max(0, Math.min(1080, (ev.clientY - r.top) / r.height * 1080));
  return [Math.round(x), Math.round(y)];
}
const pctX = v => (v / 1920 * 100) + '%';
const pctY = v => (v / 1080 * 100) + '%';

function render() {
  stage.querySelectorAll('.pt,.box').forEach(m => m.remove());
  lines.innerHTML = '';
  for (const p of PLOTS) {
    const [px, py] = proj(p);
    const dot = document.createElement('div');
    dot.className = 'pt' + (p.id === SEL ? ' sel' : '');
    dot.style.left = pctX(px); dot.style.top = pctY(py);
    dot.title = p.label;
    stage.appendChild(dot);
    const xy = PL[p.id];
    if (!xy) continue;
    // Línea punto→caja (misma pareja negro+blanco que el render).
    for (const [color, w] of [["rgba(0,0,0,0.55)", 4], ["rgba(255,255,255,0.92)", 1.7]]) {
      const l = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      l.setAttribute('x1', px); l.setAttribute('y1', py);
      l.setAttribute('x2', xy[0]); l.setAttribute('y2', xy[1]);
      l.setAttribute('stroke', color); l.setAttribute('stroke-width', w);
      l.setAttribute('stroke-linecap', 'round');
      lines.appendChild(l);
    }
    const b = document.createElement('div');
    b.className = 'box' + (p.id === SEL ? ' sel' : '');
    b.style.left = pctX(xy[0]); b.style.top = pctY(xy[1]);
    b.style.width = pctX(p.w * SCALE); b.style.height = pctY(p.h * SCALE);
    b.textContent = p.label;
    b.addEventListener('pointerdown', ev => startDrag(ev, p.id, b));
    stage.appendChild(b);
  }
  list.innerHTML = '';
  for (const p of PLOTS) {
    const row = document.createElement('div');
    row.className = 'city' + (p.id === SEL ? ' sel' : '');
    const name = document.createElement('span');
    name.textContent = p.label;
    row.appendChild(name);
    if (PL[p.id]) {
      const pos = document.createElement('span');
      pos.className = 'pos';
      pos.textContent = PL[p.id][0] + ',' + PL[p.id][1];
      row.appendChild(pos);
      const rm = document.createElement('button');
      rm.className = 'rm'; rm.type = 'button'; rm.textContent = '×';
      rm.title = 'Volver al colocador automático';
      rm.addEventListener('click', ev => { ev.stopPropagation(); delete PL[p.id]; render(); });
      row.appendChild(rm);
    } else {
      const auto = document.createElement('span');
      auto.className = 'auto';
      auto.textContent = 'automático';
      row.appendChild(auto);
    }
    row.addEventListener('click', () => { SEL = (SEL === p.id ? null : p.id); render(); });
    list.appendChild(row);
  }
}

function startDrag(ev, id, b) {
  ev.preventDefault(); ev.stopPropagation();
  SEL = id;
  b.classList.add('drag');
  b.setPointerCapture(ev.pointerId);
  const p = byId[id], [px, py] = proj(p);
  const move = e => {
    PL[id] = toCanvas(e);
    b.style.left = pctX(PL[id][0]); b.style.top = pctY(PL[id][1]);
    // La pareja de líneas de este plot son las 2 últimas creadas para él; más
    // simple: re-render de líneas al soltar, aquí solo movemos la caja.
  };
  const up = e => {
    b.releasePointerCapture(e.pointerId);
    b.removeEventListener('pointermove', move);
    b.removeEventListener('pointerup', up);
    render();
  };
  b.addEventListener('pointermove', move);
  b.addEventListener('pointerup', up);
}

stage.addEventListener('click', ev => {
  if (ev.target.closest('.box')) return;
  if (!SEL) return;
  PL[SEL] = toCanvas(ev);
  render();
});

const slider = document.getElementById('chipScale');
slider.addEventListener('input', () => {
  SCALE = parseFloat(slider.value);
  document.getElementById('scaleVal').textContent = SCALE.toFixed(2);
  render();
});

document.getElementById('saveForm').addEventListener('submit', () => {
  document.getElementById('placementJson').value = JSON.stringify(PL);
  document.getElementById('chipScaleField').value = slider.value;
});

render();
</script>
</body>
</html>
