#!/usr/bin/php
<?php
//**
// * Air Quality Sync Script
// * Descarga datos de calidad del aire de AirNow EPA y los convierte a GeoJSON
// * 
// * Uso: php sync-airquality.php
// * Cron: 0 */3 * * *  (cada 3 horas)
// */
// =============================================
// CONFIGURACIÓN
// =============================================
$config = [
    // DigitalOcean Spaces
    // Cargar credenciales del .env (rotables sin tocar el código)
    'spaces_key'      => trim(shell_exec("grep '^SPACES_ACCESS_KEY=' /opt/canalmeteo/.env | cut -d= -f2")),
    'spaces_secret'   => trim(shell_exec("grep '^SPACES_SECRET_KEY=' /opt/canalmeteo/.env | cut -d= -f2")),
    'spaces_bucket'   => 'canalmeteo-public',
    'spaces_region'   => 'sfo3',
    'spaces_endpoint' => 'sfo3.digitaloceanspaces.com',
    
    // URLs de AirNow
    'sources' => [
        'stations' => [
            'url' => 'https://s3-us-west-1.amazonaws.com/files.airnowtech.org/airnow/today/airnow_conditions.kml',
            'output' => 'data/airquality/stations.geojson',
            'type' => 'points'
        ],
        'contours_combined' => [
            'url' => 'https://s3-us-west-1.amazonaws.com/files.airnowtech.org/airnow/today/cur_aqi_combined.kml',
            'output' => 'data/airquality/contours.geojson',
            'type' => 'polygons'
        ],
        'contours_ozone' => [
            'url' => 'https://s3-us-west-1.amazonaws.com/files.airnowtech.org/airnow/today/cur_aqi_ozone.kml',
            'output' => 'data/airquality/contours-ozone.geojson',
            'type' => 'polygons'
        ],
        'contours_pm25' => [
            'url' => 'https://s3-us-west-1.amazonaws.com/files.airnowtech.org/airnow/today/cur_aqi_pm25.kml',
            'output' => 'data/airquality/contours-pm25.geojson',
            'type' => 'polygons'
        ],
        'forecast_today' => [
            'url' => 'https://s3-us-west-1.amazonaws.com/files.airnowtech.org/airnow/today/forecast_today_usa.kml',
            'output' => 'data/airquality/forecast-today.geojson',
            'type' => 'polygons'
        ],
        'forecast_tomorrow' => [
            'url' => 'https://s3-us-west-1.amazonaws.com/files.airnowtech.org/airnow/today/forecast_tomorrow_usa.kml',
            'output' => 'data/airquality/forecast-tomorrow.geojson',
            'type' => 'polygons'
        ],
    ],
];

// Colores AQI oficiales
$aqiColors = [
    'Good' => '#00e400',
    'Moderate' => '#ffff00',
    'Unhealthy for Sensitive Groups' => '#ff7e00',
    'USG' => '#ff7e00',
    'Unhealthy' => '#ff0000',
    'Very Unhealthy' => '#8f3f97',
    'Hazardous' => '#7e0023',
];

// =============================================
// FUNCIONES
// =============================================

function log_msg($msg) {
    echo "[" . date('Y-m-d H:i:s') . "] $msg\n";
}

function download_file($url) {
    log_msg("Descargando: " . basename($url));
    
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, 180);
    curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, true);
    curl_setopt($ch, CURLOPT_USERAGENT, 'CanalMeteoTV/1.0 (contact: info@canalmeteo.tv)');
    
    $data = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $error = curl_error($ch);
    curl_close($ch);
    
    if ($httpCode !== 200) {
        throw new Exception("HTTP Error $httpCode: $error");
    }
    
    return $data;
}

