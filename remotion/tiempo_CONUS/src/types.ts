// ─── Satélite full-disk (data/satellite-fd/{vista}/manifest.json) ───
export type SatFrame = { url: string; time: number };
export type SatBounds = { north: number; south: number; west: number; east: number };

// Multi-banda: guardamos varias bandas del mismo manifest (geocolor, ir…)
export type SatData = {
  view: string;
  sat?: string; // GOES19 | GOES18
  bounds: SatBounds | null;
  bands: Record<string, SatFrame[]>;
};

// Vista de una sola banda (lo que consume SatMap)
export type SatView = {
  view: string;
  band: string;
  sat?: string;
  bounds: SatBounds | null;
  frames: SatFrame[];
};

// ─── Radar CONUS (data/radar_conus/manifest.json) ───
// Frames JPG ya compuestos con basemap (MRMS · EEUU), 16:9.
export type RadarData = {
  frames: string[]; // URLs de los frames, viejo → nuevo
  updated?: string; // ISO del último frame
  spanMinutes: number; // ventana temporal cubierta (p.ej. 180 = 3 h)
};

// ─── Alertas NWS (data/alertas/alertas_nws.json) ───
// Una alerta normalizada por el pipeline. `tipo` es la categoría interna.
export type AlertItem = {
  id: string;
  evento: string; // "Tornado Watch"
  evento_es: string; // "Vigilancia de Tornado"
  tipo: string; // inundacion | calor | tormenta | tornado | invierno | …
  color?: string;
  severity?: string;
  estado?: string; // "TX"
  estado_nombre?: string;
  area_desc?: string;
  area_count?: number;
  poblacion?: number;
  effective?: string;
  expires?: string;
  headline?: string;
  // true = vigilancia/aviso agrupado (zona grande); false = warning individual.
  is_grouped?: boolean;
};

export type AlertsData = {
  timestamp?: string;
  conteos?: {
    total?: number;
    warnings?: number;
    watches?: number;
    tornado?: number;
    tormenta?: number;
    inundacion?: number;
    invierno?: number;
    calor?: number;
    con_geometria?: number;
  };
  // Solo las vigilancias (watches), ya filtradas en calculateMetadata:
  watches: AlertItem[];
  // GeoJSON con la geometría de esas vigilancias (las que la tengan):
  geojson?: any;
};

// Nivel/modo cromático del segmento. "alert" = Modo Rojo (tornado/severo/huracán).
export type ThemeMode = "normal" | "alert";

// ─── Servicios CONUS (datos puntuales por ciudad/aeropuerto) ───
// Coordenadas y nombres en español se curan localmente; el feed solo trae valores
// indexados por `id` (IATA para aeropuertos, id de ciudad para UV/AQI).
export type AirStatus = "open" | "delay" | "closed";
export type Airport = {
  id: string;
  iata: string;
  city: string;
  lon: number;
  lat: number;
  status: AirStatus;
  delayMin: number;
};
export type UvCity = { id: string; name: string; lon: number; lat: number; uv: number };
export type AqiCity = { id: string; name: string; lon: number; lat: number; aqi: number };

// ─── Cierre nacional: SPC + temperatura máxima ───
// SPC outlook día 1: FeatureCollection con `level` por feature (geometría WGS84).
export type SpcOutlook = { updated?: number; issue?: string; features: any[] };
// Ciudad con su máxima (°F); coords/nombre curados localmente, feed trae id+tmax.
export type TmaxCity = { id: string; name: string; lon: number; lat: number; tmax: number };

// ─── Plan de escenas (fijo, ampliable) ───
export type SceneType =
  | "open"
  | "geocolor"
  | "condiciones"
  | "precip_fcst"
  | "precip_accum"
  | "radar"
  | "alerts"
  | "spc"
  | "aeropuertos"
  | "uv"
  | "aqi"
  | "tmax_today"
  | "tvar"
  | "tmax_tomorrow"
  | "outro";

export type ScenePlanItem = {
  id: string;
  type: SceneType;
  seconds: number;
};

export type ConusProps = {
  plan: ScenePlanItem[];
  mode: ThemeMode;
  sat?: SatData;
  // Satélite IR (banda 13) con paleta propia + transparencia, drapeable.
  ir?: SatView;
  // Radar como overlay drapeable (PNG transparentes MRMS con bounds).
  radar?: SatView;
  // Capa de temperatura NBM "ahora" (PNG coloreado con bounds, drapeable).
  temp?: SatView;
  // Condiciones por ciudad (cajas: símbolo + temp + viento).
  cityConds?: import("./lib/conditions").CityCond[];
  // Precip NBM próximas 24 h: bucle horario (precipFcst) y total (precipAccum).
  precipFcst?: SatView;
  precipAccum?: SatView;
  alerts?: AlertsData;
  // Categorías de vigilancia a destacar con caja (se especifica por render).
  // Si está vacío/ausente → se muestran todas las presentes.
  alertCategories?: string[];
  // Servicios CONUS: demoras de aeropuertos (FAA), índice UV (EPA) y AQI (AirNow).
  airports?: Airport[];
  uv?: UvCity[];
  aqi?: AqiCity[];
  // Cierre nacional: riesgo severo SPC + bloque de temperatura máxima.
  spc?: SpcOutlook | null;
  tmaxTodayRaster?: SatView;
  tmaxTomorrowRaster?: SatView;
  tdeltaRaster?: SatView;
  tmaxToday?: TmaxCity[];
  tmaxTomorrow?: TmaxCity[];
};
