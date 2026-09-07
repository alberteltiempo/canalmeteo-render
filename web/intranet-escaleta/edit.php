<?php
/** Escaleta — edición de un producto: escenas on/off, orden, duraciones, umbrales, previews e historial. */
require_once dirname(__DIR__) . '/includes/auth.php';
requireSection('escaleta');
require_once __DIR__ . '/lib.php';

$slug = $_GET['p'] ?? '';
$catalog = esc_catalog();
$product = $catalog['products'][$slug] ?? null;
if (!$product) { http_response_code(404); exit('Producto desconocido'); }

$user = getCurrentUserName();
$notice = null; $error = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    csrfCheck();
    $action = $_POST['action'] ?? '';
    if ($action === 'preview') {
        $scene = $_POST['scene'] ?? '';
        if (esc_preview_still($slug, $scene)) {
            $ok = esc_request_preview($slug, $scene, $user);
            $notice = $ok
                ? "Vista previa de «{$scene}» solicitada: calamarsa la renderiza en 1–3 min (recarga la página)."
                : 'No se pudo escribir en el buzón (outbox no accesible)';
        } else {
            $error = 'Esa escena no tiene vista previa disponible';
        }
    } elseif ($action === 'preview_all') {
        // Encola TODAS las escenas con preview; calamarsa las va sirviendo en
        // orden (~1 min por escena, respetando el lock de GPU de producción).
        $n = 0;
        foreach ($product['scenes'] as $key => $_meta) {
            if (esc_preview_still($slug, $key) && esc_request_preview($slug, $key, $user)) $n++;
        }
        $notice = $n
            ? "{$n} vistas previas encoladas: irán apareciendo durante los próximos ~{$n} minutos (recarga la página)."
            : 'No se pudo encolar ninguna preview';
    } elseif ($action === 'restore') {
        // Restaurar una versión del historial: pasa a ser la vigente y la actual
        // se apila (así el "deshacer" también se puede deshacer).
        $prev = esc_config($slug);
        $idx = (int) ($_POST['idx'] ?? -1);
        $entry = $prev['history'][$idx] ?? null;
        if (!$entry || !is_array($entry['config'] ?? null)) {
            $error = 'Esa versión ya no está en el historial';
        } else {
            $snap = $entry['config'];
            $when = substr((string) ($entry['ts'] ?? ''), 0, 16);
            if (esc_save_config($slug, $snap, $prev, $user, "Restaurada la versión de {$when} UTC ({$entry['by']})")) {
                $notice = "Versión de {$when} UTC restaurada. Se publica en ≤1 min.";
            } else {
                $error = 'No se pudo escribir en el buzón (outbox no accesible)';
            }
        }
    } else {
        [$cfg, $err] = esc_build_config($slug, $product, $_POST, $user);
        $prev = esc_config($slug);
        if (!$err) {
            $err = esc_conflict($prev, (string) ($_POST['base_updated'] ?? ''), isset($_POST['force']));
        }
        if (!$err) {
            // Posiciones fijadas y ciudades se editan en placement.php, no aquí:
            // se arrastran de la config vigente para que guardar no las borre.
            foreach (['placement', 'cities'] as $k) {
                if (isset($prev[$k]) && is_array($prev[$k]) && $prev[$k]) $cfg[$k] = $prev[$k];
            }
            $note = trim((string) ($_POST['note'] ?? ''));
            if ($note === '') $note = 'Escaleta: ' . esc_summary($cfg, $product);
        }
        if ($err) {
            $error = $err;
        } elseif (esc_save_config($slug, $cfg, $prev, $user, $note)) {
            $notice = 'Guardado. Se publica al CDN en ≤1 min y aplica en el siguiente render.';
        } else {
            $error = 'No se pudo escribir en el buzón (outbox no accesible)';
        }
    }
}

