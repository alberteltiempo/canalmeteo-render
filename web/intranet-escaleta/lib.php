<?php
/**
 * Escaleta ("granja") — editor web de las escaletas de los vídeos automáticos.
 *
 * Los JSON de escaleta viven en el CDN (data/escaleta/<slug>.json) y los LEEN
 * los proyectos Remotion de calamarsa en cada render, con fallback total a los
 * valores de código. Aquí se editan y se GUARDAN en un buzón local
 * (/opt/canalmeteo/escaleta/outbox) que un cron de root sube a Spaces
 * (escaleta_push.sh, cada minuto): el PHP no tiene credenciales S3 a propósito.
 *
 * v2 (2026-09-07): historial de versiones con restaurar, detección de guardado
 * concurrente, orden de escenas, ciudades on/off + añadidas por escena y
 * posiciones fijadas RELATIVAS al punto ({dx,dy}).
 */

const ESC_CDN = 'https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/escaleta';
const ESC_OUTBOX = '/opt/canalmeteo/escaleta/outbox';
const ESC_SECONDS_MIN = 2;
const ESC_SECONDS_MAX = 30;
const ESC_MIN_ENABLED = 3; // cortafuegos: mismo mínimo que aplica Remotion
const ESC_HISTORY_MAX = 20; // versiones guardadas en el propio JSON

function esc_http_json(string $url): ?array {
    $ctx = stream_context_create(['http' => ['timeout' => 8]]);
    $raw = @file_get_contents($url . '?ts=' . time(), false, $ctx);
    if ($raw === false) return null;
    $d = json_decode($raw, true);
    return is_array($d) ? $d : null;
}

function esc_catalog(): ?array {
    return esc_http_json(ESC_CDN . '/catalog.json');
}

/**
 * Config vigente del producto. Si hay un guardado PENDIENTE en el buzón (aún
 * no publicado por el cron, ≤1 min) manda ese: así dos guardados seguidos del
 * mismo editor no se pisan ni saltan como conflicto.
 */
function esc_config(string $slug): ?array {
    $pending = ESC_OUTBOX . '/' . $slug . '.json';
    if (is_readable($pending)) {
        $d = json_decode((string) @file_get_contents($pending), true);
        if (is_array($d)) return $d;
    }
    return esc_http_json(ESC_CDN . '/' . rawurlencode($slug) . '.json');
}

/** Escritura atómica en el buzón (tmp + rename). */
function esc_spool(string $name, array $payload): bool {
    if (!is_dir(ESC_OUTBOX) || !is_writable(ESC_OUTBOX)) return false;
    $tmp = ESC_OUTBOX . '/.' . $name . '.tmp';
    $ok = @file_put_contents(
        $tmp,
        json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT) . "\n"
    );
    return $ok !== false && @rename($tmp, ESC_OUTBOX . '/' . $name);
}

/**
 * Guarda la config de un producto con historial: la versión ANTERIOR (sin su
 * propio historial) se apila en `history` (máx. ESC_HISTORY_MAX) con fecha,
 * autor y nota. Devuelve false si el buzón no es accesible.
 */
function esc_save_config(string $slug, array $cfg, ?array $prev, string $user, string $note): bool {
    $history = [];
    if ($prev) {
        $history = is_array($prev['history'] ?? null) ? $prev['history'] : [];
        $snap = $prev;
        unset($snap['history']);
        array_unshift($history, [
            'ts' => $snap['updated'] ?? gmdate('c'),
            'by' => $snap['updatedBy'] ?? '—',
            'note' => $snap['note'] ?? '',
            'config' => $snap,
        ]);
        $history = array_slice($history, 0, ESC_HISTORY_MAX);
    }
    $cfg['version'] = 1;
    $cfg['updated'] = gmdate('c');
    $cfg['updatedBy'] = $user;
    $cfg['note'] = $note;
    if ($history) $cfg['history'] = $history;
    return esc_spool("{$slug}.json", $cfg);
}

/**
 * Conflicto de edición: el formulario lleva el `updated` de la config que
 * cargó; si la vigente tiene otro, alguien guardó entre medias. Devuelve el
 * mensaje o null si no hay conflicto.
 */
