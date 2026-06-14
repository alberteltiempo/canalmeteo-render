#!/usr/bin/php
<?php
//**
// * Beach/Rip Current Sync Script
// * Descarga datos de corrientes de resaca del NWS y los combina
// * 
// * Uso: php sync-beach.php
// * Cron: 0 */4 * * *  (cada 4 horas)
// */
// =============================================
// CONFIGURACIÓN
// =============================================
$config = [
    // DigitalOcean Spaces
    'spaces_key'      => 'DO801TTXWZBCH2GJAHRZ',
    'spaces_secret'   => 'lHXcvhMwwQg/99YgukMU8aZYQIGD18t7gfocsLlLeSw',
    'spaces_bucket'   => 'canalmeteo-public',
    'spaces_region'   => 'sfo3',
    'spaces_endpoint' => 'sfo3.digitaloceanspaces.com',
    
    // Archivo destino
    'destination_path' => 'data/beach/rip-currents.geojson',
    
    // Oficinas NWS con pronóstico de playa
    'nws_offices' => [
        'apx', 'akq', 'buf', 'box', 'bro', 'car', 'chs', 'cle', 'crp',
        'dlh', 'dtx', 'grb', 'grr', 'gum', 'gyx', 'hfo', 'ilm', 'iwx',
        'jax', 'lot', 'lox', 'mfl', 'mhx', 'mlb', 'mkx', 'mob', 'mqt',
        'okx', 'phi', 'sgx', 'tae', 'tbw'
    ],
];

// =============================================
// FUNCIONES
// =============================================

function log_msg($msg) {
    echo "[" . date('Y-m-d H:i:s') . "] $msg\n";
}

function download_json($url, $timeout = 30) {
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, $timeout);
    curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, true);
    curl_setopt($ch, CURLOPT_USERAGENT, 'CanalMeteoTV/1.0 (contact: info@canalmeteo.tv)');
    
    $data = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $error = curl_error($ch);
    curl_close($ch);
    
    if ($httpCode !== 200) {
        return null;
    }
    
    $json = json_decode($data, true);
    if (json_last_error() !== JSON_ERROR_NONE) {
        return null;
    }
    
    return $json;
}

function upload_to_spaces($config, $data, $path) {
    log_msg("Subiendo a Spaces: $path");
    
    if (is_array($data)) {
        $data = json_encode($data, JSON_UNESCAPED_UNICODE);
    }
    
    $host = $config['spaces_bucket'] . '.' . $config['spaces_endpoint'];
    $url = "https://$host/$path";
    
    $date = gmdate('Ymd\THis\Z');
    $dateShort = gmdate('Ymd');
    $contentHash = hash('sha256', $data);
    
    $headers = [
        'host' => $host,
        'x-amz-content-sha256' => $contentHash,
        'x-amz-date' => $date,
        'content-type' => 'application/json',
        'x-amz-acl' => 'public-read',
    ];
    
    ksort($headers);
    
    $canonicalHeaders = '';
    $signedHeaders = [];
    foreach ($headers as $key => $value) {
        $canonicalHeaders .= strtolower($key) . ':' . trim($value) . "\n";
        $signedHeaders[] = strtolower($key);
    }
    $signedHeadersStr = implode(';', $signedHeaders);
    
    $canonicalRequest = "PUT\n/$path\n\n$canonicalHeaders\n$signedHeadersStr\n$contentHash";
    
    $algorithm = 'AWS4-HMAC-SHA256';
    $credentialScope = "$dateShort/{$config['spaces_region']}/s3/aws4_request";
    $stringToSign = "$algorithm\n$date\n$credentialScope\n" . hash('sha256', $canonicalRequest);
    
    $kDate = hash_hmac('sha256', $dateShort, 'AWS4' . $config['spaces_secret'], true);
    $kRegion = hash_hmac('sha256', $config['spaces_region'], $kDate, true);
    $kService = hash_hmac('sha256', 's3', $kRegion, true);
    $kSigning = hash_hmac('sha256', 'aws4_request', $kService, true);
    $signature = hash_hmac('sha256', $stringToSign, $kSigning);
    
    $authorization = "$algorithm Credential={$config['spaces_key']}/$credentialScope, SignedHeaders=$signedHeadersStr, Signature=$signature";
    
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $url);
    curl_setopt($ch, CURLOPT_CUSTOMREQUEST, 'PUT');
    curl_setopt($ch, CURLOPT_POSTFIELDS, $data);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_HTTPHEADER, [
        "Host: $host",
        "Content-Type: application/json",
        "x-amz-content-sha256: $contentHash",
        "x-amz-date: $date",
        "x-amz-acl: public-read",
        "Authorization: $authorization",
    ]);
    
    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    
    if ($httpCode !== 200 && $httpCode !== 201) {
        throw new Exception("Upload failed. HTTP $httpCode: $response");
    }
    
    log_msg("✅ Subido: https://{$config['spaces_bucket']}.{$config['spaces_endpoint']}/$path");
    
    return true;
}

// =============================================
// EJECUCIÓN PRINCIPAL
// =============================================

log_msg("=== Beach/Rip Current Sync ===");

$allFeatures = [];
$successCount = 0;
$errorCount = 0;

foreach ($config['nws_offices'] as $office) {
    $officeUpper = strtoupper($office);
    $url = "https://www.weather.gov/source/{$office}/beachforecast/{$officeUpper}_GIS_day1.json";
    
    log_msg("Descargando: $officeUpper");
    
    $data = download_json($url);
    
    if ($data && isset($data['features']) && is_array($data['features'])) {
        foreach ($data['features'] as $feature) {
            // Añadir la oficina NWS al feature
            if (!isset($feature['properties'])) {
                $feature['properties'] = [];
            }
            $feature['properties']['nws_office'] = $officeUpper;
            
            // Normalizar el nivel de riesgo
            $risk = strtolower($feature['properties']['risk'] ?? $feature['properties']['RISK'] ?? '');
            if (strpos($risk, 'high') !== false) {
                $feature['properties']['risk_level'] = 'high';
                $feature['properties']['risk_num'] = 3;
            } elseif (strpos($risk, 'mod') !== false) {
                $feature['properties']['risk_level'] = 'moderate';
                $feature['properties']['risk_num'] = 2;
            } else {
                $feature['properties']['risk_level'] = 'low';
                $feature['properties']['risk_num'] = 1;
            }
            
            $allFeatures[] = $feature;
        }
        $successCount++;
        log_msg("  ✓ {$officeUpper}: " . count($data['features']) . " zonas");
    } else {
        $errorCount++;
        log_msg("  ✗ {$officeUpper}: No disponible");
    }
    
    // Pequeña pausa para no sobrecargar el servidor del NWS
    usleep(200000); // 200ms
}

// Crear GeoJSON combinado
$combinedGeoJson = [
    'type' => 'FeatureCollection',
    'features' => $allFeatures,
    'metadata' => [
        'generated_at' => date('c'),
        'source' => 'National Weather Service',
        'offices_success' => $successCount,
        'offices_failed' => $errorCount,
        'total_zones' => count($allFeatures),
    ]
];

log_msg("Total: " . count($allFeatures) . " zonas de " . $successCount . " oficinas");

// Subir a Spaces
try {
    upload_to_spaces($config, $combinedGeoJson, $config['destination_path']);
    log_msg("=== Sincronización completada ===");
    exit(0);
} catch (Exception $e) {
    log_msg("❌ ERROR: " . $e->getMessage());
    exit(1);
}
