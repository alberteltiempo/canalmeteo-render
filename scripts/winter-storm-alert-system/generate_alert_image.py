#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generador de imágenes de alertas 1080x1920 - Canal Meteo TV
Versión mejorada con traducciones completas y logo
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
import math
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# Traducciones de eventos al español (SOLO español, sin inglés)
EVENT_TRANSLATIONS = {
    'Winter Storm Warning': 'AVISO DE TORMENTA INVERNAL',
    'Blizzard Warning': 'AVISO DE VENTISCA',
    'Ice Storm Warning': 'AVISO DE TORMENTA DE HIELO',
    'Winter Storm Watch': 'VIGILANCIA DE TORMENTA INVERNAL',
    'Extreme Cold Warning': 'AVISO DE FRÍO EXTREMO',
    'Extreme Cold Watch': 'VIGILANCIA DE FRÍO EXTREMO',
    'Wind Chill Warning': 'AVISO DE SENSACIÓN TÉRMICA',
    'Wind Chill Watch': 'VIGILANCIA DE SENSACIÓN TÉRMICA',
    'Winter Weather Advisory': 'ADVERTENCIA DE CLIMA INVERNAL',
    'Tornado Warning': 'AVISO DE TORNADO',
    'Tornado Watch': 'VIGILANCIA DE TORNADO',
    'Severe Thunderstorm Warning': 'AVISO DE TORMENTA SEVERA',
    'Severe Thunderstorm Watch': 'VIGILANCIA DE TORMENTA SEVERA',
    'Flash Flood Warning': 'AVISO DE INUNDACIÓN REPENTINA',
    'Flood Warning': 'AVISO DE INUNDACIÓN',
    'High Wind Warning': 'AVISO DE VIENTOS FUERTES',
    'Wind Advisory': 'ADVERTENCIA DE VIENTO',
    'Freeze Warning': 'AVISO DE HELADA',
    'Frost Advisory': 'ADVERTENCIA DE ESCARCHA',
    'Heat Advisory': 'ADVERTENCIA DE CALOR',
    'Excessive Heat Warning': 'AVISO DE CALOR EXCESIVO',
}

# Colores por tipo de evento
EVENT_COLORS = {
    'Winter Storm Warning': {'primary': '#0ea5e9', 'secondary': '#0369a1', 'accent': '#7dd3fc', 'icon': '❄️'},
    'Blizzard Warning': {'primary': '#8b5cf6', 'secondary': '#6d28d9', 'accent': '#c4b5fd', 'icon': '🌨️'},
    'Ice Storm Warning': {'primary': '#06b6d4', 'secondary': '#0891b2', 'accent': '#67e8f9', 'icon': '🧊'},
    'Extreme Cold Warning': {'primary': '#3b82f6', 'secondary': '#1d4ed8', 'accent': '#93c5fd', 'icon': '🥶'},
    'Extreme Cold Watch': {'primary': '#3b82f6', 'secondary': '#1d4ed8', 'accent': '#93c5fd', 'icon': '🥶'},
    'Wind Chill Warning': {'primary': '#6366f1', 'secondary': '#4338ca', 'accent': '#a5b4fc', 'icon': '💨'},
    'Tornado Warning': {'primary': '#dc2626', 'secondary': '#991b1b', 'accent': '#fca5a5', 'icon': '🌪️'},
    'Severe Thunderstorm Warning': {'primary': '#f97316', 'secondary': '#c2410c', 'accent': '#fdba74', 'icon': '⛈️'},
    'default': {'primary': '#0ea5e9', 'secondary': '#0369a1', 'accent': '#7dd3fc', 'icon': '⚠️'},
}