function esc_conflict(?array $current, string $baseUpdated, bool $force): ?string {
    if ($force) return null;
    $cur = (string) ($current['updated'] ?? '');
    if ($cur === $baseUpdated) return null;
    $by = $current['updatedBy'] ?? 'otra persona';
    $when = $cur ? substr($cur, 11, 5) . ' UTC' : '—';
    return "⚠ {$by} guardó esta escaleta a las {$when} mientras la editabas. Recarga para ver sus cambios, "
         . "o marca «Sobrescribir» y vuelve a guardar para imponer los tuyos.";
}

/**
 * Escenas con vista previa (Still en calamarsa; desde la fase 7 TODAS con datos
 * reales: los Mockup-* reciben los feeds por calculateMetadata y los Prev-*
 * renderizan el Segment real con el plan reducido a esa escena). Mantener en
 * sincronía con el mapa del worker (scripts/escaleta_preview_worker.py).
 */
function esc_preview_still(string $slug, string $scene): ?string {
    if ($slug === 'tropico') {
        $trop = ['open', 'satGlobal', 'countIntro', 'basinIntro', 'stormSat', 'stormTrack',
                 'investStatus', 'stormRain', 'basinStatus', 'nameList', 'outro'];
        return in_array($scene, $trop, true) ? 'Prev-' . $scene : null;
    }
    $tiempo = [
        'condiciones'   => 'Prev-condiciones',
        'reports'       => 'Mockup-reportes',
        'uv'            => 'Mockup-uv',
        'aqi'           => 'Mockup-aqi',
        'aeropuertos'   => 'Mockup-aeropuertos',
        'spc'           => 'Mockup-spc',
        'drought'       => 'Mockup-sequia',
        'tmax_today'    => 'Mockup-tmax-hoy',
        'tvar'          => 'Mockup-tvar-manana',
        'tmax_tomorrow' => 'Mockup-tmax-manana',
        'quake'         => 'Mockup-quake',
        'quake_intro'   => 'Mockup-quake-intro',
        // Escenas sin still propio: preview del Segment real (plan filtrado).
        'open'          => 'Prev-open',
        'geocolor'      => 'Prev-geocolor',
        'radar'         => 'Prev-radar',
        'alerts'        => 'Prev-alerts',
        // ids de composición sin "_" (Remotion no lo admite): van con guion.
        'precip_fcst'   => 'Prev-precip-fcst',
        'precip_accum'  => 'Prev-precip-accum',
        'outro'         => 'Prev-outro',
    ];
    $conus = [
        'lightning' => 'Mockup-rayos',
        'watches'   => 'Mockup-vigilancias',
        'hail'      => 'Mockup-granizo',
    ];
    $map = $slug === 'tiempo-conus' ? $tiempo + $conus : $tiempo;
    return $map[$scene] ?? null;
}

/** Encola una preview (full o fondo limpio `base`) para calamarsa. */
function esc_request_preview(string $slug, string $scene, string $user, bool $base = false, int $delay = 0): bool {
    $name = "preview_{$slug}_{$scene}" . ($base ? '_base' : '') . '.json';
    return esc_spool($name, ['slug' => $slug, 'scene' => $scene, 'ts' => time() + $delay, 'by' => $user, 'base' => $base]);
}

/** Escena → juego de ciudades (las 3 de temperatura comparten "tmax"). */
function esc_city_set(string $scene): string {
    return in_array($scene, ['tmax_today', 'tmax_tomorrow', 'tvar'], true) ? 'tmax' : $scene;
}

/**
 * Valida un mapa de posiciones fijadas {id: {dx,dy}} (relativas al punto, px
 * del lienzo 1920×1080) o {id: [x,y]} (absolutas, formato antiguo) contra la
 * lista de ids válidos (catálogo + añadidas). Lo demás se descarta en silencio,
 * como hace Remotion.
 */
function esc_clean_placement(array $raw, array $validIds): array {
    $out = [];
    foreach ($raw as $id => $v) {
        if (!in_array($id, $validIds, true)) continue;
        if (is_array($v) && isset($v['dx'], $v['dy']) && is_numeric($v['dx']) && is_numeric($v['dy'])) {
            $dx = (float) $v['dx']; $dy = (float) $v['dy'];
            if (abs($dx) > 1920 || abs($dy) > 1080) continue;
            $out[$id] = ['dx' => round($dx), 'dy' => round($dy)];
        } elseif (is_array($v) && count($v) === 2 && isset($v[0], $v[1]) && is_numeric($v[0]) && is_numeric($v[1])) {
            $x = (float) $v[0]; $y = (float) $v[1];
            if ($x < 0 || $x > 1920 || $y < 0 || $y > 1080) continue;
            $out[$id] = [round($x), round($y)];
        }
    }
    return $out;
}

