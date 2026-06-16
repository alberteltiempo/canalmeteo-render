<?php
/**
 * Canal Meteo TV — sync-metrics.php
 * ─────────────────────────────────
 * Genera data/metrics/traffic.json en el CDN (DigitalOcean Spaces) a partir
 * de Google Analytics 4 (Data API). Pensado para correr en nimbus-01 por cron.
 *
 * Lo consume el dashboard del admin: admin/lib/metrics.php::cmtv_traffic_metrics()
 *   URL: https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/metrics/traffic.json
 *   Forma:
 *     { "updated_at":"ISO", "visits_today":N, "delta_pct":12.4|null,
 *       "series_14d":[{"date":"YYYY-MM-DD","visits":N}...14],
 *       "top_pages":[{"path":"/x","visits":N,"delta_pct":null}...] }
 *
 * Sin dependencias: PHP puro (curl + openssl). No usa composer.
 *
 * ── CONFIGURACIÓN ─────────────────────────────────────────────────────
 *   En nimbus-01 lee automáticamente /opt/canalmeteo/.env (convención del
 *   resto de pipelines). Claves usadas de ese .env:
 *     GA4_PROPERTY_ID       ID numérico de la propiedad GA4 (NO el G-XXXX)
 *     GA4_CREDENTIALS_JSON  Ruta al JSON de la cuenta de servicio (o JSON inline)
 *     SPACES_ACCESS_KEY / SPACES_SECRET_KEY   credenciales de Spaces
 *     SPACES_BUCKET (def. canalmeteo-public) / SPACES_REGION (def. sfo3)
 *
 *   También acepta variables de entorno reales (prioritarias), otra ruta de
 *   .env vía METRICS_ENV=/ruta/.env, o scripts/metrics-secrets.php (gitignored).
 *
 * ── SETUP GA4 (una vez) ───────────────────────────────────────────────
 *   1. Google Cloud Console → habilitar "Google Analytics Data API".
 *   2. Crear una cuenta de servicio → generar clave JSON → guardarla en
 *      nimbus-01 FUERA del webroot (ej: /opt/canalmeteo/ga4-sa.json).
 *   3. En GA4 → Admin → Property Access Management → añadir el email de la
 *      cuenta de servicio (xxx@xxx.iam.gserviceaccount.com) como "Viewer".
 *   4. Copiar el Property ID numérico (GA4 → Admin → Property Settings).
 *
 * ── USO ───────────────────────────────────────────────────────────────
 *   php scripts/sync-metrics.php            genera y SUBE traffic.json al CDN
 *   php scripts/sync-metrics.php --stdout   imprime el JSON, NO sube (para probar)
 *
 * ── CRON en nimbus-01 (cada 10 min) ───────────────────────────────────
 *   (lee /opt/canalmeteo/.env solo, sin variables inline)
 *   0,10,20,30,40,50 * * * * /usr/bin/php /opt/canalmeteo/scripts/sync-metrics.php >> /var/log/canalmeteo/metrics.log 2>&1
 */

declare(strict_types=1);
error_reporting(E_ALL & ~E_DEPRECATED);

$STDOUT_ONLY = in_array('--stdout', $argv, true);

// ── Carga de configuración (env real > /opt/canalmeteo/.env > metrics-secrets.php) ──
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
$localSecrets = __DIR__ . '/metrics-secrets.php';
if (is_file($localSecrets)) require_once $localSecrets;

function cfg(string $name, ?string $default = null): ?string {
    global $ENV_VARS;
    $env = getenv($name);
    if ($env !== false && $env !== '') return $env;
    if (!empty($ENV_VARS[$name])) return $ENV_VARS[$name];
    if (defined($name) && constant($name) !== '') return (string) constant($name);
    return $default;
}