$cfg = esc_config($slug);
$scenes = $product['scenes'];
// Orden efectivo: el de la escaleta (claves válidas) y después el resto en el
// orden de código (= el del catálogo).
$keys = array_keys($scenes);
$ordered = [];
foreach ((array) ($cfg['order'] ?? []) as $k) if (in_array($k, $keys, true) && !in_array($k, $ordered, true)) $ordered[] = $k;
foreach ($keys as $k) if (!in_array($k, $ordered, true)) $ordered[] = $k;
$canOrder = $slug !== 'tropico';
$previewBase = ESC_CDN . '/previews/' . rawurlencode($slug);
$history = is_array($cfg['history'] ?? null) ? $cfg['history'] : [];
$conflictErr = $error && strncmp($error, '⚠', strlen('⚠')) === 0;
?>
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title><?= htmlspecialchars($product['nombre']) ?> · Escaleta</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;600;700&family=JetBrains+Mono:wght@600&display=swap" rel="stylesheet">
<style>
  body{font-family:Outfit,system-ui,sans-serif;background:#0d1a26;color:#eef4f8;margin:0;padding:32px}
  a{color:#7cc4ff;text-decoration:none}
  h1{font-size:24px;margin:0 0 4px}
  .sub{color:#9db4c4;margin-bottom:20px;font-size:14px}
  .msg{padding:10px 16px;border-radius:10px;margin-bottom:18px;max-width:900px;font-size:15px}
  .ok{background:#123a24;border:1px solid #2ecc71}
  .err{background:#3a1212;border:1px solid #e74c3c}
  table{border-collapse:collapse;max-width:980px;width:100%}
  th,td{padding:8px 12px;text-align:left;border-bottom:1px solid rgba(255,255,255,.1);font-size:15px}
  th{color:#9db4c4;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:1px}
  tr.off td{opacity:.45}
  tr.dragging td{opacity:.3}
  tr.over td{border-top:2px solid #2ee6d6}
  .grip{cursor:grab;color:#5f7787;font-size:18px;user-select:none;padding-right:4px}
  .updown button{background:#16324a;border:0;color:#cfe4f5;border-radius:6px;width:26px;height:22px;cursor:pointer;font-size:12px;padding:0}
  .updown button:hover{filter:brightness(1.2)}
  .pos{font-family:'JetBrains Mono',monospace;color:#5f7787;font-size:12px;width:22px;display:inline-block}
  input[type=number]{width:70px;background:#12283a;color:#fff;border:1px solid rgba(255,255,255,.25);border-radius:8px;padding:6px 8px;font-family:'JetBrains Mono',monospace}
  input[type=text]{background:#12283a;color:#fff;border:1px solid rgba(255,255,255,.25);border-radius:8px;padding:8px 10px;font-family:Outfit;font-size:14px}
  input[type=checkbox]{transform:scale(1.35)}
  .cond{color:#f4a020;font-size:12px}
  .btn{background:#1f5f9e;color:#fff;border:0;border-radius:10px;padding:10px 22px;font-family:Outfit;font-weight:700;font-size:16px;cursor:pointer}
  .btn.sm{padding:5px 12px;font-size:13px;background:#16324a}
  .btn:hover{filter:brightness(1.15)}
  .th-box{background:#10222f;border:1px solid rgba(255,255,255,.14);border-radius:12px;padding:14px 18px;margin:18px 0;max-width:940px}
  .prev{margin-top:6px}
  .prev img{max-width:420px;border-radius:8px;border:1px solid rgba(255,255,255,.2);display:block;margin-top:6px}
  .hist{font-size:14px}
  .hist .row{display:flex;gap:12px;align-items:center;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.08)}
  .hist .when{font-family:'JetBrains Mono',monospace;color:#2ee6d6;font-size:12px;white-space:nowrap}
  .hist .by{color:#9db4c4;white-space:nowrap}
  .hist .note{flex:1;color:#dfe8f0}
  .hint{color:#9db4c4;font-size:13px;margin-top:6px}
</style>
</head>
<body>
<h1><?= htmlspecialchars($product['nombre']) ?> <span style="color:#9db4c4">· escaleta</span></h1>
<div class="sub"><a href="index.php">← Todos los productos</a> · Los cambios aplican en el siguiente render (cron horario<?= $slug === 'tropico' ? ' / por boletín del NHC' : '' ?>).
<?php if (!empty($cfg['updated'])): ?> · Vigente: <?= htmlspecialchars(substr($cfg['updated'], 0, 16)) ?> UTC · <?= htmlspecialchars($cfg['updatedBy'] ?? '—') ?><?php if (!empty($cfg['note'])): ?> · «<?= htmlspecialchars($cfg['note']) ?>»<?php endif; ?><?php endif; ?>
</div>

<?php if ($notice): ?><div class="msg ok"><?= htmlspecialchars($notice) ?></div><?php endif; ?>
<?php if ($error): ?><div class="msg err"><?= htmlspecialchars($error) ?></div><?php endif; ?>

<form method="post" id="mainForm">
<?= csrfField() ?>
<input type="hidden" name="base_updated" value="<?= htmlspecialchars((string) ($cfg['updated'] ?? '')) ?>">
<input type="hidden" name="order" id="orderField" value="">
<table id="sceneTable">
<tr><th><?= $canOrder ? 'Orden' : '' ?></th><th>En antena</th><th>Escena</th><th>Segundos</th><th>Vista previa</th></tr>
<?php foreach ($ordered as $i => $key):
    $meta = $scenes[$key];
    $cur = $cfg['scenes'][$key] ?? [];
    $on = ($cur['enabled'] ?? true) !== false;
    $sec = $cur['seconds'] ?? $meta['default'];
    $still = esc_preview_still($slug, $key);
?>
<tr class="<?= $on ? '' : 'off' ?>" data-key="<?= htmlspecialchars($key) ?>" <?= $canOrder ? 'draggable="true"' : '' ?>>
  <td style="white-space:nowrap">
    <?php if ($canOrder): ?>
      <span class="grip" title="Arrastra para reordenar">⋮⋮</span><span class="pos"><?= $i + 1 ?></span>
      <span class="updown"><button type="button" onclick="moveRow(this,-1)" title="Subir">▲</button><button type="button" onclick="moveRow(this,1)" title="Bajar">▼</button></span>
    <?php endif; ?>
  </td>
  <td><input type="checkbox" name="on[<?= $key ?>]" <?= $on ? 'checked' : '' ?> onchange="this.closest('tr').classList.toggle('off',!this.checked)"></td>
  <td>
    <b><?= htmlspecialchars($meta['label']) ?></b>
    <?php if (!empty($meta['conditional'])): ?><div class="cond">condicional: solo sale si hay datos/actividad</div><?php endif; ?>
  </td>
  <td><input type="number" name="sec[<?= $key ?>]" value="<?= htmlspecialchars((string) $sec) ?>" min="2" max="30" step="0.5"></td>
  <td>
    <?php if ($still): ?>
      <button class="btn sm" type="button" onclick="togglePrev('prev-<?= $key ?>')">Ver</button>
      <?php if (!empty($product['plots'][$key])): ?>
        <a class="btn sm" style="text-decoration:none" title="Editor visual: mover, escalar, encender/apagar y añadir plots"
           href="placement.php?p=<?= rawurlencode($slug) ?>&scene=<?= rawurlencode($key) ?>">🎯 Plots</a>
      <?php endif; ?>
      <div class="prev" id="prev-<?= $key ?>" style="display:none">
        <img src="<?= $previewBase ?>/<?= rawurlencode($key) ?>.png?ts=<?= time() ?>"
             onerror="this.replaceWith('(aún sin preview — pídela y recarga en ~2 min)')">
        <button class="btn sm" formmethod="post" name="action" value="preview" formnovalidate
                onclick="this.form.scene.value='<?= $key ?>'">Regenerar preview</button>
      </div>
    <?php else: ?><span style="color:#5f7787">—</span><?php endif; ?>
  </td>
</tr>
<?php endforeach; ?>
</table>
<input type="hidden" name="scene" value="">
<?php if ($canOrder): ?><div class="hint">Arrastra las filas (o usa ▲▼) para cambiar el orden en que salen las escenas. Las condicionales solo entran si hay datos, pero conservan su sitio.</div><?php endif; ?>

<?php if ($slug === 'tiempo-conus'):
    $th = $cfg['thresholds'] ?? []; ?>
<div class="th-box">
  <b>Umbrales de las escenas severas en vivo</b> (si se dejan vacíos mandan los de código)<br><br>
  Rayos — mínimo de destellos GLM en CONUS:
  <input type="number" name="th[glmMinFlashes]" value="<?= htmlspecialchars((string) ($th['glmMinFlashes'] ?? 25)) ?>" min="1" max="100000"> ·
  Granizo — MESH mínimo (pulgadas):
  <input type="number" name="th[meshMinIn]" value="<?= htmlspecialchars((string) ($th['meshMinIn'] ?? 1.0)) ?>" min="0.4" max="4" step="0.1"> ·
  Granizo — cobertura mínima (bytes del PNG):
  <input type="number" name="th[meshMinBytes]" value="<?= htmlspecialchars((string) ($th['meshMinBytes'] ?? 40000)) ?>" min="0" max="10000000" step="1000">
</div>
<?php endif; ?>

<?php $camDef = $product['camera'] ?? null; $camCur = $cfg['camera'] ?? []; ?>
<?php if ($camDef): ?>
<div class="th-box">
  <b>Cámara</b>
  <?php if (($product['cameraMode'] ?? '') === 'fixed'): ?>
    — encuadre fijo del segmento (bbox en grados; vacío = el de código)<br><br>
    Oeste <input type="number" name="cam[west]" step="0.1" value="<?= htmlspecialchars((string) ($camCur['west'] ?? '')) ?>" placeholder="<?= $camDef['west'] ?>">
    Sur <input type="number" name="cam[south]" step="0.1" value="<?= htmlspecialchars((string) ($camCur['south'] ?? '')) ?>" placeholder="<?= $camDef['south'] ?>">
    Este <input type="number" name="cam[east]" step="0.1" value="<?= htmlspecialchars((string) ($camCur['east'] ?? '')) ?>" placeholder="<?= $camDef['east'] ?>">
    Norte <input type="number" name="cam[north]" step="0.1" value="<?= htmlspecialchars((string) ($camCur['north'] ?? '')) ?>" placeholder="<?= $camDef['north'] ?>">
    <br><br>
  <?php else: ?>
    — en el Trópico la posición va asociada a la data (encuadre al cono del NHC);
    aquí solo se ajusta el aire alrededor.<br><br>
  <?php endif; ?>
  Padding (px): arriba <input type="number" name="cam[padTop]" min="0" max="400" value="<?= htmlspecialchars((string) ($camCur['padTop'] ?? '')) ?>" placeholder="<?= $camDef['padTop'] ?>">
  abajo <input type="number" name="cam[padBottom]" min="0" max="400" value="<?= htmlspecialchars((string) ($camCur['padBottom'] ?? '')) ?>" placeholder="<?= $camDef['padBottom'] ?>">
  izq. <input type="number" name="cam[padLeft]" min="0" max="400" value="<?= htmlspecialchars((string) ($camCur['padLeft'] ?? '')) ?>" placeholder="<?= $camDef['padLeft'] ?>">
  dcha. <input type="number" name="cam[padRight]" min="0" max="400" value="<?= htmlspecialchars((string) ($camCur['padRight'] ?? '')) ?>" placeholder="<?= $camDef['padRight'] ?>">
  <?php if (!empty($product['plots'])): ?><div class="hint">Las posiciones fijadas de los plots son relativas a cada ciudad: sobreviven a un cambio de cámara. El fondo del editor visual se regenera solo al cambiarla.</div><?php endif; ?>
</div>
<?php endif; ?>

<?php if (isset($product['ui'])): $uiCur = $cfg['ui'] ?? []; ?>
<div class="th-box">
  <b>Tamaño de gráficos</b> (1 = tamaño canónico; 0.7–1.4)<br><br>
  Barra de tópico ×<input type="number" name="ui[topicBarScale]" min="0.7" max="1.4" step="0.05" value="<?= htmlspecialchars((string) ($uiCur['topicBarScale'] ?? '')) ?>" placeholder="1"> ·
  Chips y cajas de ciudad ×<input type="number" name="ui[chipScale]" min="0.7" max="1.4" step="0.05" value="<?= htmlspecialchars((string) ($uiCur['chipScale'] ?? '')) ?>" placeholder="1">
  <div class="hint">El anti-solape escala con los chips: al agrandarlos se recolocan solos.</div>
</div>
<?php endif; ?>

<div class="th-box">
  <b>Guardar</b><br><br>
  Nota (opcional, queda en el historial): <input type="text" name="note" size="48" placeholder="p. ej. «radar a 6 s y sequía fuera para el fin de semana»">
  <?php if ($conflictErr): ?>
    <br><br><label><input type="checkbox" name="force" style="transform:scale(1.2)"> <b>Sobrescribir</b> los cambios que guardó la otra persona</label>
  <?php endif; ?>
  <p style="margin-bottom:0">
    <button class="btn" type="submit" onclick="fillOrder()">Guardar y publicar</button>
    <button class="btn" type="submit" name="action" value="preview_all" style="background:#16324a" formnovalidate>Generar todas las previews</button>
  </p>
</div>
</form>

<div class="th-box hist">
  <b>Historial</b> <span class="hint" style="display:inline">(últimas <?= ESC_HISTORY_MAX ?> versiones; «Restaurar» la vuelve a poner en antena y guarda la actual como versión)</span><br><br>
  <?php if (!$history): ?>
    <span class="hint">Aún no hay versiones anteriores: aparecen a partir del próximo guardado.</span>
  <?php else: foreach ($history as $i => $h): ?>
    <div class="row">
      <span class="when"><?= htmlspecialchars(substr((string) ($h['ts'] ?? ''), 0, 16)) ?> UTC</span>
      <span class="by"><?= htmlspecialchars((string) ($h['by'] ?? '—')) ?></span>
      <span class="note"><?= htmlspecialchars((string) ($h['note'] ?: esc_summary($h['config'] ?? [], $product))) ?></span>
      <form method="post" style="margin:0" onsubmit="return confirm('¿Restaurar esta versión? La actual se guarda en el historial.')">
        <?= csrfField() ?>
        <input type="hidden" name="action" value="restore">
        <input type="hidden" name="idx" value="<?= $i ?>">
        <button class="btn sm" type="submit">Restaurar</button>
      </form>
    </div>
  <?php endforeach; endif; ?>
</div>

<script>
function togglePrev(id){const el=document.getElementById(id);el.style.display=el.style.display==='none'?'block':'none';}
const table = document.getElementById('sceneTable');
const rows = () => Array.from(table.querySelectorAll('tr[data-key]'));
function renumber(){ rows().forEach((r,i)=>{ const p=r.querySelector('.pos'); if(p) p.textContent=i+1; }); }
function fillOrder(){ document.getElementById('orderField').value = rows().map(r=>r.dataset.key).join(','); }
function moveRow(btn, dir){
  const tr = btn.closest('tr'); const sib = dir<0 ? tr.previousElementSibling : tr.nextElementSibling;
  if (!sib || !sib.dataset.key) return;
  dir<0 ? tr.parentNode.insertBefore(tr, sib) : tr.parentNode.insertBefore(sib, tr);
  renumber();
}
// Arrastrar y soltar filas (HTML5 DnD; el asa es toda la fila).
let dragRow = null;
table.addEventListener('dragstart', e => { const tr = e.target.closest('tr[data-key]'); if (!tr) return; dragRow = tr; tr.classList.add('dragging'); e.dataTransfer.effectAllowed='move'; });
table.addEventListener('dragover', e => { const tr = e.target.closest('tr[data-key]'); if (!tr || tr===dragRow) return; e.preventDefault(); rows().forEach(r=>r.classList.remove('over')); tr.classList.add('over'); });
table.addEventListener('dragleave', e => { const tr = e.target.closest('tr[data-key]'); if (tr) tr.classList.remove('over'); });
table.addEventListener('drop', e => { const tr = e.target.closest('tr[data-key]'); if (!tr || !dragRow || tr===dragRow) return; e.preventDefault();
  const list = rows(); const from = list.indexOf(dragRow), to = list.indexOf(tr);
  tr.parentNode.insertBefore(dragRow, from < to ? tr.nextSibling : tr); rows().forEach(r=>r.classList.remove('over')); renumber(); });
table.addEventListener('dragend', () => { if (dragRow) dragRow.classList.remove('dragging'); dragRow=null; rows().forEach(r=>r.classList.remove('over')); });
// Al enviar con Enter (sin pasar por el botón) también va el orden.
document.getElementById('mainForm').addEventListener('submit', fillOrder);
</script>
</body>
</html>