def translate_text_to_spanish(text):
    """Traducir texto completo del inglés al español usando Google Translate API o diccionario."""
    if not text:
        return "Permanezca en interiores. Evite viajar si es posible. Vista ropa abrigada en capas."
    
    # Diccionario de traducciones completas de frases comunes
    translations = {
        # Frases sobre ropa y protección
        r'dress in layers': 'vístase en capas',
        r'including a hat': 'incluyendo un gorro',
        r'face mask': 'máscara facial',
        r'and gloves': 'y guantes',
        r'if you must go outside': 'si debe salir al exterior',
        r'keep pets indoors': 'mantenga las mascotas en interiores',
        r'as much as possible': 'tanto como sea posible',
        
        # Frases sobre viaje
        r'avoid travel': 'evite viajar',
        r'if you must travel': 'si debe viajar',
        r'use extra caution when driving': 'tenga mucha precaución al conducir',
        r'especially if operating a high profile vehicle': 'especialmente si conduce un vehículo alto',
        r'use caution if you must drive': 'tenga precaución si debe conducir',
        
        # Frases sobre condiciones
        r'secure outdoor objects': 'asegure los objetos exteriores',
        r'persons are urged to stay indoors': 'se recomienda permanecer en interiores',
        r'until conditions improve': 'hasta que mejoren las condiciones',
        r'watch for falling debris': 'esté atento a escombros que caen',
        r'and tree limbs': 'y ramas de árboles',
        r'remain in the lower levels of your home': 'permanezca en los niveles inferiores de su hogar',
        r'during the windstorm': 'durante la tormenta de viento',
        r'and avoid windows': 'y evite las ventanas',
        
        # Peligros
        r'frostbite': 'congelación',
        r'hypothermia': 'hipotermia',
        r'dangerous': 'peligroso',
        r'life threatening': 'potencialmente mortal',
        r'wind chill': 'sensación térmica',
        r'power outages': 'cortes de energía',
        r'power outage': 'corte de energía',
        
        # Otras frases
        r'check on neighbors': 'revise a sus vecinos',
        r'elderly': 'personas mayores',
        r'young children': 'niños pequeños',
        r'those with special needs': 'personas con necesidades especiales',
    }
    
    result = text.lower()
    
    # Aplicar traducciones
    for eng_pattern, esp in translations.items():
        result = re.sub(eng_pattern, esp, result, flags=re.IGNORECASE)
    
    # Capitalizar primera letra de cada oración
    sentences = result.split('. ')
    sentences = [s.strip().capitalize() for s in sentences if s.strip()]
    translated = '. '.join(sentences)
    
    # Si aún tiene mucho inglés, usar mensaje genérico
    english_words = ['the', 'and', 'for', 'with', 'you', 'your', 'this', 'that', 'will', 'can', 'may']
    word_count = sum(1 for word in english_words if f' {word} ' in f' {translated.lower()} ')
    
    if word_count > 3:
        return "Permanezca en interiores. Evite viajar si es posible. Vista ropa abrigada en capas si debe salir."
    
    return translated if translated else "Permanezca en interiores. Evite viajar si es posible."


def get_event_translation(event):
    """Solo devuelve la traducción al español."""
    return EVENT_TRANSLATIONS.get(event, event.upper().replace('WARNING', 'AVISO').replace('WATCH', 'VIGILANCIA').replace('ADVISORY', 'ADVERTENCIA'))


def get_event_colors(event):
    return EVENT_COLORS.get(event, EVENT_COLORS['default'])


def format_number(num):
    try:
        n = int(num)
        if n >= 1000000:
            return f"{n/1000000:.1f}M"
        elif n >= 1000:
            return f"{n/1000:.0f}K"
        return str(n)
    except:
        return str(num)


def km2_to_miles2(km2):
    return int(km2 * 0.386102)


def calculate_polygon_area(coordinates):
    if not coordinates or len(coordinates) < 3:
        return 0
    n = len(coordinates)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        lon1, lat1 = coordinates[i]
        lon2, lat2 = coordinates[j]
        area += lon1 * lat2
        area -= lon2 * lat1
    area = abs(area) / 2.0
    avg_lat = sum(c[1] for c in coordinates) / len(coordinates)
    lat_factor = math.cos(math.radians(avg_lat))
    area_km2 = area * (111 * 111) * lat_factor
    return int(area_km2)


def estimate_population(areas_text, polygon_coords=None):
    if polygon_coords and len(polygon_coords) >= 3:
        area_km2 = calculate_polygon_area(polygon_coords)
        estimated_pop = area_km2 * 30
        return format_number(estimated_pop)
    counties = areas_text.count(';') + 1 if areas_text else 1
    return format_number(counties * 30000)