function kml_to_geojson($kmlContent, $type = 'points') {
    // Si es KMZ (comprimido), descomprimir
    if (substr($kmlContent, 0, 2) === 'PK') {
        $tmpFile = tempnam(sys_get_temp_dir(), 'kmz_');
        file_put_contents($tmpFile, $kmlContent);
        
        $zip = new ZipArchive();
        if ($zip->open($tmpFile) === true) {
            for ($i = 0; $i < $zip->numFiles; $i++) {
                $name = $zip->getNameIndex($i);
                if (pathinfo($name, PATHINFO_EXTENSION) === 'kml') {
                    $kmlContent = $zip->getFromIndex($i);
                    break;
                }
            }
            $zip->close();
        }
        unlink($tmpFile);
    }
    
    // Parsear KML
    libxml_use_internal_errors(true);
    $xml = simplexml_load_string($kmlContent);
    
    if (!$xml) {
        throw new Exception("Error parseando KML");
    }
    
    // Extraer estilos definidos en el documento
    $styles = extractStyles($xml);
    
    // Registrar namespace
    $namespaces = $xml->getNamespaces(true);
    $ns = isset($namespaces['']) ? $namespaces[''] : '';
    
    if ($ns) {
        $xml->registerXPathNamespace('kml', $ns);
        $placemarks = $xml->xpath('//kml:Placemark');
    } else {
        $placemarks = $xml->xpath('//Placemark');
    }
    
    $features = [];
    
    foreach ($placemarks as $placemark) {
        $feature = parsePlacemark($placemark, $ns, $type, $styles);
        if ($feature) {
            $features[] = $feature;
        }
    }
    
    return [
        'type' => 'FeatureCollection',
        'features' => $features,
        'metadata' => [
            'generated_at' => date('c'),
            'source' => 'AirNow EPA',
            'total_features' => count($features),
        ]
    ];
}

function extractStyles($xml) {
    $styles = [];
    
    // Buscar todos los estilos definidos
    foreach ($xml->Document->Style as $style) {
        $id = (string)$style['id'];
        if ($id) {
            $color = null;
            
            // Color de polígono
            if (isset($style->PolyStyle->color)) {
                $color = kmlColorToHex((string)$style->PolyStyle->color);
            }
            // Color de línea como fallback
            if (!$color && isset($style->LineStyle->color)) {
                $color = kmlColorToHex((string)$style->LineStyle->color);
            }
            // Color de icono
            if (!$color && isset($style->IconStyle->color)) {
                $color = kmlColorToHex((string)$style->IconStyle->color);
            }
            
            if ($color) {
                $styles['#' . $id] = $color;
                $styles[$id] = $color;
            }
        }
    }
    
    // También buscar StyleMap
    foreach ($xml->Document->StyleMap as $styleMap) {
        $id = (string)$styleMap['id'];
        if ($id) {
            foreach ($styleMap->Pair as $pair) {
                if ((string)$pair->key === 'normal') {
                    $styleUrl = (string)$pair->styleUrl;
                    $styleUrl = ltrim($styleUrl, '#');
                    if (isset($styles[$styleUrl]) || isset($styles['#' . $styleUrl])) {
                        $styles['#' . $id] = $styles[$styleUrl] ?? $styles['#' . $styleUrl];
                        $styles[$id] = $styles['#' . $id];
                    }
                }
            }
        }
    }
    
    return $styles;
}

function kmlColorToHex($kmlColor) {
    // KML color format: aabbggrr (alpha, blue, green, red)
    // HTML color format: #rrggbb
    if (strlen($kmlColor) !== 8) {
        return null;
    }
    
    $alpha = substr($kmlColor, 0, 2);
    $blue = substr($kmlColor, 2, 2);
    $green = substr($kmlColor, 4, 2);
    $red = substr($kmlColor, 6, 2);
    
    return '#' . $red . $green . $blue;
}

