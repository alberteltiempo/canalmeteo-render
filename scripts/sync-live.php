<?php
/**
 * Canal Meteo TV — sync-live.php
 * ──────────────────────────────
 * Genera data/metrics/live.json en el CDN (Spaces) a partir de la YouTube
 * Data API: detecta si el canal está EN DIRECTO y cuántos espectadores tiene.
 *
 * Lo consume el dashboard: admin/lib/metrics.php::cmtv_live_metrics()
 *   URL: https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/metrics/live.json
 *   Forma:
 *     { "updated_at":"ISO", "is_live":true, "concurrent_viewers":2140,
 *       "title":"...", "video_id":"...", "started_at":"ISO" }
 *
 * Sin dependencias (PHP puro: curl). Corre en nimbus-01 por cron.
 *
 * ── EFICIENCIA DE CUOTA (YouTube Data API: 10.000 unidades/día) ───────
 *   search.list = 100 u  ·  videos.list = 1 u
 *   Estrategia: cachea el video_id del directo en un state file.
 *     - Si hay un directo cacheado → solo videos.list (1 u) por ejecución.
 *     - Si no hay directo conocido → search.list (100 u) como mucho 1 vez
 *       cada SEARCH_INTERVAL (15 min) para no agotar la cuota.
 *
 * ── CONFIG (de /opt/canalmeteo/.env) ──────────────────────────────────
 *   YOUTUBE_API_KEY        clave de la YouTube Data API v3
 *   YOUTUBE_CHANNEL_ID     (o YOUTUGE_CHANNEL_ID) ID del canal (UC...)
 *   SPACES_ACCESS_KEY / SPACES_SECRET_KEY / SPACES_BUCKET / SPACES_REGION
 *
 * ── USO ───────────────────────────────────────────────────────────────
 *   php scripts/sync-live.php            genera y SUBE live.json
 *   php scripts/sync-live.php --stdout   imprime, NO sube (para probar)
 *
 * ── CRON en nimbus-01 (cada 5 min) ────────────────────────────────────
 *   0,5,10,15,20,25,30,35,40,45,50,55 * * * * /usr/bin/flock -n /tmp/cmtv_live.lock timeout 40 /usr/bin/php /opt/canalmeteo/scripts/sync-live.php >> /var/log/canalmeteo/live.log 2>&1
 */

declare(strict_types=1);
error_reporting(E_ALL & ~E_DEPRECATED);

$STDOUT_ONLY = in_array('--stdout', $argv, true);
const SEARCH_INTERVAL = 900; // s: cada cuánto buscar directo cuando no hay uno conocido

// ── Config (env real > /opt/canalmeteo/.env) ──────────────────────────
$ENV_VARS = [];
$envFile = getenv('METRICS_ENV') ?: '/opt/canalmeteo/.env';
if (is_file($envFile)) {
    foreach (file($envFile, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        $line = trim($line);
        if ($line === '' || $line[0] === '#' || strpos($line, '=') === false) continue;
        [$k, $v] = explode('=', $line, 2);
        $ENV_VARS[trim($k)] = trim($v, " \t\"'");
    }
}
function cfg(string $name, ?string $default = null): ?string {
    global $ENV_VARS;
    $env = getenv($name);
    if ($env !== false && $env !== '') return $env;
    if (!empty($ENV_VARS[$name])) return $ENV_VARS[$name];
    return $default;
}
function fail(string $msg): void { fwrite(STDERR, "[sync-live] ERROR: $msg\n"); exit(1); }

$YT_KEY      = cfg('YOUTUBE_API_KEY');
$YT_CHANNEL  = cfg('YOUTUBE_CHANNEL_ID') ?: cfg('YOUTUGE_CHANNEL_ID'); // .env tiene el typo YOUTUGE
$SPACES_ACCESS_KEY = cfg('SPACES_ACCESS_KEY');
$SPACES_SECRET_KEY = cfg('SPACES_SECRET_KEY');
$SPACES_BUCKET     = cfg('SPACES_BUCKET', 'canalmeteo-public');
$SPACES_REGION     = cfg('SPACES_REGION', 'sfo3');
$OBJECT_KEY        = 'data/metrics/live.json';
$STATE_FILE        = cfg('LIVE_STATE_FILE', '/opt/canalmeteo/cache/live-state.json');

if (!$YT_KEY)     fail('Falta YOUTUBE_API_KEY en /opt/canalmeteo/.env');
if (!$YT_CHANNEL) fail('Falta YOUTUBE_CHANNEL_ID (o YOUTUGE_CHANNEL_ID) en /opt/canalmeteo/.env');
if (!$STDOUT_ONLY && (!$SPACES_ACCESS_KEY || !$SPACES_SECRET_KEY)) fail('Faltan credenciales SPACES_*');

// ── HTTP GET (curl) ───────────────────────────────────────────────────
function http_get(string $url): array {
    $ch = curl_init($url);
    curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 15]);
    $resp = curl_exec($ch);
    if ($resp === false) fail('HTTP error: ' . curl_error($ch));
    return json_decode((string) $resp, true) ?: [];
}