def estimate_schools(population_str):
    try:
        pop = population_str.replace('K', '000').replace('M', '000000').replace('.', '')
        pop = int(''.join(filter(str.isdigit, pop)) or 0)
        schools = max(1, pop // 1500)
        return str(schools)
    except:
        return "~10"


def extract_main_cities(areas_text, limit=5):
    if not areas_text:
        return "Información no disponible"
    parts = [p.strip() for p in areas_text.split(';')]
    cities = parts[:limit]
    if len(parts) > limit:
        return ', '.join(cities) + f' y {len(parts) - limit} más'
    return ', '.join(cities)


# Mapeo de abreviaciones de estados a nombres completos
US_STATES = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California',
    'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware', 'FL': 'Florida', 'GA': 'Georgia',
    'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa',
    'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
    'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi', 'MO': 'Missouri',
    'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada', 'NH': 'New Hampshire', 'NJ': 'New Jersey',
    'NM': 'New Mexico', 'NY': 'New York', 'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio',
    'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
    'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah', 'VT': 'Vermont',
    'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming',
    'DC': 'Washington DC', 'PR': 'Puerto Rico', 'VI': 'Virgin Islands', 'GU': 'Guam',
}


def extract_state_from_sender(sender_name):
    """Extraer el nombre del estado del sender del NWS."""
    if not sender_name:
        return ""
    
    # El sender suele ser "NWS City ST" o "NWS City ST/Other City"
    # Buscar abreviación de estado de 2 letras
    import re
    
    # Buscar patrón como " MD" o " TX" al final o antes de /
    match = re.search(r'\b([A-Z]{2})\b(?:/|$)', sender_name)
    if match:
        abbrev = match.group(1)
        if abbrev in US_STATES:
            return US_STATES[abbrev]
    
    # Buscar nombre completo del estado en el sender
    sender_upper = sender_name.upper()
    for abbrev, name in US_STATES.items():
        if name.upper() in sender_upper:
            return name
    
    return ""