function parsePlacemark($placemark, $ns, $type, $styles = []) {
    global $aqiColors;
    
    $properties = [];
    
    // Nombre
    $name = (string)$placemark->name;
    if ($name) {
        $properties['name'] = $name;
        
        // Intentar extraer categoría del nombre (ej: "Good", "Moderate", etc.)
        $categoryFromName = detectCategoryFromName($name);
        if ($categoryFromName) {
            $properties['category'] = $categoryFromName['category'];
            $properties['color'] = $categoryFromName['color'];
            $properties['category_es'] = $categoryFromName['category_es'];
        }
    }
    
    // Obtener color del estilo referenciado
    if (isset($placemark->styleUrl)) {
        $styleUrl = (string)$placemark->styleUrl;
        if (isset($styles[$styleUrl])) {
            $styleColor = $styles[$styleUrl];
            $properties['color'] = $styleColor;
            
            // Detectar categoría por color
            $categoryFromColor = detectCategoryFromColor($styleColor);
            if ($categoryFromColor && !isset($properties['category'])) {
                $properties['category'] = $categoryFromColor['category'];
                $properties['category_es'] = $categoryFromColor['category_es'];
            }
        }
    }
    
    // Color inline en el placemark
    if (isset($placemark->Style->PolyStyle->color)) {
        $inlineColor = kmlColorToHex((string)$placemark->Style->PolyStyle->color);
        if ($inlineColor) {
            $properties['color'] = $inlineColor;
            $categoryFromColor = detectCategoryFromColor($inlineColor);
            if ($categoryFromColor) {
                $properties['category'] = $categoryFromColor['category'];
                $properties['category_es'] = $categoryFromColor['category_es'];
            }
        }
    }
    
    // Descripción (puede contener datos HTML)
    $description = (string)$placemark->description;
    if ($description) {
        $properties['description_html'] = $description;
        
        // Extraer AQI de la descripción
        if (preg_match('/AQI[:\s]*(\d+)/i', $description, $m)) {
            $properties['aqi'] = (int)$m[1];
        }
        
        // Extraer categoría
        if (preg_match('/Category[:\s]*([^<\n,]+)/i', $description, $m)) {
            $properties['category'] = trim($m[1]);
        }
        
        // Extraer contaminante
        if (preg_match('/(?:Pollutant|Parameter)[:\s]*([^<\n,]+)/i', $description, $m)) {
            $properties['pollutant'] = trim($m[1]);
        }
        
        // Extraer área de reporte
        if (preg_match('/(?:Reporting Area|Area)[:\s]*([^<\n]+)/i', $description, $m)) {
            $properties['reporting_area'] = trim($m[1]);
        }
        
        // Extraer estado
        if (preg_match('/(?:State|Estado)[:\s]*([A-Z]{2})/i', $description, $m)) {
            $properties['state'] = trim($m[1]);
        }
        
        // Extraer fecha/hora de observación
        if (preg_match('/(?:Valid Date|Date|Observation)[:\s]*([^<\n]+)/i', $description, $m)) {
            $properties['observation_time'] = trim($m[1]);
        }
        
        // Extraer discusión/comentarios
        if (preg_match('/(?:Discussion|Comments)[:\s]*([^<]+)/i', $description, $m)) {
            $properties['discussion'] = trim($m[1]);
        }
    }
    
    // Extended Data
    if (isset($placemark->ExtendedData)) {
        foreach ($placemark->ExtendedData->Data as $data) {
            $dataName = (string)$data['name'];
            $dataValue = (string)$data->value;
            
            $nameLower = strtolower($dataName);
            
            if ($nameLower === 'aqi') {
                $properties['aqi'] = (int)$dataValue;
            } elseif ($nameLower === 'category') {
                $properties['category'] = $dataValue;
            } elseif ($nameLower === 'pollutant' || $nameLower === 'parameter') {
                $properties['pollutant'] = $dataValue;
            } elseif ($nameLower === 'sitename' || $nameLower === 'site_name') {
                $properties['site_name'] = $dataValue;
            } elseif ($nameLower === 'state') {
                $properties['state'] = $dataValue;
            } elseif ($nameLower === 'reportingarea') {
                $properties['reporting_area'] = $dataValue;
            } elseif ($nameLower === 'latitude') {
                $properties['lat'] = (float)$dataValue;
            } elseif ($nameLower === 'longitude') {
                $properties['lng'] = (float)$dataValue;
            }
        }
    }
    
    // Determinar color basado en AQI si aún no tenemos color
    if (isset($properties['aqi']) && !isset($properties['color'])) {
        $aqi = $properties['aqi'];
        $catInfo = getAqiCategoryInfo($aqi);
        $properties['color'] = $catInfo['color'];
        $properties['category'] = $properties['category'] ?? $catInfo['category'];
        $properties['category_es'] = $catInfo['category_es'];
    }
    
    // Asegurar traducción de categoría
    if (isset($properties['category']) && !isset($properties['category_es'])) {
        $translations = [
            'Good' => 'Buena',
            'Moderate' => 'Moderada',
            'Unhealthy for Sensitive Groups' => 'Dañina para grupos sensibles',
            'USG' => 'Dañina para grupos sensibles',
            'Unhealthy' => 'Dañina',
            'Very Unhealthy' => 'Muy dañina',
            'Hazardous' => 'Peligrosa',
        ];
        $properties['category_es'] = $translations[$properties['category']] ?? $properties['category'];
    }
    
    // Traducir contaminantes
    if (isset($properties['pollutant'])) {
        $pollutantTranslations = [
            'OZONE' => 'Ozono',
            'O3' => 'Ozono',
            'PM2.5' => 'PM2.5 (Partículas finas)',
            'PM10' => 'PM10 (Partículas)',
            'CO' => 'Monóxido de carbono',
            'SO2' => 'Dióxido de azufre',
            'NO2' => 'Dióxido de nitrógeno',
        ];
        $pollutant = strtoupper($properties['pollutant']);
        $properties['pollutant_es'] = $pollutantTranslations[$pollutant] ?? $properties['pollutant'];
    }
    
    // Geometría
    $geometry = null;
    
    // Point
    if (isset($placemark->Point->coordinates)) {
        $coords = trim((string)$placemark->Point->coordinates);
        $parts = explode(',', $coords);
        if (count($parts) >= 2) {
            $geometry = [
                'type' => 'Point',
                'coordinates' => [(float)$parts[0], (float)$parts[1]]
            ];
        }
    }
    
    // Polygon (para contornos)
    if (isset($placemark->Polygon)) {
        $coordsStr = trim((string)$placemark->Polygon->outerBoundaryIs->LinearRing->coordinates);
        $coordPairs = preg_split('/\s+/', $coordsStr);
        $coordinates = [];
        
        foreach ($coordPairs as $pair) {
            $parts = explode(',', $pair);
            if (count($parts) >= 2) {
                $coordinates[] = [(float)$parts[0], (float)$parts[1]];
            }
        }
        
        if (count($coordinates) > 2) {
            $geometry = [
                'type' => 'Polygon',
                'coordinates' => [$coordinates]
            ];
        }
    }
    
    // MultiGeometry
    if (isset($placemark->MultiGeometry)) {
        $polygons = [];
        foreach ($placemark->MultiGeometry->Polygon as $polygon) {
            $coordsStr = trim((string)$polygon->outerBoundaryIs->LinearRing->coordinates);
            $coordPairs = preg_split('/\s+/', $coordsStr);
            $coordinates = [];
            
            foreach ($coordPairs as $pair) {
                $parts = explode(',', $pair);
                if (count($parts) >= 2) {
                    $coordinates[] = [(float)$parts[0], (float)$parts[1]];
                }
            }
            
            if (count($coordinates) > 2) {
                $polygons[] = [$coordinates];
            }
        }
        
        if (count($polygons) > 0) {
            $geometry = [
                'type' => 'MultiPolygon',
                'coordinates' => $polygons
            ];
        }
    }
    
    if (!$geometry) {
        return null;
    }
    
    return [
        'type' => 'Feature',
        'properties' => $properties,
        'geometry' => $geometry
    ];
}

