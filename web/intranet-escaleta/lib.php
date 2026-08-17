<?php
/**
 * Escaleta ("granja") — editor web de las escaletas de los vídeos automáticos.
 *
 * Los JSON de escaleta viven en el CDN (data/escaleta/<slug>.json) y los LEEN
 * los proyectos Remotion de calamarsa en cada render, con fallback total a los
 * valores de código. Aquí se editan y se GUARDAN en un buzón local
 * (/opt/canalmeteo/escaleta/outbox) que un cron de root sube a Spaces
 * (escaleta_push.sh, cada minuto): el PHP no tiene credenciales S3 a propósito.
 */

const ESC_CDN = 'https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/escaleta';
const ESC_OUTBOX = '/opt/canalmeteo/escaleta/outbox';
const ESC_SECONDS_MIN = 2;
const ESC_SECONDS_MAX = 30;
const ESC_MIN_ENABLED = 3; // cortafuegos: mismo mínimo que aplica Remotion

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

function esc_config(string $slug): ?array {
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
 * Escenas con vista previa (Still Mockup-* con datos reales en calamarsa).
 * El trópico no tiene stills: su preview es "solo en directo" de momento.
 */
function esc_preview_still(string $slug, string $scene): ?string {
    if ($slug === 'tropico') return null;
    $tiempo = [
        // condiciones usa el Still Prev-* (datos reales + escaleta aplicada:
        // cámara, escala y posiciones del editor), no el Mockup estático.
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
    ];
    $conus = [
        'lightning' => 'Mockup-rayos',
        'watches'   => 'Mockup-vigilancias',
        'hail'      => 'Mockup-granizo',
    ];
    $map = $slug === 'tiempo-conus' ? $tiempo + $conus : $tiempo;
    return $map[$scene] ?? null;
}

/**
 * Valida un mapa de posiciones fijadas {ciudad: [x,y]} (px del lienzo
 * 1920×1080) contra la lista de ciudades del catálogo. Devuelve solo las
 * entradas válidas (lo demás se descarta en silencio, como hace Remotion).
 */
function esc_clean_placement(array $raw, array $validIds): array {
    $out = [];
    foreach ($raw as $id => $xy) {
        if (!in_array($id, $validIds, true)) continue;
        if (!is_array($xy) || count($xy) !== 2 || !is_numeric($xy[0]) || !is_numeric($xy[1])) continue;
        $x = (float) $xy[0]; $y = (float) $xy[1];
        if ($x < 0 || $x > 1920 || $y < 0 || $y > 1080) continue;
        $out[$id] = [round($x), round($y)];
    }
    return $out;
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