$GA4_PROPERTY_ID   = cfg('GA4_PROPERTY_ID');
$GA4_CRED          = cfg('GA4_CREDENTIALS_JSON') ?: cfg('GA4_SA_KEYFILE'); // ruta a JSON o JSON inline
$SPACES_ACCESS_KEY = cfg('SPACES_ACCESS_KEY');
$SPACES_SECRET_KEY = cfg('SPACES_SECRET_KEY');
$SPACES_BUCKET     = cfg('SPACES_BUCKET', 'canalmeteo-public');
$SPACES_REGION     = cfg('SPACES_REGION', 'sfo3');
$OBJECT_KEY        = 'data/metrics/traffic.json';

function fail(string $msg): void {
    fwrite(STDERR, "[sync-metrics] ERROR: $msg\n");
    exit(1);
}

if (!$GA4_PROPERTY_ID || $GA4_PROPERTY_ID === '123456789') fail('Falta GA4_PROPERTY_ID real en /opt/canalmeteo/.env (hay un placeholder)');
if (!$GA4_CRED) fail('Falta GA4_CREDENTIALS_JSON en /opt/canalmeteo/.env');
if (!$STDOUT_ONLY && (!$SPACES_ACCESS_KEY || !$SPACES_SECRET_KEY)) fail('Faltan credenciales SPACES_ACCESS_KEY/SPACES_SECRET_KEY');

// Resolver credenciales: ruta a archivo o JSON inline
if (isset($GA4_CRED[0]) && $GA4_CRED[0] === '{') {
    $SA_JSON_RAW = $GA4_CRED;
} else {
    if (!is_file($GA4_CRED)) fail("No existe el archivo de credenciales GA4: {$GA4_CRED}");
    $SA_JSON_RAW = (string) file_get_contents($GA4_CRED);
}

// ══════════════════════════════════════════════════════════════════════
//  Google: cuenta de servicio → token OAuth2 (JWT firmado RS256)
// ══════════════════════════════════════════════════════════════════════
function b64url(string $data): string {
    return rtrim(strtr(base64_encode($data), '+/', '-_'), '=');
}

/**
 * Obtiene un access_token de Google. Soporta dos tipos de credencial:
 *   - service_account  (JWT RS256)            → si la org permite SA keys
 *   - authorized_user  (OAuth refresh token)  → recomendado (sin clave SA)
 */
function ga4_access_token(string $credRaw): string {
    $cred = json_decode($credRaw, true);
    if (!is_array($cred)) fail('Las credenciales GA4 no son JSON válido');
    $type = $cred['type'] ?? (isset($cred['private_key']) ? 'service_account'
            : (isset($cred['refresh_token']) ? 'authorized_user' : ''));
    if ($type === 'service_account') return ga4_token_from_sa($cred);
    if ($type === 'authorized_user') return ga4_token_from_user($cred);
    fail('Tipo de credencial GA4 no soportado (esperaba service_account o authorized_user)');
}

/** OAuth de usuario: cambia el refresh_token por un access_token. */
function ga4_token_from_user(array $cred): string {
    foreach (['client_id', 'client_secret', 'refresh_token'] as $k) {
        if (empty($cred[$k])) fail("Credencial authorized_user incompleta: falta $k");
    }
    $resp = http_post('https://oauth2.googleapis.com/token', http_build_query([
        'client_id'     => $cred['client_id'],
        'client_secret' => $cred['client_secret'],
        'refresh_token' => $cred['refresh_token'],
        'grant_type'    => 'refresh_token',
    ]), ['Content-Type: application/x-www-form-urlencoded']);
    $tok = json_decode($resp, true);
    if (!isset($tok['access_token'])) fail('No se obtuvo access_token (refresh_token): ' . substr($resp, 0, 300));
    return $tok['access_token'];
}