function detectCategoryFromName($name) {
    $name = strtolower($name);
    
    $categories = [
        'good' => ['category' => 'Good', 'color' => '#00e400', 'category_es' => 'Buena'],
        'moderate' => ['category' => 'Moderate', 'color' => '#ffff00', 'category_es' => 'Moderada'],
        'unhealthy for sensitive' => ['category' => 'Unhealthy for Sensitive Groups', 'color' => '#ff7e00', 'category_es' => 'Dañina para grupos sensibles'],
        'usg' => ['category' => 'Unhealthy for Sensitive Groups', 'color' => '#ff7e00', 'category_es' => 'Dañina para grupos sensibles'],
        'unhealthy' => ['category' => 'Unhealthy', 'color' => '#ff0000', 'category_es' => 'Dañina'],
        'very unhealthy' => ['category' => 'Very Unhealthy', 'color' => '#8f3f97', 'category_es' => 'Muy dañina'],
        'hazardous' => ['category' => 'Hazardous', 'color' => '#7e0023', 'category_es' => 'Peligrosa'],
    ];
    
    foreach ($categories as $key => $info) {
        if (strpos($name, $key) !== false) {
            return $info;
        }
    }
    
    return null;
}

function detectCategoryFromColor($hexColor) {
    $hexColor = strtolower($hexColor);
    
    // Mapeo de colores AQI (con tolerancia)
    $colorMap = [
        '#00e400' => ['category' => 'Good', 'category_es' => 'Buena'],
        '#00e500' => ['category' => 'Good', 'category_es' => 'Buena'],
        '#00ff00' => ['category' => 'Good', 'category_es' => 'Buena'],
        '#ffff00' => ['category' => 'Moderate', 'category_es' => 'Moderada'],
        '#ffff01' => ['category' => 'Moderate', 'category_es' => 'Moderada'],
        '#ff7e00' => ['category' => 'Unhealthy for Sensitive Groups', 'category_es' => 'Dañina para grupos sensibles'],
        '#ff8000' => ['category' => 'Unhealthy for Sensitive Groups', 'category_es' => 'Dañina para grupos sensibles'],
        '#ffa500' => ['category' => 'Unhealthy for Sensitive Groups', 'category_es' => 'Dañina para grupos sensibles'],
        '#ff0000' => ['category' => 'Unhealthy', 'category_es' => 'Dañina'],
        '#ff0001' => ['category' => 'Unhealthy', 'category_es' => 'Dañina'],
        '#8f3f97' => ['category' => 'Very Unhealthy', 'category_es' => 'Muy dañina'],
        '#99004c' => ['category' => 'Very Unhealthy', 'category_es' => 'Muy dañina'],
        '#800080' => ['category' => 'Very Unhealthy', 'category_es' => 'Muy dañina'],
        '#7e0023' => ['category' => 'Hazardous', 'category_es' => 'Peligrosa'],
        '#7e0024' => ['category' => 'Hazardous', 'category_es' => 'Peligrosa'],
        '#800000' => ['category' => 'Hazardous', 'category_es' => 'Peligrosa'],
    ];
    
    if (isset($colorMap[$hexColor])) {
        return $colorMap[$hexColor];
    }
    
    // Intentar detectar por rango de color
    $r = hexdec(substr($hexColor, 1, 2));
    $g = hexdec(substr($hexColor, 3, 2));
    $b = hexdec(substr($hexColor, 5, 2));
    
    // Verde = Good
    if ($g > 200 && $r < 100 && $b < 100) {
        return ['category' => 'Good', 'category_es' => 'Buena'];
    }
    // Amarillo = Moderate
    if ($r > 200 && $g > 200 && $b < 100) {
        return ['category' => 'Moderate', 'category_es' => 'Moderada'];
    }
    // Naranja = USG
    if ($r > 200 && $g > 100 && $g < 180 && $b < 50) {
        return ['category' => 'Unhealthy for Sensitive Groups', 'category_es' => 'Dañina para grupos sensibles'];
    }
    // Rojo = Unhealthy
    if ($r > 200 && $g < 50 && $b < 50) {
        return ['category' => 'Unhealthy', 'category_es' => 'Dañina'];
    }
    // Púrpura = Very Unhealthy
    if ($r > 100 && $r < 180 && $b > 100) {
        return ['category' => 'Very Unhealthy', 'category_es' => 'Muy dañina'];
    }
    // Marrón oscuro = Hazardous
    if ($r > 100 && $r < 150 && $g < 50 && $b < 50) {
        return ['category' => 'Hazardous', 'category_es' => 'Peligrosa'];
    }
    
    return null;
}

