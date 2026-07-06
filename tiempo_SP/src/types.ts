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
// SPC outlook (v2 multi-amenaza, geometría WGS84). El categórico vive en
// `categorical`; las amenazas (tornado/wind/hail/prob) solo aparecen según el día.
// `prob` en las amenazas es string crudo del SPC ("0.05"…); `sig` = área rayada.
// `population` por feature = habitantes bajo el polígono; `populationByLevel` =
// acumulado de gente bajo ≥ese nivel (las bandas categóricas son disjuntas).
export type SpcFeature = {
  type?: "Feature";
  properties?: { level?: string; prob?: string; sig?: boolean; population?: number };
  geometry?: any;
};
export type SpcOutlook = {
  updated?: number;
  day?: number;
  issue?: string;
  valid?: string;
  expire?: string;
  categorical: SpcFeature[];
  tornado?: SpcFeature[];
  wind?: SpcFeature[];
  hail?: SpcFeature[];
  prob?: SpcFeature[];
  populationByLevel?: Record<string, number>;
};
// Ciudad con su máxima (°F); coords/nombre curados localmente, feed trae id+tmax.
export type TmaxCity = { id: string; name: string; lon: number; lat: number; tmax: number };

// Población expuesta por umbral de temperatura (la calcula el pipeline NBM en
// nimbus, igual que population_by_level del SPC). Calor: gente por encima de
// 90°F/100°F; frío (futuro, escena de mínimas): por debajo de 32°F. Todos
// opcionales: la escena solo pinta los umbrales que el feed traiga.
export type TmaxPop = { heat90?: number; heat100?: number; cold32?: number };

// ─── Mapa de superficie: frentes + centros de presión (data/fronts/fronts.json) ───
// El feed es un FeatureCollection: puntos kind:"H"/"L" con presión (hPa) y líneas
// con properties.ftype (cold|warm|stationary|occluded|trough). Geometría WGS84.
export type FrontPoint = { kind: "H" | "L"; pressure?: number; lon: number; lat: number };
export type FrontLine = { ftype: string; geometry: any };
export type FrontsData = {
  updated?: number;
  issue?: string;
  valid?: string;
  points: FrontPoint[];
  lines: FrontLine[];
};

// ─── Reportes de tormenta últimas 24 h (data/reports/storm_reports.json) ───
// El feed trae `reports` (puntos con type/lat/lon) y un `summary` con los conteos
// totales por categoría. Aquí reducimos cada reporte a {cat, lon, lat}.
export type StormReportCat = "tornado" | "wind" | "hail" | "rain" | "winter";
export type StormReport = { cat: StormReportCat; lon: number; lat: number };
export type StormReportsData = {
  generated?: string;
  hoursCovered?: number;
  total: number;
  summary: { tornado: number; wind: number; hail: number; rain: number; snow: number; ice: number };
  reports: StormReport[];
};

// ─── Monitor de sequía USDM (data/drought/usdm_current.json) ───
// FeatureCollection con un polígono por nivel (properties.DM = 0..4). Pasamos el
// GeoJSON tal cual + los niveles presentes para la leyenda.
export type DroughtData = { geojson: any; levels: number[]; updated?: string };

// ─── Terremoto (data/quake/latest.json) ───
// Último sismo fuerte (M≥5.5) sobre EEUU publicado por el pipeline (origen USGS).
// Si lo hay, dispara el bloque "Última hora · Terremoto" al INICIO del vídeo.
// `timeLabel` (opcional) = hora ya formateada por el pipeline (evita líos de zona
// horaria); si falta, el frontend muestra la hora UTC de `time`.
export type Quake = {
  id?: string;
  mag: number;
  place: string;
  lon: number;
  lat: number;
  depthKm?: number;
  time?: number; // unix s del sismo
  timeLabel?: string;
  tsunami?: number; // 1 = aviso de tsunami USGS
  felt?: number; // nº de reportes "lo sentí" (USGS DYFI)
};

// ─── Plan de escenas (fijo, ampliable) ───
export type SceneType =
  | "quake_intro"
  | "quake"
  | "open"
  | "geocolor"
  | "condiciones"
  | "precip_fcst"
  | "precip_accum"
  | "radar"
  | "alerts"
  | "fronts"
  | "reports"
  | "drought"
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
  // Mapa de superficie (frentes + presión), reportes de tormenta 24 h y sequía.
  fronts?: FrontsData | null;
  reports?: StormReportsData | null;
  drought?: DroughtData | null;
  // Cierre nacional: riesgo severo SPC + bloque de temperatura máxima.
  spc?: SpcOutlook | null;
  tmaxTodayRaster?: SatView;
  tmaxTomorrowRaster?: SatView;
  tdeltaRaster?: SatView;
  tmaxToday?: TmaxCity[];
  tmaxTomorrow?: TmaxCity[];
  tmaxPopToday?: TmaxPop;
  tmaxPopTomorrow?: TmaxPop;
  // Última hora: terremoto fuerte (M≥5.5) sobre EEUU. Si está, abre el vídeo.
  quake?: Quake | null;
};
