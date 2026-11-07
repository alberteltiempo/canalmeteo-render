// Tipos compartidos entre componentes

export interface MetarData {
    id: string;            // ICAO ej. "KMCE"
    name: string;          // ej. "Merced Regional"
    distance_mi: number;   // distancia al parque en millas
    temp_f?: number;       // °F
    feels_f?: number;      // °F sensación
    conditions?: string;   // "Despejado", "Nublado", etc.
    conditions_en?: string; // "Clear", "Mostly cloudy", etc. (derivado de skyCover)
    wind?: string;         // "12 mph NO"
    wind_en?: string;      // "12 mph NW"
    humidity?: number;     // %
    dewpoint_f?: number;   // °F
    visibility_mi?: number; // mi
}

export interface CamData {
    code: string;
    park_name_es: string;
    park_name_en: string;
    state: string;
    state_abbr: string;
    view_es: string;
    view_en: string;
    lat: number;
    lon: number;
    elevation_ft: number;
    tz: string;
    tz_abbr: string;
    region: string;
    image_url: string;     // URL de la imagen del CDN
    metar: MetarData;
}

export interface RadarFrame {
    time: number;          // unix timestamp
    path: string;          // path completo de RainViewer
    host: string;          // host de RainViewer (cambia)
}

export interface SegmentData {
    cams: CamData[];       // 4 cámaras a mostrar en este segmento
    radarFrames: RadarFrame[];  // últimas 6 frames de radar
    generatedAt: string;   // ISO timestamp del momento del render
}