function getAqiCategoryInfo($aqi) {
    if ($aqi <= 50) {
        return ['color' => '#00e400', 'category' => 'Good', 'category_es' => 'Buena'];
    } elseif ($aqi <= 100) {
        return ['color' => '#ffff00', 'category' => 'Moderate', 'category_es' => 'Moderada'];
    } elseif ($aqi <= 150) {
        return ['color' => '#ff7e00', 'category' => 'Unhealthy for Sensitive Groups', 'category_es' => 'Dañina para grupos sensibles'];
    } elseif ($aqi <= 200) {
        return ['color' => '#ff0000', 'category' => 'Unhealthy', 'category_es' => 'Dañina'];
    } elseif ($aqi <= 300) {
        return ['color' => '#8f3f97', 'category' => 'Very Unhealthy', 'category_es' => 'Muy dañina'];
    } else {
        return ['color' => '#7e0023', 'category' => 'Hazardous', 'category_es' => 'Peligrosa'];
    }
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

log_msg("=== Air Quality Sync ===");

$successCount = 0;
$errorCount = 0;

foreach ($config['sources'] as $name => $source) {
    try {
        log_msg("--- Procesando: $name ---");
        $kmlData = download_file($source['url']);
        $geoJson = kml_to_geojson($kmlData, $source['type']);
        log_msg("Features procesados: " . count($geoJson['features']));
        upload_to_spaces($config, $geoJson, $source['output']);
        $successCount++;
    } catch (Exception $e) {
        log_msg("⚠️ Error en $name: " . $e->getMessage());
        $errorCount++;
    }
}

log_msg("=== Sincronización completada ===");
log_msg("Exitosos: $successCount / Errores: $errorCount");

exit($errorCount > 0 ? 1 : 0);