def get_template():
    return '''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap');
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            width: 1080px;
            height: 1920px;
            font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
            background: linear-gradient(180deg, #0f172a 0%, #1e3a5f 50%, #0f172a 100%);
            color: white;
            overflow: hidden;
        }
        .container {
            width: 1080px;
            height: 1920px;
            display: flex;
            flex-direction: column;
            padding: 80px 35px 40px 35px;
        }
        
        /* Header con solo español */
        .header {
            text-align: center;
            padding: 40px 25px;
            background: linear-gradient(135deg, {{COLOR_PRIMARY}} 0%, {{COLOR_SECONDARY}} 100%);
            border-radius: 24px;
            margin-bottom: 25px;
            position: relative;
            overflow: hidden;
        }
        .header::before {
            content: '';
            position: absolute;
            width: 150px;
            height: 150px;
            opacity: 0.15;
            top: -20px;
            right: 10px;
            background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='white' viewBox='0 0 24 24'%3E%3Cpath d='M22 11h-4.17l3.24-3.24-1.41-1.42L15 11h-2V9l4.66-4.66-1.42-1.41L13 6.17V2h-2v4.17L7.76 2.93 6.34 4.34 11 9v2H9L4.34 6.34 2.93 7.76 6.17 11H2v2h4.17l-3.24 3.24 1.41 1.42L9 13h2v2l-4.66 4.66 1.42 1.41L11 17.83V22h2v-4.17l3.24 3.24 1.42-1.41L13 15v-2h2l4.66 4.66 1.41-1.42L17.83 13H22z'/%3E%3C/svg%3E") no-repeat center;
            background-size: contain;
        }
        .alert-type {
            font-size: 54px;
            font-weight: 900;
            letter-spacing: 2px;
            text-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
            line-height: 1.2;
        }
        
        /* Caja de expiración */
        .expires-box {
            background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%);
            border-radius: 18px;
            padding: 22px 35px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 18px;
        }
        .expires-box svg {
            width: 34px;
            height: 34px;
            fill: white;
        }
        .expires-text { font-size: 30px; font-weight: 700; }
        .expires-time { font-size: 40px; font-weight: 900; color: #fecaca; }
        
        /* Caja del estado */
        .state-box {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 18px 30px;
            margin-bottom: 25px;
            text-align: center;
            border: 2px solid {{COLOR_PRIMARY}};
        }
        .state-name {
            font-size: 42px;
            font-weight: 900;
            color: {{COLOR_ACCENT}};
            text-transform: uppercase;
            letter-spacing: 4px;
        }
        
        /* Mapa */
        .map-container {
            flex: 0 0 480px;
            border-radius: 20px;
            overflow: hidden;
            border: 4px solid {{COLOR_PRIMARY}};
            margin-bottom: 25px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
        }
        #map { width: 100%; height: 100%; }
        
        /* Cajas de información */
        .info-box {
            background: rgba(255, 255, 255, 0.08);
            border-radius: 18px;
            padding: 24px 28px;
            margin-bottom: 22px;
            border-left: 6px solid {{COLOR_PRIMARY}};
        }
        .info-label {
            font-size: 18px;
            font-weight: 800;
            color: {{COLOR_ACCENT}};
            text-transform: uppercase;
            letter-spacing: 3px;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .info-label svg {
            width: 22px;
            height: 22px;
            fill: {{COLOR_ACCENT}};
        }
        .info-text {
            font-size: 28px;
            font-weight: 600;
            line-height: 1.4;
            color: #f1f5f9;
        }
        
        /* Grid de estadísticas */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 14px;
            margin-bottom: 22px;
        }
        .stat-card {
            background: rgba(255, 255, 255, 0.06);
            border-radius: 16px;
            padding: 20px;
            text-align: center;
            border: 2px solid rgba(255, 255, 255, 0.1);
        }
        .stat-icon { 
            width: 42px; 
            height: 42px; 
            margin: 0 auto 10px auto; 
            display: block;
            fill: {{COLOR_ACCENT}};
        }
        .stat-value { font-size: 38px; font-weight: 900; color: {{COLOR_ACCENT}}; }
        .stat-label { font-size: 14px; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; margin-top: 6px; }
        
        /* Caja de recomendaciones */
        .instructions-box {
            background: linear-gradient(135deg, rgba(251, 191, 36, 0.2), rgba(245, 158, 11, 0.08));
            border-left: 6px solid #fbbf24;
            border-radius: 0 18px 18px 0;
            padding: 24px 28px;
            margin-bottom: 25px;
        }
        .instructions-label {
            font-size: 18px;
            font-weight: 800;
            color: #fbbf24;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .instructions-label svg {
            width: 24px;
            height: 24px;
            fill: #fbbf24;
        }
        .instructions-text {
            font-size: 24px;
            color: #fef3c7;
            line-height: 1.5;
        }
        
        /* Footer con logo grande centrado */
        .footer {
            margin-top: auto;
            background: rgba(0, 0, 0, 0.5);
            border-radius: 20px;
            padding: 30px;
            text-align: center;
        }
        .footer-logo {
            margin-bottom: 15px;
        }
        .footer-logo img {
            height: 70px;
        }
        .footer-source { 
            font-size: 16px; 
            color: #64748b; 
            line-height: 1.5;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header SOLO en español -->
        <div class="header">
            <div class="alert-type">{{EVENT_ES}}</div>
        </div>
        
        <!-- Tiempo de expiración -->
        <div class="expires-box">
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z"/></svg>
            <span class="expires-text">VIGENTE HASTA:</span>
            <span class="expires-time">{{EXPIRES_FORMATTED}}</span>
        </div>
        
        <!-- Estado -->
        <div class="state-box">
            <div class="state-name">{{STATE_NAME}}</div>
        </div>
        
        <!-- Mapa -->
        <div class="map-container">
            <div id="map"></div>
        </div>
        
        <!-- Condados -->
        <div class="info-box">
            <div class="info-label">
                <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/></svg>
                Condados bajo alerta
            </div>
            <div class="info-text">{{AREAS}}</div>
        </div>
        
        <!-- Estadísticas -->
        <div class="stats-grid">
            <div class="stat-card">
                <svg class="stat-icon" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/>
                </svg>
                <div class="stat-value">{{POPULATION}}</div>
                <div class="stat-label">Población</div>
            </div>
            <div class="stat-card">
                <svg class="stat-icon" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M5 13.18v4L12 21l7-3.82v-4L12 17l-7-3.82zM12 3L1 9l11 6 9-4.91V17h2V9L12 3z"/>
                </svg>
                <div class="stat-value">{{SCHOOLS}}</div>
                <div class="stat-label">Escuelas</div>
            </div>
            <div class="stat-card">
                <svg class="stat-icon" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M19 9.3V4h-3v2.6L12 3 2 12h3v8h5v-6h4v6h5v-8h3l-3-2.7zm-9 .7c0-1.1.9-2 2-2s2 .9 2 2h-4z"/>
                </svg>
                <div class="stat-value">{{CITIES_COUNT}}</div>
                <div class="stat-label">Condados</div>
            </div>
            <div class="stat-card">
                <svg class="stat-icon" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M20.5 3l-.16.03L15 5.1 9 3 3.36 4.9c-.21.07-.36.25-.36.48V20.5c0 .28.22.5.5.5l.16-.03L9 18.9l6 2.1 5.64-1.9c.21-.07.36-.25.36-.48V3.5c0-.28-.22-.5-.5-.5zM15 19l-6-2.11V5l6 2.11V19z"/>
                </svg>
                <div class="stat-value">{{AREA_MI2}}</div>
                <div class="stat-label">Millas²</div>
            </div>
        </div>
        
        <!-- Recomendaciones -->
        <div class="instructions-box">
            <div class="instructions-label">
                <svg viewBox="0 0 24 24" fill="currentColor"><path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>
                Recomendaciones
            </div>
            <div class="instructions-text">{{INSTRUCTION}}</div>
        </div>
        
        <!-- Footer con logo grande centrado -->
        <div class="footer">
            <div class="footer-logo">
                <img src="https://www.canalmeteo.tv/logos/logocanalmeteo30.png" alt="Canal Meteo TV">
            </div>
            <div class="footer-source">
                Fuente: National Weather Service · {{GENERATED}}
            </div>
        </div>
    </div>
    
    <script>
        const center = [{{CENTER_LAT}}, {{CENTER_LON}}];
        const polygon = {{POLYGON_JSON}};
        
        const map = L.map('map', {
            zoomControl: false,
            attributionControl: false
        }).setView(center, 8);
        
        // Capa base con etiquetas claras
        L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
            maxZoom: 19
        }).addTo(map);
        
        if (polygon && polygon.length > 0) {
            const poly = L.polygon(polygon, {
                color: '{{COLOR_PRIMARY}}',
                weight: 5,
                fillColor: '{{COLOR_PRIMARY}}',
                fillOpacity: 0.30
            }).addTo(map);
            map.fitBounds(poly.getBounds(), { padding: [50, 50] });
        }
        
        // Marcador central
        const centerIcon = L.divIcon({
            html: '<div style="background: {{COLOR_PRIMARY}}; width: 28px; height: 28px; border-radius: 50%; border: 4px solid white; box-shadow: 0 0 20px rgba(0,0,0,0.5);"></div>',
            iconSize: [28, 28],
            iconAnchor: [14, 14]
        });
        L.marker(center, { icon: centerIcon }).addTo(map);
    </script>
</body>
</html>'''


