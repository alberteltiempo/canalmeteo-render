#!/usr/bin/php
<?php
/**
 * Canal Meteo TV — Beach / Rip Current Sync Script v2.0
 * Descarga forecasts de playa del NWS, los enriquece y los sube a DO Spaces
 *
 * Cambios v2.0 (25/05/2026):
 *  - Fix crítico: campo es `rip`, no `risk` — antes TODO salía como Low
 *  - Captura los 8 campos adicionales del NWS: surf, wtemp, maxtemp, weather,
 *    winds, tstorm, wspout, srfprod, heatindex, beachName, period, etc.
 *  - Parser de wtemp (string → numérico en °F): "in the mid 80s" → 85
 *  - Parser de maxtemp idéntico
 *  - Opción de day2 (--day2) para generar el segundo archivo
 *
 * Uso:
 *   php sync-beach.php           → genera rip-currents.geojson (day1)
 *   php sync-beach.php --day2    → genera rip-currents-day2.geojson
 *   php sync-beach.php --both    → genera ambos
 *
 * Cron sugerido (cada 4h, NWS actualiza 2x al día):
 *   0 0,4,8,12,16,20  *  *  *   /usr/bin/php /opt/canalmeteo/scripts/sync-beach.php --both >> /var/log/canalmeteo/sync-beach.log 2>&1
 */

// =============================================
// CONFIGURACIÓN
// =============================================
$config = [
    // DO Spaces (leer del .env en producción — aquí dejados como antes)
    'spaces_key'      => trim(shell_exec("grep '^SPACES_ACCESS_KEY=' /opt/canalmeteo/.env | cut -d= -f2") ?: ''),
    'spaces_secret'   => trim(shell_exec("grep '^SPACES_SECRET_KEY=' /opt/canalmeteo/.env | cut -d= -f2") ?: ''),
    'spaces_bucket'   => 'canalmeteo-public',
    'spaces_region'   => 'sfo3',
    'spaces_endpoint' => 'sfo3.digitaloceanspaces.com',

    // Paths CDN destino
    'destination_day1' => 'data/beach/rip-currents.geojson',
    'destination_day2' => 'data/beach/rip-currents-day2.geojson',

    // 32 oficinas NWS con pronóstico de playa
    'nws_offices' => [
        'apx', 'akq', 'buf', 'box', 'bro', 'car', 'chs', 'cle', 'crp',
        'dlh', 'dtx', 'grb', 'grr', 'gum', 'gyx', 'hfo', 'ilm', 'iwx',
        'jax', 'lot', 'lox', 'mfl', 'mhx', 'mlb', 'mkx', 'mob', 'mqt',
        'okx', 'phi', 'sgx', 'tae', 'tbw'
    ],
];

// =============================================
// FUNCIONES AUXILIARES
// =============================================

function log_msg($msg) {
    echo '[' . date('Y-m-d H:i:s') . "] $msg\n";
}

function download_json($url, $timeout = 30) {
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, $timeout);
    curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, true);
    curl_setopt($ch, CURLOPT_USERAGENT, 'CanalMeteoTV/2.0 (contact: info@canalmeteo.tv)');

    $data = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    if ($httpCode !== 200 || $data === false) return null;

    $json = json_decode($data, true);
    if (json_last_error() !== JSON_ERROR_NONE) return null;

    return $json;
}

/**
 * Parsea una expresión de temperatura del NWS a un valor numérico en °F.
 * Maneja todos los formatos vistos en el feed real:
 *   "52"                  → 52
 *   "85"                  → 85
 *   "75 to 80"            → 78
 *   "around 85"           → 85
 *   "near 85"             → 85
 *   "about 85"            → 85
 *   "in the mid 80s"      → 85
 *   "in the low 80s"      → 82
 *   "in the lower 80s"    → 82
 *   "in the upper 80s"    → 88
 *   "in the high 80s"     → 88
 *   "in the 80s"          → 85
 *   "Up to 103."          → 103
 *
 * @return int|null Temperatura en °F, o null si no se puede parsear
 */
