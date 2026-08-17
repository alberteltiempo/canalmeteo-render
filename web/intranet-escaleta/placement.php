<?php
/**
 * Escaleta — editor VISUAL de posición de las cajas de ciudad ("no puedo mover
 * los plots"). Se trabaja sobre la vista previa real (Still Prev-condiciones,
 * que ya sale con la cámara/escala/posiciones de la escaleta): se selecciona
 * una ciudad y se hace clic —o se arrastra su marcador— para fijarla en px del
 * lienzo 1920×1080. Lo no fijado lo sigue colocando el anti-solape automático.
 *
 * Guardar hace read-modify-write del JSON publicado (solo toca `placement`,
 * nunca escenas/cámara/umbrales) y encola una preview nueva para ver el
 * resultado en ~1-2 min.
 */
require_once dirname(__DIR__) . '/includes/auth.php';
requireSection('escaleta');
require_once __DIR__ . '/lib.php';

$slug = $_GET['p'] ?? '';
$scene = 'condiciones'; // de momento la única escena con posiciones editables
$catalog = esc_catalog();
$product = $catalog['products'][$slug] ?? null;
$cities = $product['cities'][$scene] ?? [];
if (!$product || !$cities) { http_response_code(404); exit('Producto sin editor de posición'); }

$user = getCurrentUserName();
$self = 'placement.php?p=' . rawurlencode($slug);

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    csrfCheck();
    $action = $_POST['action'] ?? '';
    if ($action === 'save') {
        $raw = json_decode($_POST['placement'] ?? '', true);
        $clean = esc_clean_placement(is_array($raw) ? $raw : [], $cities);
        // Read-modify-write sobre el JSON publicado: este editor SOLO toca
        // `placement` — escenas, cámara, umbrales y ui quedan como estaban.
        $cfg = esc_config($slug) ?? ['version' => 1];
        $cfg['updated'] = gmdate('c');
        $cfg['updatedBy'] = $user;
        if ($clean) {
            $cfg['placement'][$scene] = $clean;
        } else {
            unset($cfg['placement'][$scene]);
            if (empty($cfg['placement'])) unset($cfg['placement']);
        }
        if (esc_spool("{$slug}.json", $cfg)) {
            // Preview nueva para ver las cajas donde se han dejado. Se pide con
            // un pequeño margen para que el push (cron de nimbus) publique antes.
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
$previewUrl = ESC_CDN . '/previews/' . rawurlencode($slug) . '/' . $scene . '.png?ts=' . time();
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
<title><?= htmlspecialchars($product['nombre']) ?> · Posición de cajas</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;600;700&family=JetBrains+Mono:wght@600&display=swap" rel="stylesheet">
<style>
  body{font-family:Outfit,system-ui,sans-serif;background:#0d1a26;color:#eef4f8;margin:0;padding:32px}
  a{color:#7cc4ff;text-decoration:none}
  h1{font-size:24px;margin:0 0 4px}
  .sub{color:#9db4c4;margin-bottom:20px;font-size:14px}
  .msg{padding:10px 16px;border-radius:10px;margin-bottom:18px;max-width:1200px;font-size:15px}
  .ok{background:#123a24;border:1px solid #2ecc71}
  .err{background:#3a1212;border:1px solid #e74c3c}
  .cols{display:flex;gap:22px;align-items:flex-start;flex-wrap:wrap}
  /* Escenario 16:9 SIEMPRE (aunque falte la imagen): los clics se convierten a
     px del lienzo 1920×1080 con una regla de tres sobre su tamaño en pantalla. */
  #stage{position:relative;flex:1 1 720px;max-width:1180px;aspect-ratio:16/9;background:#08131c;
         border:1px solid rgba(255,255,255,.2);border-radius:10px;overflow:hidden;cursor:crosshair;user-select:none}
  #stage img{position:absolute;inset:0;width:100%;height:100%;display:block;pointer-events:none}
  #noimg{position:absolute;inset:0;display:none;align-items:center;justify-content:center;color:#9db4c4;font-size:15px;text-align:center;padding:30px}
  .mark{position:absolute;transform:translate(-50%,-50%);cursor:grab;z-index:5}
  .mark.drag{cursor:grabbing;z-index:9}
  .mark .dot{width:14px;height:14px;border-radius:50%;background:#2ee6d6;border:2px solid #04222b;box-shadow:0 0 8px rgba(0,0,0,.8);margin:0 auto}
  .mark .tag{margin-top:3px;background:rgba(4,20,30,.85);border:1px solid #2ee6d6;color:#d9fffa;font-size:12px;
             padding:1px 7px;border-radius:7px;white-space:nowrap}
  .mark.sel .dot{background:#ffd24a;border-color:#3a2b00}
  .mark.sel .tag{border-color:#ffd24a;color:#fff2c4}
  .panel{flex:0 0 300px;background:#10222f;border:1px solid rgba(255,255,255,.14);border-radius:12px;padding:14px 16px}
  .panel h2{font-size:15px;margin:0 0 10px;color:#9db4c4;text-transform:uppercase;letter-spacing:1px}
  .city{display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:8px;cursor:pointer;font-size:15px}
  .city:hover{background:rgba(255,255,255,.06)}
  .city.sel{background:#1f5f9e33;outline:1px solid #7cc4ff}
  .city .pos{margin-left:auto;font-family:'JetBrains Mono',monospace;font-size:12px;color:#2ee6d6}
  .city .auto{margin-left:auto;font-size:12px;color:#5f7787}
  .city .rm{background:none;border:0;color:#e74c3c;font-size:15px;cursor:pointer;padding:0 2px}
  .btn{background:#1f5f9e;color:#fff;border:0;border-radius:10px;padding:10px 22px;font-family:Outfit;font-weight:700;font-size:16px;cursor:pointer}
  .btn.sm{padding:5px 12px;font-size:13px;background:#16324a}
  .btn:hover{filter:brightness(1.15)}
  .hint{color:#9db4c4;font-size:13px;margin-top:10px;line-height:1.5}
</style>
</head>
<body>
<h1><?= htmlspecialchars($product['nombre']) ?> <span style="color:#9db4c4">· posición de cajas · Condiciones ahora</span></h1>
<div class="sub"><a href="edit.php?p=<?= rawurlencode($slug) ?>">← Escaleta del producto</a> ·
  El marcador es el CENTRO de la caja; el punto blanco de la ciudad no se mueve.</div>

<?php if ($msg): ?><div class="msg <?= $isErr ? 'err' : 'ok' ?>"><?= htmlspecialchars($msg) ?></div><?php endif; ?>

<div class="cols">
  <div id="stage">
    <img id="prevImg" src="<?= htmlspecialchars($previewUrl) ?>" alt=""
         onerror="this.style.display='none';document.getElementById('noimg').style.display='flex'">
    <div id="noimg">Aún no hay vista previa de esta escena.<br>
      Pide una con «Regenerar preview» (abajo) y recarga en ~2 min.<br>
      Mientras tanto puedes fijar posiciones a ciegas sobre el lienzo.</div>
  </div>

  <div class="panel">
    <h2>Ciudades</h2>
    <div id="cityList"></div>
    <form method="post" id="saveForm" style="margin-top:14px">
      <?= csrfField() ?>
      <input type="hidden" name="action" value="save">
      <input type="hidden" name="placement" id="placementJson" value="">
      <button class="btn" type="submit">Guardar y publicar</button>
    </form>
    <form method="post" style="margin-top:8px">
      <?= csrfField() ?>
      <input type="hidden" name="action" value="preview">
      <button class="btn sm" type="submit">Regenerar preview</button>
    </form>
    <div class="hint">
      1. Elige una ciudad de la lista.<br>
      2. Haz clic en el mapa donde quieras su caja (o arrastra un marcador ya puesto).<br>
      3. «×» la devuelve al colocador automático.<br>
      Al guardar se encola una preview nueva con las cajas en su sitio.
    </div>
  </div>
</div>

<script>
const CITIES = <?= json_encode(array_values($cities), JSON_UNESCAPED_UNICODE) ?>;
const PL = <?= json_encode((object) $placed, JSON_UNESCAPED_UNICODE) ?>; // {ciudad: [x,y]} en px 1920×1080
let SEL = null;

const stage = document.getElementById('stage');
const list = document.getElementById('cityList');

function toCanvas(ev) {
  const r = stage.getBoundingClientRect();
  const x = Math.max(0, Math.min(1920, (ev.clientX - r.left) / r.width * 1920));
  const y = Math.max(0, Math.min(1080, (ev.clientY - r.top) / r.height * 1080));
  return [Math.round(x), Math.round(y)];
}

function render() {
  // Marcadores (uno por ciudad fijada), en % para que sigan al responsive.
  stage.querySelectorAll('.mark').forEach(m => m.remove());
  for (const [city, xy] of Object.entries(PL)) {
    const m = document.createElement('div');
    m.className = 'mark' + (city === SEL ? ' sel' : '');
    m.style.left = (xy[0] / 1920 * 100) + '%';
    m.style.top = (xy[1] / 1080 * 100) + '%';
    m.innerHTML = '<div class="dot"></div><div class="tag"></div>';
    m.querySelector('.tag').textContent = city;
    m.addEventListener('pointerdown', ev => startDrag(ev, city, m));
    stage.appendChild(m);
  }
  // Lista lateral.
  list.innerHTML = '';
  for (const city of CITIES) {
    const row = document.createElement('div');
    row.className = 'city' + (city === SEL ? ' sel' : '');
    const name = document.createElement('span');
    name.textContent = city;
    row.appendChild(name);
    if (PL[city]) {
      const pos = document.createElement('span');
      pos.className = 'pos';
      pos.textContent = PL[city][0] + ',' + PL[city][1];
      row.appendChild(pos);
      const rm = document.createElement('button');
      rm.className = 'rm'; rm.type = 'button'; rm.textContent = '×';
      rm.title = 'Volver al colocador automático';
      rm.addEventListener('click', ev => { ev.stopPropagation(); delete PL[city]; render(); });
      row.appendChild(rm);
    } else {
      const auto = document.createElement('span');
      auto.className = 'auto';
      auto.textContent = 'automática';
      row.appendChild(auto);
    }
    row.addEventListener('click', () => { SEL = (SEL === city ? null : city); render(); });
    list.appendChild(row);
  }
}

function startDrag(ev, city, m) {
  ev.preventDefault(); ev.stopPropagation();
  SEL = city;
  m.classList.add('drag');
  m.setPointerCapture(ev.pointerId);
  const move = e => { PL[city] = toCanvas(e); m.style.left = (PL[city][0] / 1920 * 100) + '%'; m.style.top = (PL[city][1] / 1080 * 100) + '%'; };
  const up = e => {
    m.releasePointerCapture(e.pointerId);
    m.removeEventListener('pointermove', move);
    m.removeEventListener('pointerup', up);
    render();
  };
  m.addEventListener('pointermove', move);
  m.addEventListener('pointerup', up);
}

stage.addEventListener('click', ev => {
  if (ev.target.closest('.mark')) return;
  if (!SEL) return;
  PL[SEL] = toCanvas(ev);
  render();
});

document.getElementById('saveForm').addEventListener('submit', () => {
  document.getElementById('placementJson').value = JSON.stringify(PL);
});

render();
</script>
</body>
</html>