/** Service account: firma un JWT RS256 y lo cambia por un access_token. */
function ga4_token_from_sa(array $sa): string {
    if (!isset($sa['client_email'], $sa['private_key'])) {
        fail('El JSON de la cuenta de servicio no es válido (faltan client_email/private_key)');
    }
    $now = time();
    $header = b64url(json_encode(['alg' => 'RS256', 'typ' => 'JWT']));
    $claim  = b64url(json_encode([
        'iss'   => $sa['client_email'],
        'scope' => 'https://www.googleapis.com/auth/analytics.readonly',
        'aud'   => 'https://oauth2.googleapis.com/token',
        'iat'   => $now,
        'exp'   => $now + 3600,
    ]));
    $signingInput = $header . '.' . $claim;
    $signature = '';
    if (!openssl_sign($signingInput, $signature, $sa['private_key'], 'sha256WithRSAEncryption')) {
        fail('No se pudo firmar el JWT (openssl)');
    }
    $jwt = $signingInput . '.' . b64url($signature);
    $resp = http_post('https://oauth2.googleapis.com/token', http_build_query([
        'grant_type' => 'urn:ietf:params:oauth:grant-type:jwt-bearer',
        'assertion'  => $jwt,
    ]), ['Content-Type: application/x-www-form-urlencoded']);
    $tok = json_decode($resp, true);
    if (!isset($tok['access_token'])) fail('No se obtuvo access_token de Google: ' . substr($resp, 0, 300));
    return $tok['access_token'];
}

// ══════════════════════════════════════════════════════════════════════
//  GA4 Data API — runReport
// ══════════════════════════════════════════════════════════════════════
function ga4_run_report(string $token, string $propertyId, array $body): array {
    $url = "https://analyticsdata.googleapis.com/v1beta/properties/{$propertyId}:runReport";
    $resp = http_post($url, json_encode($body), [
        'Authorization: Bearer ' . $token,
        'Content-Type: application/json',
    ]);
    $data = json_decode($resp, true);
    if (!is_array($data) || isset($data['error'])) {
        fail('GA4 runReport falló: ' . substr($resp, 0, 400));
    }
    return $data['rows'] ?? [];
}

// ══════════════════════════════════════════════════════════════════════
//  HTTP helper (curl)
// ══════════════════════════════════════════════════════════════════════
function http_post(string $url, string $body, array $headers): string {
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_POST           => true,
        CURLOPT_POSTFIELDS     => $body,
        CURLOPT_HTTPHEADER     => $headers,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => 20,
    ]);
    $resp = curl_exec($ch);
    if ($resp === false) fail('HTTP error: ' . curl_error($ch));
    curl_close($ch);
    return (string) $resp;
}

// ══════════════════════════════════════════════════════════════════════
//  DigitalOcean Spaces (S3) — PUT con firma AWS SigV4
// ══════════════════════════════════════════════════════════════════════
function spaces_put_json(string $bucket, string $region, string $key, string $body,
                         string $access, string $secret): void {
    $host    = "{$bucket}.{$region}.digitaloceanspaces.com";
    $service = 's3';
    $now     = time();
    $amzDate = gmdate('Ymd\THis\Z', $now);
    $dateStamp = gmdate('Ymd', $now);
    $payloadHash = hash('sha256', $body);

    $canonicalUri = '/' . ltrim($key, '/');
    $headers = [
        'cache-control'        => 'max-age=300',
        'content-type'         => 'application/json',
        'host'                 => $host,
        'x-amz-acl'            => 'public-read',
        'x-amz-content-sha256' => $payloadHash,
        'x-amz-date'           => $amzDate,
    ];
    ksort($headers);
    $canonicalHeaders = '';
    foreach ($headers as $k => $v) $canonicalHeaders .= $k . ':' . $v . "\n";
    $signedHeaders = implode(';', array_keys($headers));

    $canonicalRequest = "PUT\n{$canonicalUri}\n\n{$canonicalHeaders}\n{$signedHeaders}\n{$payloadHash}";
    $scope = "{$dateStamp}/{$region}/{$service}/aws4_request";
    $stringToSign = "AWS4-HMAC-SHA256\n{$amzDate}\n{$scope}\n" . hash('sha256', $canonicalRequest);

    $kDate    = hash_hmac('sha256', $dateStamp, 'AWS4' . $secret, true);
    $kRegion  = hash_hmac('sha256', $region, $kDate, true);
    $kService = hash_hmac('sha256', $service, $kRegion, true);
    $kSigning = hash_hmac('sha256', 'aws4_request', $kService, true);
    $signature = hash_hmac('sha256', $stringToSign, $kSigning);

    $authHeader = "AWS4-HMAC-SHA256 Credential={$access}/{$scope}, "
                . "SignedHeaders={$signedHeaders}, Signature={$signature}";

    $ch = curl_init("https://{$host}{$canonicalUri}");
    curl_setopt_array($ch, [
        CURLOPT_CUSTOMREQUEST  => 'PUT',
        CURLOPT_POSTFIELDS     => $body,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => 20,
        CURLOPT_HTTPHEADER     => [
            'Authorization: ' . $authHeader,
            'x-amz-date: ' . $amzDate,
            'x-amz-content-sha256: ' . $payloadHash,
            'x-amz-acl: public-read',
            'content-type: application/json',
            'cache-control: max-age=300',
        ],
    ]);
    $resp = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    if ($resp === false) fail('Spaces PUT error: ' . curl_error($ch));
    curl_close($ch);
    if ($code < 200 || $code >= 300) fail("Spaces PUT devolvió HTTP {$code}: " . substr((string)$resp, 0, 300));
}