// ── State (cache del video_id del directo) ────────────────────────────
function load_state(string $f): array {
    if (!is_file($f)) return ['video_id' => '', 'last_search' => 0];
    $d = json_decode((string) @file_get_contents($f), true);
    return is_array($d) ? $d + ['video_id' => '', 'last_search' => 0] : ['video_id' => '', 'last_search' => 0];
}
function save_state(string $f, array $s): void {
    $dir = dirname($f);
    if (!is_dir($dir)) @mkdir($dir, 0775, true);
    @file_put_contents($f, json_encode($s));
}

// ── YouTube: detalles de un video (1 unidad) ──────────────────────────
function yt_video_details(string $key, string $videoId): ?array {
    $d = http_get('https://www.googleapis.com/youtube/v3/videos?' . http_build_query([
        'part' => 'snippet,liveStreamingDetails', 'id' => $videoId, 'key' => $key,
    ]));
    return $d['items'][0] ?? null;
}

// ── YouTube: buscar directo activo del canal (100 unidades) ───────────
function yt_search_live(string $key, string $channelId): ?string {
    $d = http_get('https://www.googleapis.com/youtube/v3/search?' . http_build_query([
        'part' => 'id', 'channelId' => $channelId, 'eventType' => 'live',
        'type' => 'video', 'maxResults' => 1, 'key' => $key,
    ]));
    if (isset($d['error'])) fail('YouTube search falló: ' . ($d['error']['message'] ?? 'error'));
    return $d['items'][0]['id']['videoId'] ?? null;
}

// ══════════════════════════════════════════════════════════════════════
//  MAIN
// ══════════════════════════════════════════════════════════════════════
$state = load_state($STATE_FILE);
$now   = time();
$videoId = $state['video_id'] ?? '';
$liveItem = null;

// 1) Si teníamos un directo, comprobarlo barato (1 u)
if ($videoId) {
    $item = yt_video_details($YT_KEY, $videoId);
    if ($item && (($item['snippet']['liveBroadcastContent'] ?? '') === 'live')) {
        $liveItem = $item;
    } else {
        $videoId = ''; // ya no está en directo
    }
}

// 2) Si no hay directo conocido, buscar (100 u) — pero throttled
if (!$liveItem) {
    if (($now - (int)($state['last_search'] ?? 0)) >= SEARCH_INTERVAL || $STDOUT_ONLY) {
        $state['last_search'] = $now;
        $found = yt_search_live($YT_KEY, $YT_CHANNEL);
        if ($found) {
            $item = yt_video_details($YT_KEY, $found);
            if ($item && (($item['snippet']['liveBroadcastContent'] ?? '') === 'live')) {
                $liveItem = $item;
                $videoId = $found;
            }
        }
    }
}

