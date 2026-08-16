<?php
/** Escaleta — lista de productos (vídeos automáticos) editables. */
require_once dirname(__DIR__) . '/includes/auth.php';
requireSection('escaleta');
require_once __DIR__ . '/lib.php';

$catalog = esc_catalog();
$user = getCurrentUserName();
?>
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>Escaletas · Intranet Canal Meteo</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;600;700&display=swap" rel="stylesheet">
<style>
  body{font-family:Outfit,system-ui,sans-serif;background:#0d1a26;color:#eef4f8;margin:0;padding:32px}
  a{color:#7cc4ff;text-decoration:none}
  h1{font-size:26px;margin:0 0 6px}
  .sub{color:#9db4c4;margin-bottom:26px;font-size:15px}
  table{border-collapse:collapse;width:100%;max-width:860px}
  th,td{padding:10px 14px;text-align:left;border-bottom:1px solid rgba(255,255,255,.12);font-size:15px}
  th{color:#9db4c4;font-weight:600;font-size:13px;text-transform:uppercase;letter-spacing:1px}
  tr:hover td{background:rgba(255,255,255,.04)}
  .pill{display:inline-block;background:#16324a;border-radius:999px;padding:2px 10px;font-size:13px}
  .warn{color:#f4a020}
</style>
</head>
<body>
<h1>Escaletas de los vídeos automáticos</h1>
<div class="sub">
  Sesión: <?= htmlspecialchars($user) ?> · <a href="../dashboard.php">← Volver al dashboard</a><br>
  Los cambios se publican al CDN en ≤1 min y aplican en el <b>siguiente render</b> de cada producto.
  Si el fichero falla, el render usa sus valores de código (la antena nunca depende de esta web).
</div>
<?php if (!$catalog): ?>
  <p class="warn">No se pudo leer el catálogo del CDN (data/escaleta/catalog.json). Reintenta en unos segundos.</p>
<?php else: ?>
<table>
<tr><th>Producto</th><th>Escenas activas</th><th>Última edición</th><th></th></tr>
<?php foreach ($catalog['products'] as $slug => $p):
    $cfg = esc_config($slug);
    $on = 0; $total = count($p['scenes']);
    if ($cfg && isset($cfg['scenes'])) {
        foreach ($p['scenes'] as $k => $_) {
            if (($cfg['scenes'][$k]['enabled'] ?? true) !== false) $on++;
        }
    } else { $on = $total; }
    $upd = $cfg['updated'] ?? null;
    $by = $cfg['updatedBy'] ?? '—';
?>
<tr>
  <td><b><?= htmlspecialchars($p['nombre']) ?></b> <span class="pill"><?= htmlspecialchars($slug) ?></span></td>
  <td><?= $on ?> / <?= $total ?></td>
  <td><?= $upd ? htmlspecialchars(substr($upd, 0, 16)) . ' UTC · ' . htmlspecialchars($by) : 'defaults' ?></td>
  <td><a href="edit.php?p=<?= rawurlencode($slug) ?>">Editar →</a></td>
</tr>
<?php endforeach; ?>
</table>
<?php endif; ?>
</body>
</html>