def generate_html_content(alert_data):
    html = get_template()
    
    event = alert_data.get('event', 'Weather Alert')
    event_es = get_event_translation(event)
    colors = get_event_colors(event)
    areas = alert_data.get('areas', 'Área no especificada')
    
    # Fecha de expiración
    expires_dt = alert_data.get('expires_dt')
    expires = alert_data.get('expires', '')
    try:
        if expires_dt:
            expires_formatted = expires_dt.strftime('%d/%m/%Y %H:%M')
        elif expires:
            dt = datetime.fromisoformat(expires.replace('Z', '+00:00'))
            expires_formatted = dt.strftime('%d/%m/%Y %H:%M')
        else:
            expires_formatted = 'No especificado'
    except:
        expires_formatted = expires or 'No especificado'
    
    # Coordenadas
    center = alert_data.get('center', [39.8, -98.5])
    coordinates = alert_data.get('coordinates', [])
    
    # Si no hay coordenadas, crear rectángulo aproximado
    if not coordinates or len(coordinates) < 3:
        lat, lon = center[0], center[1]
        offset = 0.5
        coordinates = [
            [lon - offset, lat - offset],
            [lon + offset, lat - offset],
            [lon + offset, lat + offset],
            [lon - offset, lat + offset],
            [lon - offset, lat - offset],
        ]
        has_polygon = False
    else:
        has_polygon = True
        # Recalcular centro basado en el polígono real
        lons = [c[0] for c in coordinates]
        lats = [c[1] for c in coordinates]
        center = [sum(lats)/len(lats), sum(lons)/len(lons)]
    
    polygon_leaflet = [[c[1], c[0]] for c in coordinates]
    
    # Estadísticas
    area_km2 = calculate_polygon_area(coordinates) if has_polygon else 5000
    area_mi2 = km2_to_miles2(area_km2)
    population = estimate_population(areas, coordinates if has_polygon else None)
    schools = estimate_schools(population)
    cities_count = str(areas.count(';') + 1 if areas else 1)
    main_cities = extract_main_cities(areas)
    
    # Instrucciones - traducir completamente al español
    instruction = alert_data.get('instruction', '')
    instruction = translate_text_to_spanish(instruction)
    if len(instruction) > 220:
        instruction = instruction[:220] + '...'
    
    # Extraer nombre del estado
    sender = alert_data.get('sender', '')
    state_name = extract_state_from_sender(sender)
    
    generated = datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')
    
    replacements = {
        '{{EVENT_ES}}': event_es,
        '{{ICON}}': colors.get('icon', '⚠️'),
        '{{AREAS}}': areas[:150] + '...' if len(areas) > 150 else areas,
        '{{EXPIRES_FORMATTED}}': expires_formatted,
        '{{CENTER_LAT}}': str(center[0]),
        '{{CENTER_LON}}': str(center[1]),
        '{{POLYGON_JSON}}': json.dumps(polygon_leaflet),
        '{{POPULATION}}': population,
        '{{SCHOOLS}}': schools,
        '{{CITIES_COUNT}}': cities_count,
        '{{AREA_MI2}}': format_number(area_mi2),
        '{{MAIN_CITIES}}': main_cities,
        '{{INSTRUCTION}}': instruction,
        '{{GENERATED}}': generated,
        '{{COLOR_PRIMARY}}': colors['primary'],
        '{{COLOR_SECONDARY}}': colors['secondary'],
        '{{COLOR_ACCENT}}': colors['accent'],
        '{{STATE_NAME}}': state_name,
    }
    
    for key, value in replacements.items():
        html = html.replace(key, str(value))
    
    return html