function parse_temp($text) {
    if (empty($text) || !is_string($text)) return null;

    $t = strtolower(trim($text));
    $t = rtrim($t, '.');

    // 1. Número limpio
    if (preg_match('/^(\d{2,3})$/', $t, $m)) {
        return (int)$m[1];
    }

    // 2. Rango "75 to 80" o "75-80"
    if (preg_match('/(\d{2,3})\s*(?:to|-|–)\s*(\d{2,3})/', $t, $m)) {
        return (int)round(((int)$m[1] + (int)$m[2]) / 2);
    }

    // 3. "around X" / "near X" / "about X" / "up to X"
    if (preg_match('/(?:around|near|about|up to|approximately)\s+(\d{2,3})/', $t, $m)) {
        return (int)$m[1];
    }

    // 4. "in the mid 80s" / "in the low 80s" / "in the upper 80s"
    if (preg_match('/(\d{2,3})s\b/', $t, $m)) {
        $base = (int)$m[1];
        if (strpos($t, 'lower') !== false || strpos($t, 'low ') !== false) return $base + 2;
        if (strpos($t, 'middle') !== false || strpos($t, 'mid')   !== false) return $base + 5;
        if (strpos($t, 'upper')  !== false || strpos($t, 'high')  !== false) return $base + 8;
        return $base + 5; // default: medio de la década
    }

    // 5. Un número solo entre 30 y 110 (rangos plausibles de °F en agua/aire)
    if (preg_match('/(\d{2,3})/', $t, $m)) {
        $val = (int)$m[1];
        if ($val >= 30 && $val <= 110) return $val;
    }

    return null;
}

/**
 * Normaliza el nivel de riesgo a 'low' | 'moderate' | 'high'.
 * El campo NWS es `rip` (Rip Current Risk en costas, Swim Risk en Grandes Lagos).
 */
function normalize_risk($rip) {
    if (empty($rip)) return ['low', 1];
    $r = strtolower(trim($rip));
    if (strpos($r, 'high') !== false) return ['high', 3];
    if (strpos($r, 'mod')  !== false) return ['moderate', 2];
    return ['low', 1];
}

/**
 * Sube un archivo JSON a DO Spaces usando AWS SDK / cURL con firma S3v4.
 * Para simplicidad y dado el patrón de Canal Meteo, usamos `aws s3 cp` via shell.
 */
function upload_to_spaces($config, $data, $path) {
    log_msg("Subiendo a Spaces: $path");

    if (is_array($data)) {
        $data = json_encode($data, JSON_UNESCAPED_UNICODE);
    }

    // Guardar a archivo temporal
    $tmpFile = tempnam(sys_get_temp_dir(), 'beach_');
    file_put_contents($tmpFile, $data);

    // Usar aws CLI con el perfil do-tor1 (estándar Canal Meteo)
    $bucket = $config['spaces_bucket'];
    $endpoint = "https://{$config['spaces_endpoint']}";
    $s3url = "s3://{$bucket}/{$path}";

    $cmd = sprintf(
        'aws s3 cp %s %s --profile do-tor1 --acl public-read --content-type application/json --endpoint-url %s 2>&1',
        escapeshellarg($tmpFile),
        escapeshellarg($s3url),
        escapeshellarg($endpoint)
    );

    exec($cmd, $output, $exitCode);
    unlink($tmpFile);

    if ($exitCode !== 0) {
        throw new Exception("Upload falló: " . implode("\n", $output));
    }

    $publicUrl = "https://{$bucket}.{$config['spaces_endpoint']}/{$path}";
    log_msg("✅ Subido: $publicUrl");
    return true;
}

