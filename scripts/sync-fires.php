#!/usr/bin/php
<?php
//**
// * Active Fires Sync Script
// * Descarga datos de incendios activos del NIFC y los procesa para Canal Meteo
//  * 
//  * Uso: php sync-fires.php
//  * Cron: 0 */6 * * *  (cada 6 horas)
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
    
    // URLs de datos de incendios (NIFC - National Interagency Fire Center)
    'fires_geojson_url' => 'https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/Current_WildlandFire_Locations/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson',
    'perimeters_url' => 'https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/Current_WildlandFire_Perimeters/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson',
    
    // Archivos destino
    'fires_json_path' => 'data/fires/active-fires.json',
    'perimeters_path' => 'data/fires/fire-perimeters.geojson',
];

// =============================================
// FUNCIONES
// =============================================

function log_msg($msg) {
    echo "[" . date('Y-m-d H:i:s') . "] $msg\n";
}

function download_json($url) {
    log_msg("Descargando: " . substr($url, 0, 80) . "...");
    
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, 180);
    curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, true);
    curl_setopt($ch, CURLOPT_USERAGENT, 'CanalMeteoTV/1.0');
    
    $data = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $error = curl_error($ch);
    curl_close($ch);
    
    if ($httpCode !== 200) {
        throw new Exception("HTTP Error $httpCode: $error");
    }
    
    $json = json_decode($data, true);
    if (json_last_error() !== JSON_ERROR_NONE) {
        throw new Exception("JSON inválido: " . json_last_error_msg());
    }
    
    return $json;
}

function process_fires($geojson) {
    $fires = [];
    $totalAcres = 0;
    $totalContainment = 0;
    $containmentCount = 0;
    
    if (!isset($geojson['features'])) {
        return [
            'total_fires' => 0,
            'total_acres' => 0,
            'avg_containment' => 0,
            'fires' => [],
            'updated_at' => date('c'),
        ];
    }
    
    foreach ($geojson['features'] as $feature) {
        $props = $feature['properties'] ?? [];
        $coords = $feature['geometry']['coordinates'] ?? [0, 0];
        
        // Solo incluir incendios en EE.UU.
        $state = $props['POOState'] ?? $props['IncidentState'] ?? '';
        if (empty($state)) continue;
        
        $acres = floatval($props['DailyAcres'] ?? $props['GISAcres'] ?? $props['CalculatedAcres'] ?? 0);
        $containment = intval($props['PercentContained'] ?? 0);
        
        $fire = [
            'id' => $props['OBJECTID'] ?? $props['IncidentID'] ?? uniqid(),
            'name' => $props['IncidentName'] ?? 'Unknown Fire',
            'state' => $state,
            'county' => $props['POOCounty'] ?? '',
            'lat' => floatval($coords[1] ?? 0),
            'lng' => floatval($coords[0] ?? 0),
            'acres' => $acres,
            'containment' => $containment,
            'start_date' => $props['FireDiscoveryDateTime'] ? date('M j, Y', strtotime($props['FireDiscoveryDateTime'])) : '',
            'personnel' => intval($props['TotalIncidentPersonnel'] ?? 0),
            'cause' => $props['FireCause'] ?? '',
        ];
        
        // Validar coordenadas
        if ($fire['lat'] == 0 || $fire['lng'] == 0) continue;
        if ($fire['lat'] < 24 || $fire['lat'] > 72) continue; // Fuera de EE.UU.
        if ($fire['lng'] < -180 || $fire['lng'] > -60) continue;
        
        $fires[] = $fire;
        $totalAcres += $acres;
        
        if ($containment > 0) {
            $totalContainment += $containment;
            $containmentCount++;
        }
    }
    
    // Ordenar por acres (mayor primero)
    usort($fires, function($a, $b) {
        return $b['acres'] <=> $a['acres'];
    });
    
    $avgContainment = $containmentCount > 0 ? round($totalContainment / $containmentCount) : 0;
    
    return [
        'total_fires' => count($fires),
        'total_acres' => round($totalAcres),
        'avg_containment' => $avgContainment,
        'fires' => $fires,
        'updated_at' => date('c'),
    ];
}

function upload_to_spaces($config, $data, $path, $contentType = 'application/json') {
    log_msg("Subiendo a Spaces: $path");
    
    if (is_array($data)) {
        $data = json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
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
        'content-type' => $contentType,
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
        "Content-Type: $contentType",
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

log_msg("=== Active Fires Sync ===");

try {
    // 1. Descargar y procesar incendios
    $firesGeoJson = download_json($config['fires_geojson_url']);
    $firesData = process_fires($firesGeoJson);
    
    log_msg("Incendios encontrados: " . $firesData['total_fires']);
    log_msg("Acres totales: " . number_format($firesData['total_acres']));
    
    // 2. Subir JSON procesado
    upload_to_spaces($config, $firesData, $config['fires_json_path']);
    
    // 3. Descargar y subir perímetros
    try {
        $perimeters = download_json($config['perimeters_url']);
        upload_to_spaces($config, json_encode($perimeters), $config['perimeters_path']);
    } catch (Exception $e) {
        log_msg("⚠️ No se pudieron obtener perímetros: " . $e->getMessage());
    }
    
    log_msg("=== Sincronización completada ===");
    exit(0);
    
} catch (Exception $e) {
    log_msg("❌ ERROR: " . $e->getMessage());
    exit(1);
}