/**
 * Valida el juego de ciudades de una escena: {off: [ids del catálogo],
 * extra: [...]} donde cada extra es (a) {id} de una ciudad del catálogo
 * MAESTRO (se copian sus datos) o (b) una ciudad NUEVA {custom:true, id,
 * label, city, state, lon, lat} que no está en ningún catálogo: los pipelines
 * de nimbus (escaleta_cities.py) producen su dato por lat/lon o city/state.
 * Devuelve [] si no hay nada que anular/añadir.
 */
function esc_clean_cities(array $raw, array $catalogIds, array $master): array {
    $byId = [];
    foreach ($master as $m) $byId[$m['id']] = $m;
    $off = [];
    foreach ((array) ($raw['off'] ?? []) as $id) {
        if (is_string($id) && in_array($id, $catalogIds, true)) $off[] = $id;
    }
    $extra = [];
    foreach ((array) ($raw['extra'] ?? []) as $e) {
        $id = is_array($e) ? ($e['id'] ?? null) : (is_string($e) ? $e : null);
        if (!is_string($id) || $id === '' || strlen($id) > 40 || in_array($id, $catalogIds, true)) continue;
        if (is_array($e) && !empty($e['custom'])) {
            $label = trim((string) ($e['label'] ?? ''));
            $city = trim((string) ($e['city'] ?? $label));
            $state = strtoupper(trim((string) ($e['state'] ?? '')));
            $lon = $e['lon'] ?? null; $lat = $e['lat'] ?? null;
            if ($label === '' || mb_strlen($label) > 40 || $city === '' || mb_strlen($city) > 40) continue;
            if (!preg_match('/^[A-Z]{2}$/', $state)) continue;
            if (!is_numeric($lon) || !is_numeric($lat) || abs((float) $lon) > 180 || abs((float) $lat) > 90) continue;
            $extra[$id] = ['id' => $id, 'label' => $label, 'name' => $label, 'key' => (string) ($e['key'] ?? $id),
                           'lon' => round((float) $lon, 4), 'lat' => round((float) $lat, 4),
                           'custom' => true, 'city' => $city, 'state' => $state];
            continue;
        }
        if (!isset($byId[$id])) continue;
        $m = $byId[$id];
        $extra[$id] = ['id' => $id, 'label' => $m['label'], 'name' => $m['name'] ?? $m['label'],
                       'key' => $m['key'] ?? $id, 'lon' => (float) $m['lon'], 'lat' => (float) $m['lat']];
    }
    $out = [];
    if ($off) $out['off'] = array_values(array_unique($off));
    if ($extra) $out['extra'] = array_values($extra);
    return $out;
}

/** Ids visibles de una escena: catálogo − apagadas + añadidas. */
function esc_scene_ids(array $plots, array $cities): array {
    $off = $cities['off'] ?? [];
    $ids = [];
    foreach ($plots as $p) if (!in_array($p['id'], $off, true)) $ids[] = $p['id'];
    foreach ($cities['extra'] ?? [] as $e) $ids[] = $e['id'];
    return $ids;
}

/**
 * Valida y normaliza el POST del formulario contra el catálogo.
 * Devuelve [configArray, null] o [null, "mensaje de error"].
 */