// =============================================
// SINCRONIZACIÓN DE UN DÍA
// =============================================
function sync_day($config, $day) {
    log_msg("--- Sincronizando day{$day} ---");

    $allFeatures  = [];
    $successCount = 0;
    $errorCount   = 0;
    $stats = ['low' => 0, 'moderate' => 0, 'high' => 0, 'with_wtemp' => 0];

    foreach ($config['nws_offices'] as $office) {
        $officeUpper = strtoupper($office);
        $url = "https://www.weather.gov/source/{$office}/beachforecast/{$officeUpper}_GIS_day{$day}.json";

        log_msg("→ {$officeUpper} day{$day}");

        $data = download_json($url);

        if (!$data || !isset($data['features']) || !is_array($data['features'])) {
            $errorCount++;
            log_msg("  ✗ No disponible o JSON inválido");
            usleep(150000);
            continue;
        }

        $featCount = 0;
        foreach ($data['features'] as $feature) {
            if (!isset($feature['properties'])) $feature['properties'] = [];
            $p = $feature['properties'];

            // Normalizar nivel de riesgo desde el campo `rip`
            [$riskLevel, $riskNum] = normalize_risk($p['rip'] ?? '');

            // Parsear temperaturas
            $wtempF   = parse_temp($p['wtemp']   ?? null);
            $maxtempF = parse_temp($p['maxtemp'] ?? null);
            if ($wtempF !== null) $stats['with_wtemp']++;

            // Reconstruir propiedades con todos los campos NWS + nuestros añadidos
            $feature['properties'] = [
                // Identificación
                'id'         => $p['id']         ?? null,
                'site_id'    => $p['siteId']     ?? $officeUpper,
                'site_name'  => $p['siteName']   ?? null,
                'beach_name' => $p['beachName']  ?? null,
                'nws_office' => $officeUpper,

                // Tiempo
                'product_date' => $p['productDate'] ?? null,
                'product_time' => $p['productTime'] ?? null,
                'period'       => $p['period']      ?? null,
                'day'          => (int)$day,

                // Riesgo (campo original + normalizado)
                'rip'        => $p['rip'] ?? null,
                'risk_level' => $riskLevel,
                'risk_num'   => $riskNum,

                // Datos meteorológicos del NWS
                'surf'       => $p['surf']      ?? null,
                'wtemp'      => $p['wtemp']     ?? null,
                'wtemp_f'    => $wtempF,
                'maxtemp'    => $p['maxtemp']   ?? null,
                'maxtemp_f'  => $maxtempF,
                'heatindex'  => $p['heatindex'] ?? null,
                'weather'    => $p['weather']   ?? null,
                'winds'      => $p['winds']     ?? null,
                'tstorm'     => $p['tstorm']    ?? null,
                'wspout'     => $p['wspout']    ?? null,
                'uvindex'    => $p['uvindex']   ?? null,

                // Enlace al Surf Zone Forecast oficial
                'srfprod' => $p['srfprod'] ?? null,
            ];

            $stats[$riskLevel]++;
            $allFeatures[] = $feature;
            $featCount++;
        }

        $successCount++;
        log_msg("  ✓ {$featCount} zonas");

        // Pausa cortés con el servidor NWS
        usleep(200000);
    }

    // Construir FeatureCollection final
    $combined = [
        'type'     => 'FeatureCollection',
        'features' => $allFeatures,
        'metadata' => [
            'generated_at'    => date('c'),
            'source'          => 'National Weather Service',
            'source_url'      => 'https://www.weather.gov/beach',
            'day'             => (int)$day,
            'offices_success' => $successCount,
            'offices_failed'  => $errorCount,
            'total_zones'     => count($allFeatures),
            'risk_breakdown'  => [
                'low'      => $stats['low'],
                'moderate' => $stats['moderate'],
                'high'     => $stats['high'],
            ],
            'zones_with_wtemp' => $stats['with_wtemp'],
        ],
    ];

    log_msg(sprintf(
        "Day{$day} total: %d zonas (low: %d, mod: %d, high: %d) | wtemp en %d zonas",
        count($allFeatures), $stats['low'], $stats['moderate'], $stats['high'], $stats['with_wtemp']
    ));

    // Subir a Spaces
    $destPath = $day === 1 ? $config['destination_day1'] : $config['destination_day2'];
    upload_to_spaces($config, $combined, $destPath);
}

// =============================================
// EJECUCIÓN PRINCIPAL
// =============================================
log_msg("=== Canal Meteo Beach Sync v2.0 ===");

$args = $argv ?? [];
$doDay1 = !in_array('--day2', $args);
$doDay2 = in_array('--day2', $args) || in_array('--both', $args);

try {
    if ($doDay1) sync_day($config, 1);
    if ($doDay2) sync_day($config, 2);

    log_msg("=== Sincronización completada ===");
    exit(0);
} catch (Exception $e) {
    log_msg("❌ ERROR: " . $e->getMessage());
    exit(1);
}