def generate_alert_image(alert_data, output_path, template_path=None):
    """Generar imagen PNG 1080x1920."""
    from playwright.sync_api import sync_playwright
    
    html_content = generate_html_content(alert_data)
    
    temp_html = output_path.replace('.png', '_temp.html')
    with open(temp_html, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1080, 'height': 1920})
            page.goto(f'file://{os.path.abspath(temp_html)}')
            page.wait_for_timeout(3000)  # Más tiempo para cargar logo y mapa
            page.screenshot(path=output_path, full_page=False)
            browser.close()
        
        log.info(f"✅ Imagen generada: {output_path}")
        
        if os.path.exists(temp_html):
            os.remove(temp_html)
        
        return output_path
        
    except Exception as e:
        log.error(f"❌ Error generando imagen: {e}")
        return None


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true')
    parser.add_argument('--output', type=str, default='test_alert.png')
    args = parser.parse_args()
    
    if args.test:
        test_data = {
            'event': 'Extreme Cold Warning',
            'areas': 'Pamlico; Southern Craven; Eastern Carteret',
            'expires': '2026-02-07T14:00:00-05:00',
            'center': [35.1, -76.8],
            'coordinates': [
                [-77.2, 34.8],
                [-76.4, 34.8],
                [-76.4, 35.4],
                [-77.2, 35.4],
                [-77.2, 34.8],
            ],
            'instruction': 'Dress in layers including a hat, face mask, and gloves if you must go outside. Keep pets indoors as much as possible.',
        }
        generate_alert_image(test_data, args.output)
