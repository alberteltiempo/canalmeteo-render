#!/usr/bin/php
<?php
/**
 * Drought Monitor Sync Script
 * Descarga el JSON del NDMC y lo sube a DigitalOcean Spaces
 * 
 * Uso: php sync-drought.php
 * Cron: 0 8 * * 5  (cada viernes a las 8am - se actualiza los jueves)
 */

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
    
    // Archivo destino en Spaces
    'destination_path' => 'data/drought/usdm_current.json',
    
    // URL fuente del Drought Monitor
    'source_url' => 'https://droughtmonitor.unl.edu/data/json/usdm_current.json',
];

// =============================================
// FUNCIONES
// =============================================

function log_msg($msg) {
    echo "[" . date('Y-m-d H:i:s') . "] $msg\n";
}

function download_file($url) {
    log_msg("Descargando desde: $url");
    
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, 120);
    curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, true);
    curl_setopt($ch, CURLOPT_USERAGENT, 'CanalMeteoTV/1.0');
    
    $data = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $error = curl_error($ch);
    curl_close($ch);
    
    if ($httpCode !== 200) {
        throw new Exception("HTTP Error $httpCode: $error");
    }
    
    // Verificar que es JSON válido
    $json = json_decode($data);
    if (json_last_error() !== JSON_ERROR_NONE) {
        throw new Exception("JSON inválido: " . json_last_error_msg());
    }
    
    log_msg("Descargado correctamente. Tamaño: " . strlen($data) . " bytes");
    log_msg("Features encontradas: " . count($json->features ?? []));
    
    return $data;
}

function upload_to_spaces($config, $data, $path) {
    log_msg("Subiendo a Spaces: $path");
    
    $host = $config['spaces_bucket'] . '.' . $config['spaces_endpoint'];
    $url = "https://$host/$path";
    
    // Fecha y hora para la firma
    $date = gmdate('Ymd\THis\Z');
    $dateShort = gmdate('Ymd');
    
    // Content hash
    $contentHash = hash('sha256', $data);
    
    // Headers canónicos
    $headers = [
        'host' => $host,
        'x-amz-content-sha256' => $contentHash,
        'x-amz-date' => $date,
        'content-type' => 'application/json',
        'x-amz-acl' => 'public-read',
    ];
    
    ksort($headers);
    
    // Construir string canónico
    $canonicalHeaders = '';
    $signedHeaders = [];
    foreach ($headers as $key => $value) {
        $canonicalHeaders .= strtolower($key) . ':' . trim($value) . "\n";
        $signedHeaders[] = strtolower($key);
    }
    $signedHeadersStr = implode(';', $signedHeaders);
    
    $canonicalRequest = "PUT\n/$path\n\n$canonicalHeaders\n$signedHeadersStr\n$contentHash";
    
    // String to sign
    $algorithm = 'AWS4-HMAC-SHA256';
    $credentialScope = "$dateShort/{$config['spaces_region']}/s3/aws4_request";
    $stringToSign = "$algorithm\n$date\n$credentialScope\n" . hash('sha256', $canonicalRequest);
    
    // Calcular firma
    $kDate = hash_hmac('sha256', $dateShort, 'AWS4' . $config['spaces_secret'], true);
    $kRegion = hash_hmac('sha256', $config['spaces_region'], $kDate, true);
    $kService = hash_hmac('sha256', 's3', $kRegion, true);
    $kSigning = hash_hmac('sha256', 'aws4_request', $kService, true);
    $signature = hash_hmac('sha256', $stringToSign, $kSigning);
    
    // Authorization header
    $authorization = "$algorithm Credential={$config['spaces_key']}/$credentialScope, SignedHeaders=$signedHeadersStr, Signature=$signature";
    
    // Hacer request
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
    $error = curl_error($ch);
    curl_close($ch);
    
    if ($httpCode !== 200 && $httpCode !== 201) {
        throw new Exception("Upload failed. HTTP $httpCode: $response - $error");
    }
    
    log_msg("✅ Subido correctamente a: https://{$config['spaces_bucket']}.{$config['spaces_endpoint']}/$path");
    
    return true;
}

// =============================================
// EJECUCIÓN PRINCIPAL
// =============================================

log_msg("=== Drought Monitor Sync ===");

try {
    // 1. Descargar archivo
    $data = download_file($config['source_url']);
    
    // 2. Subir a Spaces
    upload_to_spaces($config, $data, $config['destination_path']);
    
    log_msg("=== Sincronización completada ===");
    exit(0);
    
} catch (Exception $e) {
    log_msg("❌ ERROR: " . $e->getMessage());
    exit(1);
}