// ══════════════════════════════════════════════════════════════════════
//  MAIN
// ══════════════════════════════════════════════════════════════════════
$token = ga4_access_token($SA_JSON_RAW);

// — Serie de 14 días (sesiones por día) —
$rowsSeries = ga4_run_report($token, $GA4_PROPERTY_ID, [
    'dateRanges' => [['startDate' => '13daysAgo', 'endDate' => 'today']],
    'dimensions' => [['name' => 'date']],
    'metrics'    => [['name' => 'sessions']],
    'orderBys'   => [['dimension' => ['dimensionName' => 'date']]],
]);

$series = [];
foreach ($rowsSeries as $r) {
    $raw = $r['dimensionValues'][0]['value'] ?? '';          // YYYYMMDD
    $visits = (int) ($r['metricValues'][0]['value'] ?? 0);
    if (strlen($raw) === 8) {
        $date = substr($raw, 0, 4) . '-' . substr($raw, 4, 2) . '-' . substr($raw, 6, 2);
        $series[] = ['date' => $date, 'visits' => $visits];
    }
}
$n = count($series);
$visitsToday = $n > 0 ? $series[$n - 1]['visits'] : 0;
$visitsYesterday = $n > 1 ? $series[$n - 2]['visits'] : 0;
$deltaPct = $visitsYesterday > 0
    ? round((($visitsToday - $visitsYesterday) / $visitsYesterday) * 100, 1)
    : null;

// — Páginas más vistas (últimos 7 días) —
$rowsPages = ga4_run_report($token, $GA4_PROPERTY_ID, [
    'dateRanges' => [['startDate' => '7daysAgo', 'endDate' => 'today']],
    'dimensions' => [['name' => 'pagePath']],
    'metrics'    => [['name' => 'screenPageViews']],
    'orderBys'   => [['metric' => ['metricName' => 'screenPageViews'], 'desc' => true]],
    'limit'      => 8,
]);

$topPages = [];
foreach ($rowsPages as $r) {
    $topPages[] = [
        'path'      => $r['dimensionValues'][0]['value'] ?? '',
        'visits'    => (int) ($r['metricValues'][0]['value'] ?? 0),
        'delta_pct' => null,
    ];
}

$payload = [
    'updated_at'   => gmdate('c'),
    'visits_today' => $visitsToday,
    'delta_pct'    => $deltaPct,
    'series_14d'   => $series,
    'top_pages'    => $topPages,
];
$json = json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);

if ($STDOUT_ONLY) {
    echo $json . "\n";
    exit(0);
}

spaces_put_json($SPACES_BUCKET, $SPACES_REGION, $OBJECT_KEY, $json, $SPACES_ACCESS_KEY, $SPACES_SECRET_KEY);
fwrite(STDOUT, "[sync-metrics] OK — traffic.json subido ({$visitsToday} visitas hoy, " . count($series) . " días de serie)\n");
