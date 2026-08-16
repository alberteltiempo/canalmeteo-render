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
        'condiciones'   => 'Mockup-condiciones',
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