if ($liveItem) {
    $payload = [
        'updated_at'         => gmdate('c'),
        'is_live'            => true,
        'concurrent_viewers' => (int) ($liveItem['liveStreamingDetails']['concurrentViewers'] ?? 0),
        'title'              => $liveItem['snippet']['title'] ?? 'En directo',
        'video_id'           => $videoId,
        'started_at'         => $liveItem['liveStreamingDetails']['actualStartTime'] ?? null,
    ];
} else {
    $payload = [
        'updated_at'         => gmdate('c'),
        'is_live'            => false,
        'concurrent_viewers' => 0,
        'title'              => null,
        'video_id'           => null,
        'started_at'         => null,
    ];
}

$state['video_id'] = $videoId;
if (!$STDOUT_ONLY) save_state($STATE_FILE, $state);

$json = json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);

if ($STDOUT_ONLY) { echo $json . "\n"; exit(0); }

// ── Subir a Spaces (S3 SigV4) ─────────────────────────────────────────
$host = "{$SPACES_BUCKET}.{$SPACES_REGION}.digitaloceanspaces.com";
$service = 's3'; $amzDate = gmdate('Ymd\THis\Z', $now); $dateStamp = gmdate('Ymd', $now);
$payloadHash = hash('sha256', $json);
$canonicalUri = '/' . ltrim($OBJECT_KEY, '/');
$headers = [
    'cache-control' => 'max-age=60', 'content-type' => 'application/json', 'host' => $host,
    'x-amz-acl' => 'public-read', 'x-amz-content-sha256' => $payloadHash, 'x-amz-date' => $amzDate,
];
ksort($headers);
$canonicalHeaders = ''; foreach ($headers as $k => $v) $canonicalHeaders .= "$k:$v\n";
$signedHeaders = implode(';', array_keys($headers));
$canonicalRequest = "PUT\n{$canonicalUri}\n\n{$canonicalHeaders}\n{$signedHeaders}\n{$payloadHash}";
$scope = "{$dateStamp}/{$SPACES_REGION}/{$service}/aws4_request";
$stringToSign = "AWS4-HMAC-SHA256\n{$amzDate}\n{$scope}\n" . hash('sha256', $canonicalRequest);
$kDate = hash_hmac('sha256', $dateStamp, 'AWS4' . $SPACES_SECRET_KEY, true);
$kRegion = hash_hmac('sha256', $SPACES_REGION, $kDate, true);
$kService = hash_hmac('sha256', $service, $kRegion, true);
$kSigning = hash_hmac('sha256', 'aws4_request', $kService, true);
$signature = hash_hmac('sha256', $stringToSign, $kSigning);
$authHeader = "AWS4-HMAC-SHA256 Credential={$SPACES_ACCESS_KEY}/{$scope}, SignedHeaders={$signedHeaders}, Signature={$signature}";

$ch = curl_init("https://{$host}{$canonicalUri}");
curl_setopt_array($ch, [
    CURLOPT_CUSTOMREQUEST => 'PUT', CURLOPT_POSTFIELDS => $json,
    CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 20,
    CURLOPT_HTTPHEADER => [
        "Authorization: {$authHeader}", "x-amz-date: {$amzDate}",
        "x-amz-content-sha256: {$payloadHash}", 'x-amz-acl: public-read',
        'content-type: application/json', 'cache-control: max-age=60',
    ],
]);
$resp = curl_exec($ch);
$code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
if ($resp === false) fail('Spaces PUT error: ' . curl_error($ch));
if ($code < 200 || $code >= 300) fail("Spaces PUT HTTP {$code}: " . substr((string)$resp, 0, 300));

fwrite(STDOUT, "[sync-live] OK — live.json subido (is_live=" . ($payload['is_live'] ? 'true' : 'false')
    . ($payload['is_live'] ? ', viewers=' . $payload['concurrent_viewers'] : '') . ")\n");