function esc_build_config(string $slug, array $catalogProduct, array $post, string $user): array {
    $scenes = [];
    $enabledCount = 0;
    foreach ($catalogProduct['scenes'] as $key => $meta) {
        $enabled = isset($post['on'][$key]);
        $sec = $post['sec'][$key] ?? $meta['default'];
        if (!is_numeric($sec)) return [null, "Duración no numérica en «{$meta['label']}»"];
        $sec = (float) $sec;
        if ($sec < ESC_SECONDS_MIN || $sec > ESC_SECONDS_MAX) {
            return [null, sprintf('Duración fuera de rango (%g–%g s) en «%s»', ESC_SECONDS_MIN, ESC_SECONDS_MAX, $meta['label'])];
        }
        if ($enabled) $enabledCount++;
        $scenes[$key] = ['enabled' => $enabled, 'seconds' => $sec];
    }
    if ($enabledCount < ESC_MIN_ENABLED) {
        return [null, 'Debe haber al menos ' . ESC_MIN_ENABLED . ' escenas encendidas (cortafuegos de antena)'];
    }
    $cfg = [
        'version' => 1,
        'updated' => gmdate('c'),
        'updatedBy' => $user,
        'scenes' => $scenes,
    ];
    // Orden de escenas (solo si difiere del orden de código = el del catálogo).
    // El trópico no lo admite (su plan lo dicta la data del NHC).
    if ($slug !== 'tropico' && isset($post['order']) && is_string($post['order'])) {
        $order = array_values(array_filter(explode(',', $post['order']), 'strlen'));
        $valid = array_keys($catalogProduct['scenes']);
        $order = array_values(array_unique(array_filter($order, fn($k) => in_array($k, $valid, true))));
        if ($order && $order !== array_values(array_intersect($valid, $order))) {
            $cfg['order'] = $order;
        }
    }
    // Cámara: bbox (solo productos de cámara fija) + padding. Vacío → sin override.
    if (isset($catalogProduct['camera'])) {
        $cam = [];
        if (($catalogProduct['cameraMode'] ?? '') === 'fixed') {
            $bb = [];
            foreach (['west' => [-180, 180], 'south' => [-85, 85], 'east' => [-180, 180], 'north' => [-85, 85]] as $k => $r) {
                $v = $post['cam'][$k] ?? '';
                if ($v === '' || !is_numeric($v)) { $bb = null; break; }
                $v = (float) $v;
                if ($v < $r[0] || $v > $r[1]) return [null, "Cámara: {$k} fuera de rango"];
                $bb[$k] = $v;
            }
            if ($bb !== null) {
                if ($bb['west'] >= $bb['east'] || $bb['south'] >= $bb['north']) {
                    return [null, 'Cámara: oeste<este y sur<norte, revisa el bbox'];
                }
                $cam = $bb;
            }
        }
        foreach (['padTop', 'padBottom', 'padLeft', 'padRight'] as $k) {
            $v = $post['cam'][$k] ?? '';
            if ($v !== '' && is_numeric($v)) {
                $v = (float) $v;
                if ($v < 0 || $v > 400) return [null, "Cámara: {$k} fuera de rango (0–400 px)"];
                $cam[$k] = $v;
            }
        }
        if ($cam) $cfg['camera'] = $cam;
    }
    // Escala de gráficos (0.7–1.4): barra de tópico y chips/cajas.
    if (isset($catalogProduct['ui'])) {
        $ui = [];
        foreach (['topicBarScale', 'chipScale'] as $k) {
            $v = $post['ui'][$k] ?? '';
            if ($v !== '' && is_numeric($v)) {
                $v = (float) $v;
                if ($v < 0.7 || $v > 1.4) return [null, "Escala {$k} fuera de rango (0.7–1.4)"];
                $ui[$k] = $v;
            }
        }
        if ($ui) $cfg['ui'] = $ui;
    }
    if ($slug === 'tiempo-conus') {
        $th = [];
        foreach (['glmMinFlashes' => [1, 100000], 'meshMinIn' => [0.4, 4], 'meshMinBytes' => [0, 10000000]] as $k => $range) {
            $v = $post['th'][$k] ?? null;
            if ($v !== null && $v !== '' && is_numeric($v)) {
                $v = (float) $v;
                if ($v >= $range[0] && $v <= $range[1]) $th[$k] = $v;
            }
        }
        if ($th) $cfg['thresholds'] = $th;
    }
    return [$cfg, null];
}

/** Resumen humano de una config (para el historial). */
function esc_summary(array $cfg, array $catalogProduct): string {
    $on = 0; $total = count($catalogProduct['scenes']);
    foreach ($catalogProduct['scenes'] as $k => $_) {
        if (($cfg['scenes'][$k]['enabled'] ?? true) !== false) $on++;
    }
    $bits = ["{$on}/{$total} escenas"];
    if (!empty($cfg['order'])) $bits[] = 'orden propio';
    if (!empty($cfg['camera'])) $bits[] = 'cámara';
    if (!empty($cfg['ui'])) $bits[] = 'escala';
    $pins = 0;
    foreach ($cfg['placement'] ?? [] as $sc) $pins += count($sc);
    if ($pins) $bits[] = "{$pins} plots fijados";
    $cit = 0;
    foreach ($cfg['cities'] ?? [] as $c) $cit += count($c['off'] ?? []) + count($c['extra'] ?? []);
    if ($cit) $bits[] = "{$cit} cambios de ciudades";
    return implode(' · ', $bits);
}
