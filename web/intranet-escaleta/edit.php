<?php
/** Escaleta — edición de un producto: escenas on/off, duraciones, umbrales y previews. */
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
    if (($_POST['action'] ?? '') === 'preview') {
        $scene = $_POST['scene'] ?? '';
        if (esc_preview_still($slug, $scene)) {
            $ok = esc_spool("preview_{$slug}_{$scene}.json", [
                'slug' => $slug, 'scene' => $scene, 'ts' => time(), 'by' => $user,
            ]);
            $notice = $ok
                ? "Vista previa de «{$scene}» solicitada: calamarsa la renderiza en 1–3 min (recarga la página)."
                : 'No se pudo escribir en el buzón (outbox no accesible)';
        } else {
            $error = 'Esa escena no tiene vista previa disponible';
        }
    } else {
        [$cfg, $err] = esc_build_config($slug, $product, $_POST, $user);
        if ($err) {
            $error = $err;
        } elseif (esc_spool("{$slug}.json", $cfg)) {
            $notice = 'Guardado. Se publica al CDN en ≤1 min y aplica en el siguiente render.';
        } else {
            $error = 'No se pudo escribir en el buzón (outbox no accesible)';
        }
    }
}

$cfg = esc_config($slug);
$scenes = $product['scenes'];
$previewBase = ESC_CDN . '/previews/' . rawurlencode($slug);
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
  input[type=number]{width:70px;background:#12283a;color:#fff;border:1px solid rgba(255,255,255,.25);border-radius:8px;padding:6px 8px;font-family:'JetBrains Mono',monospace}
  input[type=checkbox]{transform:scale(1.35)}
  .cond{color:#f4a020;font-size:12px}
  .btn{background:#1f5f9e;color:#fff;border:0;border-radius:10px;padding:10px 22px;font-family:Outfit;font-weight:700;font-size:16px;cursor:pointer}
  .btn.sm{padding:5px 12px;font-size:13px;background:#16324a}
  .btn:hover{filter:brightness(1.15)}
  .th-box{background:#10222f;border:1px solid rgba(255,255,255,.14);border-radius:12px;padding:14px 18px;margin:18px 0;max-width:940px}
  .prev{margin-top:6px}
  .prev img{max-width:420px;border-radius:8px;border:1px solid rgba(255,255,255,.2);display:block;margin-top:6px}
</style>
<script>
  function togglePrev(id){const el=document.getElementById(id);el.style.display=el.style.display==='none'?'block':'none';}
</script>
</head>
<body>
<h1><?= htmlspecialchars($product['nombre']) ?> <span style="color:#9db4c4">· escaleta</span></h1>
<div class="sub"><a href="index.php">← Todos los productos</a> · Los cambios aplican en el siguiente render (cron horario<?= $slug === 'tropico' ? ' / por boletín del NHC' : '' ?>).</div>

<?php if ($notice): ?><div class="msg ok"><?= htmlspecialchars($notice) ?></div><?php endif; ?>
<?php if ($error): ?><div class="msg err"><?= htmlspecialchars($error) ?></div><?php endif; ?>

<form method="post">
<table>
<tr><th>En antena</th><th>Escena</th><th>Segundos</th><th>Vista previa</th></tr>
<?php foreach ($scenes as $key => $meta):
    $cur = $cfg['scenes'][$key] ?? [];
    $on = ($cur['enabled'] ?? true) !== false;
    $sec = $cur['seconds'] ?? $meta['default'];
    $still = esc_preview_still($slug, $key);
?>
<tr class="<?= $on ? '' : 'off' ?>">
  <td><input type="checkbox" name="on[<?= $key ?>]" <?= $on ? 'checked' : '' ?>></td>
  <td>
    <b><?= htmlspecialchars($meta['label']) ?></b>
    <?php if (!empty($meta['conditional'])): ?><div class="cond">condicional: solo sale si hay datos/actividad</div><?php endif; ?>
  </td>
  <td><input type="number" name="sec[<?= $key ?>]" value="<?= htmlspecialchars((string) $sec) ?>" min="2" max="30" step="0.5"></td>
  <td>
    <?php if ($still): ?>
      <button class="btn sm" type="button" onclick="togglePrev('prev-<?= $key ?>')">Ver</button>
      <div class="prev" id="prev-<?= $key ?>" style="display:none">
        <img src="<?= $previewBase ?>/<?= rawurlencode($key) ?>.png?ts=<?= time() ?>"
             onerror="this.replaceWith('(aún sin preview — pídela y recarga en ~2 min)')">
        <button class="btn sm" formmethod="post" name="action" value="preview"
                onclick="this.form.scene.value='<?= $key ?>'">Regenerar preview</button>
      </div>
    <?php else: ?><span style="color:#5f7787">—</span><?php endif; ?>
  </td>
</tr>
<?php endforeach; ?>
</table>
<input type="hidden" name="scene" value="">

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

<p><button class="btn" type="submit">Guardar y publicar</button></p>
</form>
</body>
</html>
