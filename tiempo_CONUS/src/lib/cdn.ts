import type {
  SatData,
  SatView,
  SatFrame,
  RadarData,
  AlertsData,
  AlertItem,
  ScenePlanItem,
  ThemeMode,
  Airport,
  AirStatus,
  UvCity,
  AqiCity,
  SpcOutlook,
  TmaxCity,
  TmaxPop,
  Quake,
  FrontsData,
  FrontPoint,
  FrontLine,
  StormReportsData,
  StormReport,
  StormReportCat,
  DroughtData,
} from "../types";
import type { CityCond } from "./conditions";
import { skyFromConditionEs, windArrowDeg } from "./conditions";

export const CDN = "https://canalmeteo-public.sfo3.digitaloceanspaces.com";

// ─────────────────────────────────────────────────────────────
// Mapbox / encuadre
// ─────────────────────────────────────────────────────────────
export const MAPBOX_TOKEN =
  "pk.eyJ1IjoiYWxiZXJ0ZWx0aWVtcG8iLCJhIjoiY21rM2pqa29zMGd6NjNncHdlMWZ1NTNlayJ9.0d2lAZ-CmqEuoPe_h2JEHA";
export const MAPBOX_STYLE = "mapbox://styles/mapbox/dark-v11";

// Encuadre de los 48 estados contiguos (CONUS), bbox [[oeste,sur],[este,norte]].
// Cerrado entre la frontera con Canadá (~49N) y el sur de Florida (~24.5N); sin
// Caribe/Puerto Rico. Más zoom = menos océano de margen y mejor batimetría.
export const CONUS_VIEW: [[number, number], [number, number]] = [
  [-124.7, 24.5],
  [-66.9, 49.2],
];

// Padding del encuadre ÚNICO para TODAS las escenas (satélite, radar, alertas):
// misma proyección y mismo encuadre → sin saltos entre escenas. El hueco inferior
// deja sitio a las cajas de alertas y a la barra de tiempo.
export const CONUS_PAD = { top: 80, bottom: 185, left: 40, right: 40 };

// Aclara el océano del basemap (dark-v11 lo trae casi negro).
export const OCEAN = "#3d5a6e";
export function lightenWater(map: any) {
  (map.getStyle().layers || []).forEach((l: any) => {
    if (l.type === "fill" && /water/.test(l.id) && !/waterway/.test(l.id)) {
      try {
        map.setPaintProperty(l.id, "fill-color", OCEAN);
      } catch {
        /* noop */
      }
    }
  });
}

// bbox [[w,s],[e,n]] de cualquier GeoJSON (recorre coordenadas)
export function geoBounds(
  gj: any
): [[number, number], [number, number]] | null {
  let w = Infinity,
    s = Infinity,
    e = -Infinity,
    n = -Infinity;
  const scan = (c: any) => {
    if (typeof c[0] === "number" && typeof c[1] === "number") {
      w = Math.min(w, c[0]);
      e = Math.max(e, c[0]);
      s = Math.min(s, c[1]);
      n = Math.max(n, c[1]);
    } else if (Array.isArray(c)) {
      c.forEach(scan);
    }
  };
  (gj?.features || []).forEach(
    (f: any) => f?.geometry?.coordinates && scan(f.geometry.coordinates)
  );
  if (!isFinite(w)) return null;
  return [
    [w, s],
    [e, n],
  ];
}

// ─────────────────────────────────────────────────────────────
// Satélite GOES (GEOCOLOR full-disk). disco-este cubre CONUS entero.
// ─────────────────────────────────────────────────────────────
export const SAT_FD_BASE = `${CDN}/data/satellite-fd`;
export const MAX_SAT_FRAMES = 10; // límite GPU al renderizar capas raster

function decimateFrames<T>(arr: T[], max: number): T[] {
  const n = arr.length;
  if (n <= max) return arr;
  const step = (n - 1) / (max - 1);
  const out: T[] = [];
  for (let i = 0; i < max; i++) out.push(arr[Math.round(i * step)]);
  out[out.length - 1] = arr[n - 1]; // garantiza el más reciente
  return out;
}

// Comprueba (HEAD) qué frames existen y descarta 404 (el manifest puede ir por
// delante del CDN). Ante error de red transitorio conserva el frame.
async function filterExistingFrames(
  frames: SatFrame[],
  signal?: AbortSignal
): Promise<SatFrame[]> {
  if (!frames.length) return frames;
  const ok = await Promise.all(
    frames.map(async (f) => {
      try {
        const res = await fetch(f.url, { method: "HEAD", signal });
        return res.ok || res.status === 405;
      } catch {
        return true;
      }
    })
  );
  const kept = frames.filter((_, i) => ok[i]);
  return kept.length ? kept : frames;
}

export async function fetchSatelliteData(
  view: string,
  bands: string[] = ["geocolor"],
  lastN = 18,
  signal?: AbortSignal
): Promise<SatData> {
  try {
    const r = await fetch(`${SAT_FD_BASE}/${view}/manifest.json?ts=${Date.now()}`, {
      signal,
    });
    const vm = await r.json();
    const products: Record<string, SatFrame[]> = vm?.products || {};
    const out: Record<string, SatFrame[]> = {};
    for (const b of bands) {
      const sliced = (products[b] || []).slice(-lastN);
      out[b] = await filterExistingFrames(sliced, signal);
    }
    return { view, sat: vm?.sat, bounds: vm?.bounds || null, bands: out };
  } catch (e) {
    console.warn(`[conus] satélite ${view}:`, e);
    return { view, bounds: null, bands: {} };
  }
}

// ─────────────────────────────────────────────────────────────
// GOES IR banda 13 con paleta propia + transparencia (data/goes_ir).
// PNG transparentes con bounds → se drapean como el radar sobre el mapa base.
// ─────────────────────────────────────────────────────────────
export async function fetchGoesIr(
  view: string = "conus",
  signal?: AbortSignal
): Promise<SatView> {
  try {
    const r = await fetch(`${CDN}/data/goes_ir/${view}/manifest.json?ts=${Date.now()}`, {
      signal,
    });
    const m = await r.json();
    const all: SatFrame[] = (Array.isArray(m?.frames) ? m.frames : []).map((f: any) => ({
      url: f.url,
      time: f.timestamp,
    }));
    const kept = await filterExistingFrames(decimateFrames(all, MAX_SAT_FRAMES), signal);
    return {
      view: `goes_ir_${view}`,
      band: "ir",
      bounds: m?.bounds || null,
      frames: kept,
    };
  } catch (e) {
    console.warn(`[conus] goes_ir ${view}:`, e);
    return { view: `goes_ir_${view}`, band: "ir", bounds: null, frames: [] };
  }
}

// Construye una vista de una sola banda (lo que consume SatMap).
export function satViewFromBand(data: SatData | undefined, band: string): SatView {
  const bands = data?.bands || {};
  const useBand =
    (bands[band]?.length ? band : null) ||
    Object.keys(bands).find((b) => bands[b]?.length) ||
    band;
  const all = bands[useBand] || [];
  return {
    view: data?.view || "disco-este",
    band: useBand,
    sat: data?.sat,
    bounds: data?.bounds || null,
    frames: decimateFrames(all, MAX_SAT_FRAMES),
  };
}

// ─────────────────────────────────────────────────────────────
// Radar CONUS (MRMS). Frames JPG ya compuestos con basemap (16:9).
// ─────────────────────────────────────────────────────────────
export const RADAR_MANIFEST = `${CDN}/data/radar_conus/manifest.json`;
export const RADAR_SPAN_MINUTES = 180; // las últimas 3 horas

// ─────────────────────────────────────────────────────────────
// Animación en bucle (satélite IR / radar)
// ─────────────────────────────────────────────────────────────
// Segundos que tarda UNA pasada completa por todos los frames. Desacopla la
// velocidad de la animación de la duración de la escena: con escenas de 8 s y un
// bucle de ~2,8 s, el loop da ~3 vueltas en vez de una sola pasada lentísima.
export const LOOP_SECONDS = 2.8;

// Índice del frame a mostrar para una animación que se REPITE cada
// `secondsPerLoop`. Recorre 0…n-1 y vuelve a empezar; el frame más reciente
// (n-1) queda al final de cada vuelta.
export function loopFrameIndex(
  frame: number,
  fps: number,
  n: number,
  secondsPerLoop: number = LOOP_SECONDS
): number {
  if (n <= 1) return 0;
  const loopFrames = Math.max(1, Math.round(secondsPerLoop * fps));
  const t = (frame % loopFrames) / loopFrames; // 0..1
  return Math.min(n - 1, Math.floor(t * n));
}

// Radar MRMS TRANSPARENTE (data/mrms): PNG RGBA con bounds, para drapear sobre el
// mapa nuevo igual que el satélite (mismo método). Sustituye a los JPG compuestos
// con basemap antiguo de radar_conus.
export const MRMS_MANIFEST = `${CDN}/data/mrms/manifest.json`;
export const MAX_RADAR_FRAMES = 10; // límite GPU (capas raster)

export async function fetchRadarOverlay(signal?: AbortSignal): Promise<SatView> {
  try {
    const r = await fetch(`${MRMS_MANIFEST}?ts=${Date.now()}`, { signal });
    const m = await r.json();
    const all: SatFrame[] = (Array.isArray(m?.frames) ? m.frames : []).map((f: any) => ({
      url: f.url,
      time: f.timestamp,
    }));
    // HEAD-check: el pipeline MRMS rota frames y el manifest puede ir por delante
    // del CDN (404). Descartamos los que ya no existen para no romper el render.
    const kept = await filterExistingFrames(decimateFrames(all, MAX_RADAR_FRAMES), signal);
    return {
      view: "mrms",
      band: "refl",
      bounds: m?.bounds || null,
      frames: kept,
    };
  } catch (e) {
    console.warn("[conus] radar mrms:", e);
    return { view: "mrms", band: "refl", bounds: null, frames: [] };
  }
}

export async function fetchRadar(signal?: AbortSignal): Promise<RadarData | undefined> {
  try {
    const r = await fetch(`${RADAR_MANIFEST}?ts=${Date.now()}`, { signal });
    const m = await r.json();
    const mapa = (m?.mapas || []).find((x: any) => x?.id === "radar_conus") || m?.mapas?.[0];
    const frames: string[] = Array.isArray(mapa?.frames) ? mapa.frames : [];
    if (!frames.length) return undefined;
    return { frames, updated: mapa?.actualizado, spanMinutes: RADAR_SPAN_MINUTES };
  } catch (e) {
    console.warn("[conus] radar:", e);
    return undefined;
  }
}

// ─────────────────────────────────────────────────────────────
// NBM temperatura 2 m (data/nbm/temp/conus). PNG RGBA coloreado con bounds, se
// drapea como el satélite/radar. Una sola imagen ("ahora").
// ─────────────────────────────────────────────────────────────
export const NBM_TEMP_MANIFEST = `${CDN}/data/nbm/temp/conus/manifest.json`;

export async function fetchNbmTemp(signal?: AbortSignal): Promise<SatView> {
  try {
    const r = await fetch(`${NBM_TEMP_MANIFEST}?ts=${Date.now()}`, { signal });
    const m = await r.json();
    const all: SatFrame[] = (Array.isArray(m?.frames) ? m.frames : []).map((f: any) => ({
      url: f.url,
      time: f.timestamp,
    }));
    const kept = await filterExistingFrames(all, signal);
    return { view: "nbm_temp", band: "temp", bounds: m?.bounds || null, frames: kept };
  } catch (e) {
    console.warn("[conus] nbm temp:", e);
    return { view: "nbm_temp", band: "temp", bounds: null, frames: [] };
  }
}

// ─────────────────────────────────────────────────────────────
// NBM precipitación a futuro (data/nbm/precip_fcst|precip_accum). PNG RGBA con
// bounds (lluvia/nieve/hielo), drapeable. precip_fcst = bucle horario 24 h;
// precip_accum = total 24 h (1 frame).
// ─────────────────────────────────────────────────────────────
async function fetchNbmRaster(path: string, view: string, signal?: AbortSignal): Promise<SatView> {
  try {
    const r = await fetch(`${CDN}/${path}/manifest.json?ts=${Date.now()}`, { signal });
    const m = await r.json();
    const all: SatFrame[] = (Array.isArray(m?.frames) ? m.frames : []).map((f: any) => ({
      url: f.url,
      time: f.timestamp,
    }));
    const kept = await filterExistingFrames(all, signal);
    return { view, band: "precip", bounds: m?.bounds || null, frames: kept };
  } catch (e) {
    console.warn(`[conus] ${view}:`, e);
    return { view, band: "precip", bounds: null, frames: [] };
  }
}

// "Radar a futuro" = reflectividad simulada HRRR (REFC) coloreada por tipo.
export const fetchHrrrRadarForecast = (signal?: AbortSignal) =>
  fetchNbmRaster("data/hrrr/radar_fcst/conus", "hrrr_radar_fcst", signal);
export const fetchNbmPrecipAccum = (signal?: AbortSignal) =>
  fetchNbmRaster("data/nbm/precip_accum/conus", "nbm_precip_accum", signal);

// ─────────────────────────────────────────────────────────────
// Condiciones por ciudad (data/cities/weather.json) → cajas de la escena.
// El feed trae temp °F, viento mph/dirección, condición en español. Aquí curamos
// un subconjunto bien repartido y le adjuntamos coordenadas (el feed no las trae).
// La clave es "Ciudad|Estado" tal como las publica weather-api.php (en inglés).
// ─────────────────────────────────────────────────────────────
export const CITIES_WEATHER_URL = `${CDN}/data/cities/weather.json`;

const CONDITION_CITIES: { key: string; name: string; lon: number; lat: number }[] = [
  { key: "New York|New York", name: "Nueva York", lon: -74.01, lat: 40.71 },
  { key: "Los Angeles|California", name: "Los Ángeles", lon: -118.24, lat: 34.05 },
  { key: "Chicago|Illinois", name: "Chicago", lon: -87.63, lat: 41.88 },
  { key: "Houston|Texas", name: "Houston", lon: -95.37, lat: 29.76 },
  { key: "Miami|Florida", name: "Miami", lon: -80.19, lat: 25.76 },
  { key: "Dallas|Texas", name: "Dallas", lon: -96.8, lat: 32.78 },
  { key: "Atlanta|Georgia", name: "Atlanta", lon: -84.39, lat: 33.75 },
  { key: "Phoenix|Arizona", name: "Phoenix", lon: -112.07, lat: 33.45 },
  { key: "Denver|Colorado", name: "Denver", lon: -104.99, lat: 39.74 },
  { key: "Salt Lake City|Utah", name: "Salt Lake City", lon: -111.89, lat: 40.76 },
  { key: "Oklahoma City|Oklahoma", name: "Oklahoma City", lon: -97.52, lat: 35.47 },
  { key: "Columbus|Ohio", name: "Columbus", lon: -82.99, lat: 39.96 },
  { key: "Las Vegas|Nevada", name: "Las Vegas", lon: -115.14, lat: 36.17 },
  { key: "Boise|Idaho", name: "Boise", lon: -116.2, lat: 43.62 },
  { key: "Bismarck|North Dakota", name: "Bismarck", lon: -100.78, lat: 46.81 },
  { key: "Saint Paul|Minnesota", name: "St. Paul", lon: -93.09, lat: 44.94 },
  { key: "Sacramento|California", name: "Sacramento", lon: -121.49, lat: 38.58 },
  // Seattle no está en weather.json (no es capital); usamos los datos de Olympia
  // (WA, ~50 km) con la etiqueta y coordenadas de Seattle.
  { key: "Olympia|Washington", name: "Seattle", lon: -122.33, lat: 47.61 },
];

export async function fetchCityConditions(signal?: AbortSignal): Promise<CityCond[]> {
  try {
    const r = await fetch(`${CITIES_WEATHER_URL}?ts=${Date.now()}`, { signal });
    const d = await r.json();
    const rows: any[] = Array.isArray(d?.data) ? d.data : [];
    const byKey = new Map<string, any>();
    for (const c of rows) byKey.set(`${c.city}|${c.state}`, c);

    const out: CityCond[] = [];
    for (const cc of CONDITION_CITIES) {
      const w = byKey.get(cc.key);
      if (!w || typeof w.temp !== "number") continue;
      out.push({
        name: cc.name,
        lon: cc.lon,
        lat: cc.lat,
        tempF: w.temp,
        sky: skyFromConditionEs(w.conditionEs, !!w.isNight),
        windMph: typeof w.windSpeed === "number" ? w.windSpeed : 0,
        windDeg: windArrowDeg(w.windDir),
      });
    }
    return out;
  } catch (e) {
    console.warn("[conus] cities weather:", e);
    return [];
  }
}

// ─────────────────────────────────────────────────────────────
// Servicios CONUS: demoras de aeropuertos (FAA), índice UV (EPA) y AQI (AirNow).
// Igual que las condiciones: el feed solo trae VALORES indexados por id; aquí
// curamos coordenadas + nombre en español. Los ids que no estén en el catálogo se
// descartan (el catálogo decide qué se dibuja y cómo).
// ─────────────────────────────────────────────────────────────
export const AIRPORTS_URL = `${CDN}/data/airports/delays.json`;
export const UV_URL = `${CDN}/data/uv/cities.json`;
export const AQI_URL = `${CDN}/data/aqi/cities.json`;

// Aeropuertos: clave = IATA (tal como llega el feed FAA).
const AIRPORT_CATALOG: { iata: string; city: string; lon: number; lat: number }[] = [
  { iata: "JFK", city: "Nueva York", lon: -73.78, lat: 40.64 },
  { iata: "EWR", city: "Newark", lon: -74.17, lat: 40.69 },
  // LGA omitido: solapa con JFK/EWR en el área metropolitana de NY (descongestión).
  { iata: "BOS", city: "Boston", lon: -71.01, lat: 42.37 },
  { iata: "PHL", city: "Filadelfia", lon: -75.24, lat: 39.87 },
  { iata: "BWI", city: "Baltimore", lon: -76.67, lat: 39.18 },
  { iata: "ATL", city: "Atlanta", lon: -84.43, lat: 33.64 },
  { iata: "CLT", city: "Charlotte", lon: -80.94, lat: 35.21 },
  { iata: "MIA", city: "Miami", lon: -80.29, lat: 25.79 },
  { iata: "MCO", city: "Orlando", lon: -81.31, lat: 28.43 },
  { iata: "TPA", city: "Tampa", lon: -82.53, lat: 27.98 },
  { iata: "ORD", city: "Chicago", lon: -87.9, lat: 41.97 },
  { iata: "DTW", city: "Detroit", lon: -83.35, lat: 42.21 },
  { iata: "MSP", city: "Mineápolis", lon: -93.22, lat: 44.88 },
  { iata: "DFW", city: "Dallas", lon: -97.04, lat: 32.9 },
  { iata: "IAH", city: "Houston", lon: -95.34, lat: 29.99 },
  { iata: "DEN", city: "Denver", lon: -104.67, lat: 39.86 },
  { iata: "SLC", city: "Salt Lake City", lon: -111.98, lat: 40.79 },
  { iata: "PHX", city: "Phoenix", lon: -112.01, lat: 33.43 },
  { iata: "LAS", city: "Las Vegas", lon: -115.15, lat: 36.08 },
  { iata: "LAX", city: "Los Ángeles", lon: -118.41, lat: 33.94 },
  { iata: "SAN", city: "San Diego", lon: -117.19, lat: 32.73 },
  { iata: "SFO", city: "San Francisco", lon: -122.38, lat: 37.62 },
  { iata: "SEA", city: "Seattle", lon: -122.31, lat: 47.45 },
  { iata: "PDX", city: "Portland", lon: -122.6, lat: 45.59 },
];

export async function fetchAirports(signal?: AbortSignal): Promise<Airport[]> {
  try {
    const r = await fetch(`${AIRPORTS_URL}?ts=${Date.now()}`, { signal });
    const d = await r.json();
    const rows: any[] = Array.isArray(d?.airports) ? d.airports : [];
    const byIata = new Map<string, any>();
    for (const a of rows) byIata.set(a.iata, a);

    const out: Airport[] = [];
    for (const cat of AIRPORT_CATALOG) {
      const a = byIata.get(cat.iata);
      if (!a) continue;
      const status: AirStatus =
        a.status === "closed" || a.status === "delay" || a.status === "open" ? a.status : "open";
      out.push({
        id: cat.iata,
        iata: cat.iata,
        city: cat.city,
        lon: cat.lon,
        lat: cat.lat,
        status,
        delayMin: typeof a.delayMin === "number" ? a.delayMin : 0,
      });
    }
    return out;
  } catch (e) {
    console.warn("[conus] aeropuertos:", e);
    return [];
  }
}

// Ciudades para UV y AQI (mismo catálogo: id → nombre en español + coords).
const SERVICE_CITIES: { id: string; name: string; lon: number; lat: number }[] = [
  { id: "MIA", name: "Miami", lon: -80.19, lat: 25.76 },
  { id: "PHX", name: "Phoenix", lon: -112.07, lat: 33.45 },
  { id: "LAX", name: "Los Ángeles", lon: -118.24, lat: 34.05 },
  { id: "HOU", name: "Houston", lon: -95.37, lat: 29.76 },
  { id: "DAL", name: "Dallas", lon: -96.8, lat: 32.78 },
  { id: "ATL", name: "Atlanta", lon: -84.39, lat: 33.75 },
  { id: "DEN", name: "Denver", lon: -104.99, lat: 39.74 },
  { id: "NYC", name: "Nueva York", lon: -74.01, lat: 40.71 },
  { id: "CHI", name: "Chicago", lon: -87.63, lat: 41.88 },
  { id: "SEA", name: "Seattle", lon: -122.33, lat: 47.61 },
  { id: "SFO", name: "San Francisco", lon: -122.42, lat: 37.77 },
  { id: "MSP", name: "Mineápolis", lon: -93.27, lat: 44.98 },
  { id: "SLC", name: "Salt Lake City", lon: -111.89, lat: 40.76 },
  { id: "ABQ", name: "Albuquerque", lon: -106.65, lat: 35.08 },
  { id: "MCO", name: "Orlando", lon: -81.38, lat: 28.54 },
  { id: "BIS", name: "Bismarck", lon: -100.78, lat: 46.81 },
  { id: "KC", name: "Kansas City", lon: -94.58, lat: 39.1 },
  // Oklahoma City y Omaha retiradas del mapa CONUS (descongestión del centro);
  // San Luis (STL) cubre esa zona.
  { id: "STL", name: "San Luis", lon: -90.2, lat: 38.63 },
  { id: "MEM", name: "Memphis", lon: -90.05, lat: 35.15 },
  { id: "BNA", name: "Nashville", lon: -86.78, lat: 36.16 },
  { id: "LAS", name: "Las Vegas", lon: -115.14, lat: 36.17 },
  // Sacramento retirada del mapa AQI (descongestión de la costa oeste).
  { id: "PDX", name: "Portland", lon: -122.68, lat: 45.52 },
  { id: "BOS", name: "Boston", lon: -71.06, lat: 42.36 },
];

export async function fetchUv(signal?: AbortSignal): Promise<UvCity[]> {
  try {
    const r = await fetch(`${UV_URL}?ts=${Date.now()}`, { signal });
    const d = await r.json();
    const rows: any[] = Array.isArray(d?.cities) ? d.cities : [];
    const byId = new Map<string, any>();
    for (const c of rows) byId.set(c.id, c);

    const out: UvCity[] = [];
    for (const cat of SERVICE_CITIES) {
      const c = byId.get(cat.id);
      if (!c || typeof c.uv !== "number") continue;
      out.push({ id: cat.id, name: cat.name, lon: cat.lon, lat: cat.lat, uv: c.uv });
    }
    return out;
  } catch (e) {
    console.warn("[conus] uv:", e);
    return [];
  }
}

export async function fetchAqi(signal?: AbortSignal): Promise<AqiCity[]> {
  try {
    const r = await fetch(`${AQI_URL}?ts=${Date.now()}`, { signal });
    const d = await r.json();
    const rows: any[] = Array.isArray(d?.cities) ? d.cities : [];
    const byId = new Map<string, any>();
    for (const c of rows) byId.set(c.id, c);

    const out: AqiCity[] = [];
    for (const cat of SERVICE_CITIES) {
      const c = byId.get(cat.id);
      if (!c || typeof c.aqi !== "number") continue;
      out.push({ id: cat.id, name: cat.name, lon: cat.lon, lat: cat.lat, aqi: c.aqi });
    }
    return out;
  } catch (e) {
    console.warn("[conus] aqi:", e);
    return [];
  }
}

// ─────────────────────────────────────────────────────────────
// Cierre nacional: riesgo severo SPC (GeoJSON) + temperatura máxima (ráster NBM
// + valores por ciudad). Igual que el resto: el feed trae valores/geometría; las
// coords/nombres de ciudad se curan aquí.
// ─────────────────────────────────────────────────────────────
export const SPC_URL = `${CDN}/data/spc/outlook_day1.json`;
export const TMAX_CITIES_URL = `${CDN}/data/tmax/cities.json`;

// SPC outlook día 1 (v2 multi-amenaza). null si el feed no existe (→ no se muestra
// la escena); categorical:[] es válido y significa "sin riesgo significativo".
// El categórico está en `.categorical` (v2); aceptamos `.features` por si quedara
// algún feed viejo (v1). Solo iteramos las amenazas que existan ese día.
export async function fetchSpcOutlook(signal?: AbortSignal): Promise<SpcOutlook | null> {
  try {
    const r = await fetch(`${SPC_URL}?ts=${Date.now()}`, { signal });
    if (!r.ok) return null;
    const d = await r.json();
    const arr = (k: string) => (Array.isArray(d?.[k]) ? d[k] : undefined);
    const categorical = arr("categorical") ?? arr("features") ?? [];
    return {
      updated: d?.updated,
      day: d?.day,
      issue: d?.issue,
      valid: d?.valid,
      expire: d?.expire,
      categorical,
      tornado: arr("tornado"),
      wind: arr("wind"),
      hail: arr("hail"),
      prob: arr("prob"),
      populationByLevel:
        d?.population_by_level && typeof d.population_by_level === "object"
          ? d.population_by_level
          : undefined,
    };
  } catch (e) {
    console.warn("[conus] spc:", e);
    return null;
  }
}

// Rásteres de máxima (hoy/mañana) y de variación (mañana−hoy), mismo método que
// el ráster de temperatura "ahora".
export const fetchTmaxTodayRaster = (signal?: AbortSignal) =>
  fetchNbmRaster("data/nbm/tmax/today", "nbm_tmax_today", signal);
export const fetchTmaxTomorrowRaster = (signal?: AbortSignal) =>
  fetchNbmRaster("data/nbm/tmax/tomorrow", "nbm_tmax_tomorrow", signal);
export const fetchTdeltaRaster = (signal?: AbortSignal) =>
  fetchNbmRaster("data/nbm/tdelta/tomorrow", "nbm_tdelta", signal);

const TMAX_CITY_CATALOG: { id: string; name: string; lon: number; lat: number }[] = [
  { id: "SEA", name: "Seattle", lon: -122.33, lat: 47.61 },
  { id: "PDX", name: "Portland", lon: -122.68, lat: 45.52 },
  { id: "SFO", name: "San Francisco", lon: -122.42, lat: 37.77 },
  { id: "LAX", name: "Los Ángeles", lon: -118.24, lat: 34.05 },
  { id: "LAS", name: "Las Vegas", lon: -115.14, lat: 36.17 },
  { id: "PHX", name: "Phoenix", lon: -112.07, lat: 33.45 },
  { id: "SLC", name: "Salt Lake City", lon: -111.89, lat: 40.76 },
  { id: "DEN", name: "Denver", lon: -104.99, lat: 39.74 },
  { id: "ABQ", name: "Albuquerque", lon: -106.65, lat: 35.08 },
  { id: "BIS", name: "Bismarck", lon: -100.78, lat: 46.81 },
  { id: "OKC", name: "Oklahoma City", lon: -97.52, lat: 35.47 },
  { id: "DAL", name: "Dallas", lon: -96.8, lat: 32.78 },
  { id: "HOU", name: "Houston", lon: -95.37, lat: 29.76 },
  { id: "KC", name: "Kansas City", lon: -94.58, lat: 39.1 },
  { id: "MSP", name: "Mineápolis", lon: -93.27, lat: 44.98 },
  { id: "CHI", name: "Chicago", lon: -87.63, lat: 41.88 },
  { id: "ATL", name: "Atlanta", lon: -84.39, lat: 33.75 },
  { id: "MIA", name: "Miami", lon: -80.19, lat: 25.76 },
  { id: "DC", name: "Washington", lon: -77.04, lat: 38.91 },
  { id: "NYC", name: "Nueva York", lon: -74.01, lat: 40.71 },
  { id: "BOS", name: "Boston", lon: -71.06, lat: 42.36 },
  // MSY/CLE/RDU (y DC, arriba) publicadas por nimbus desde 2026-07-06
  // (nbm_tmax_pipeline.py). BOI sigue SIN publicarse: no se dibuja hasta que
  // el pipeline la añada a data/tmax/cities.json con este mismo id.
  { id: "BOI", name: "Boise", lon: -116.2, lat: 43.62 },
  { id: "MSY", name: "New Orleans", lon: -90.07, lat: 29.95 },
  { id: "CLE", name: "Cleveland", lon: -81.69, lat: 41.5 },
  { id: "RDU", name: "Raleigh", lon: -78.64, lat: 35.78 },
];

// TEST: poner a true para VER todas las ciudades del catálogo en los 3 mapas de
// temperatura sin esperar a que el pipeline de nimbus las publique. Rellena con
// valores de MUESTRA las ciudades del catálogo que el feed no trae (p. ej.
// Cleveland/Raleigh/New Orleans/Boise/Washington) y simula la máxima de HOY en
// runs de tarde. PONER A false en producción (entonces solo se dibujan las
// ciudades que vengan en data/tmax/cities.json).
export const TMAX_TEST = false;
const SAMPLE_TMAX: Record<string, number> = {
  SEA: 74, PDX: 78, SFO: 68, LAX: 84, LAS: 104, PHX: 109, SLC: 92, DEN: 88,
  ABQ: 95, BIS: 80, OKC: 96, DAL: 99, HOU: 95, KC: 90, MSP: 82, CHI: 84,
  ATL: 90, MIA: 91, DC: 88, NYC: 86, BOS: 79, BOI: 94, MSY: 93, CLE: 84, RDU: 91,
};

// Valores de máxima por ciudad para hoy y mañana. En runs de tarde "today" puede
// venir vacío/ausente (el NBM ya no emite la máxima de hoy) → today: [].
export async function fetchTmaxCities(
  signal?: AbortSignal
): Promise<{ today: TmaxCity[]; tomorrow: TmaxCity[]; popToday?: TmaxPop; popTomorrow?: TmaxPop }> {
  const merge = (rows: any[]): TmaxCity[] => {
    const by = new Map<string, any>();
    for (const x of Array.isArray(rows) ? rows : []) by.set(x.id, x);
    const out: TmaxCity[] = [];
    for (const cat of TMAX_CITY_CATALOG) {
      const v = by.get(cat.id);
      if (!v || typeof v.tmax !== "number") continue;
      out.push({ ...cat, tmax: v.tmax });
    }
    return out;
  };
  // Población expuesta por umbral (opcional). El feed puede traerla en
  // `population.{today,tomorrow}` o, si lo prefiere el pipeline, embebida en cada
  // día como `{day:[...], pop:{heat90,heat100,cold32}}`. Aceptamos ambas.
  const pop = (o: any): TmaxPop | undefined => {
    if (!o || typeof o !== "object") return undefined;
    const num = (x: any) => (typeof x === "number" && x > 0 ? x : undefined);
    const p: TmaxPop = { heat90: num(o.heat90), heat100: num(o.heat100), cold32: num(o.cold32) };
    return p.heat90 || p.heat100 || p.cold32 ? p : undefined;
  };
  let today: TmaxCity[] = [];
  let tomorrow: TmaxCity[] = [];
  let popToday: TmaxPop | undefined;
  let popTomorrow: TmaxPop | undefined;
  try {
    const r = await fetch(`${TMAX_CITIES_URL}?ts=${Date.now()}`, { signal });
    if (r.ok) {
      const d = await r.json();
      today = merge(d?.today);
      tomorrow = merge(d?.tomorrow);
      popToday = pop(d?.population?.today);
      popTomorrow = pop(d?.population?.tomorrow);
    }
  } catch (e) {
    console.warn("[conus] tmax cities:", e);
  }
  if (TMAX_TEST) {
    const fillMissing = (list: TmaxCity[]): TmaxCity[] => {
      const have = new Set(list.map((c) => c.id));
      const out = [...list];
      for (const cat of TMAX_CITY_CATALOG) {
        if (have.has(cat.id) || SAMPLE_TMAX[cat.id] == null) continue;
        out.push({ ...cat, tmax: SAMPLE_TMAX[cat.id] });
      }
      return out;
    };
    tomorrow = fillMissing(tomorrow);
    // Run de tarde: "today" vacío → lo simulamos a partir de mañana (−2 °F) para
    // que las escenas de máxima HOY y variación también se vean en el test.
    today = today.length ? fillMissing(today) : tomorrow.map((c) => ({ ...c, tmax: c.tmax - 2 }));
  }
  return { today, tomorrow, popToday, popTomorrow };
}

// ─────────────────────────────────────────────────────────────
// Mapa de superficie: frentes + centros de presión (data/fronts/fronts.json).
// FeatureCollection: puntos kind:"H"/"L" (presión hPa) + líneas con ftype
// (cold|warm|stationary|occluded|trough). Geometría WGS84. null si no hay feed.
// ─────────────────────────────────────────────────────────────
export const FRONTS_URL = `${CDN}/data/fronts/fronts.json`;

export async function fetchFronts(signal?: AbortSignal): Promise<FrontsData | null> {
  try {
    const r = await fetch(`${FRONTS_URL}?ts=${Date.now()}`, { signal });
    if (!r.ok) return null;
    const d = await r.json();
    const feats: any[] = Array.isArray(d?.features) ? d.features : [];
    const points: FrontPoint[] = [];
    const lines: FrontLine[] = [];
    for (const f of feats) {
      const g = f?.geometry;
      const p = f?.properties || {};
      if (g?.type === "Point" && (p.kind === "H" || p.kind === "L")) {
        const c = g.coordinates;
        points.push({ kind: p.kind, pressure: p.pressure, lon: c[0], lat: c[1] });
      } else if (g?.type === "LineString" || g?.type === "MultiLineString") {
        lines.push({ ftype: String(p.ftype || "trough").toLowerCase(), geometry: g });
      }
    }
    return { updated: d?.updated, issue: d?.issue, valid: d?.valid, points, lines };
  } catch (e) {
    console.warn("[conus] fronts:", e);
    return null;
  }
}

// ─────────────────────────────────────────────────────────────
// Reportes de tormenta últimas 24 h (data/reports/storm_reports.json).
// Reducimos cada reporte a {cat, lon, lat}; el `summary` trae los conteos totales.
// ─────────────────────────────────────────────────────────────
export const REPORTS_URL = `${CDN}/data/reports/storm_reports.json`;

function reportCat(type?: string): StormReportCat {
  const t = (type || "").toUpperCase();
  if (/TORNADO|FUNNEL|WATERSPOUT/.test(t)) return "tornado";
  if (/HAIL/.test(t)) return "hail";
  if (/SNOW|ICE|FREEZ|SLEET|BLIZZARD|WINTER/.test(t)) return "winter";
  // El summary del feed no separa "flood": lo contamos como lluvia/agua.
  if (/FLOOD|RAIN/.test(t)) return "rain";
  return "wind";
}

export async function fetchStormReports(signal?: AbortSignal): Promise<StormReportsData | null> {
  try {
    const r = await fetch(`${REPORTS_URL}?ts=${Date.now()}`, { signal });
    if (!r.ok) return null;
    const d = await r.json();
    const rows: any[] = Array.isArray(d?.reports) ? d.reports : [];
    const reports: StormReport[] = [];
    for (const x of rows) {
      if (typeof x?.lat !== "number" || typeof x?.lon !== "number") continue;
      reports.push({ cat: reportCat(x.type), lon: x.lon, lat: x.lat });
    }
    const s = d?.summary || {};
    return {
      generated: d?.generated,
      hoursCovered: d?.hours_covered,
      total: typeof d?.total_reports === "number" ? d.total_reports : reports.length,
      summary: {
        tornado: s.tornado || 0,
        wind: s.wind || 0,
        hail: s.hail || 0,
        rain: s.rain || 0,
        snow: s.snow || 0,
        ice: s.ice || 0,
      },
      reports,
    };
  } catch (e) {
    console.warn("[conus] storm reports:", e);
    return null;
  }
}

// ─────────────────────────────────────────────────────────────
// Monitor de sequía USDM (data/drought/usdm_current.json). FeatureCollection con
// un polígono por nivel (properties.DM = 0..4). Pasamos el GeoJSON tal cual.
// ─────────────────────────────────────────────────────────────
export const DROUGHT_URL = `${CDN}/data/drought/usdm_current.json`;

export async function fetchDrought(signal?: AbortSignal): Promise<DroughtData | null> {
  try {
    const r = await fetch(`${DROUGHT_URL}?ts=${Date.now()}`, { signal });
    if (!r.ok) return null;
    const d = await r.json();
    const feats: any[] = Array.isArray(d?.features) ? d.features : [];
    if (!feats.length) return null;
    const levels = Array.from(
      new Set(
        feats
          .map((f) => Number(f?.properties?.DM))
          .filter((n) => Number.isFinite(n))
      )
    ).sort((a, b) => a - b);
    return { geojson: { type: "FeatureCollection", features: feats }, levels, updated: d?.updated };
  } catch (e) {
    console.warn("[conus] drought:", e);
    return null;
  }
}

// ─────────────────────────────────────────────────────────────
// Alertas NWS — nos quedamos SOLO con las vigilancias (watches).
// ─────────────────────────────────────────────────────────────
export const ALERTS_URL = `${CDN}/data/alertas/alertas_nws.json`;

// ¿Es vigilancia (watch)? El feed usa el evento en inglés ("… Watch") y la
// traducción ("Vigilancia de …"). Filtramos por ambas para robustez.
export function isWatch(evento?: string, eventoEs?: string): boolean {
  return /watch/i.test(evento || "") || /vigilancia/i.test(eventoEs || "");
}

export async function fetchAlerts(signal?: AbortSignal): Promise<AlertsData | undefined> {
  try {
    const r = await fetch(`${ALERTS_URL}?ts=${Date.now()}`, { signal });
    const d = await r.json();
    // Mostramos TODAS las alertas activas (avisos/warnings + vigilancias/watches).
    // Antes filtrábamos solo watches y se perdían los avisos de inundación/calor.
    const all: AlertItem[] = Array.isArray(d?.alertas) ? d.alertas : [];

    const fc = d?.geojson;
    const geojson: any = fc?.features
      ? { type: "FeatureCollection", features: fc.features }
      : undefined;

    return { timestamp: d?.timestamp, conteos: d?.conteos, watches: all, geojson };
  } catch (e) {
    console.warn("[conus] alertas:", e);
    return undefined;
  }
}

// Última hora: terremoto fuerte sobre EEUU (data/quake/latest.json). El pipeline
// (origen USGS) ya filtra por magnitud, región y recencia; aquí solo validamos y
// reforzamos el umbral M≥5.5. null = no hay sismo que abra el vídeo. Acepta el
// objeto envuelto en {quake:{…}} o suelto.
export const QUAKE_URL = `${CDN}/data/quake/latest.json`;

// TEST: poner a true para VER el bloque de terremoto sin esperar al feed de
// nimbus. Si el CDN no tiene fichero, consulta USGS directamente PERO aplicando
// el MISMO filtro de producción: M≥5.5, dentro del bbox CONUS y en las últimas 6 h.
// Así solo abre el vídeo un sismo realmente cualificado (no cualquier microsismo).
export const QUAKE_TEST = true;
const USGS_DAY_URL =
  "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson";
// bbox de los 48 estados contiguos para el filtro de terremotos (excluye
// Alaska/Hawái/PR). Coincide con el contrato del pipeline de nimbus.
const CONUS_QUAKE_BBOX = { west: -125, east: -66, south: 24, north: 50 };
// Ventana de recencia: solo sismos de las últimas 6 h.
const QUAKE_WINDOW_MS = 6 * 60 * 60 * 1000;

export async function fetchQuake(signal?: AbortSignal): Promise<Quake | null> {
  // 1) Feed de producción (nimbus → CDN).
  try {
    const r = await fetch(`${QUAKE_URL}?ts=${Date.now()}`, { signal });
    if (r.ok) {
      const d = await r.json();
      const q = d?.quake ?? d;
      // Recencia también aquí: si nimbus publica un sismo y el pipeline muere,
      // el mismo fichero abriría todos los vídeos durante días. `time` va en
      // segundos (contrato del pipeline); sin `time` no podemos validar → fuera.
      const freshEnough =
        typeof q?.time === "number" && Date.now() - q.time * 1000 <= QUAKE_WINDOW_MS;
      if (q && !freshEnough && typeof q.mag === "number") {
        console.warn("[conus] quake (cdn): descartado por antigüedad o sin time");
      }
      if (
        q &&
        freshEnough &&
        typeof q.mag === "number" &&
        typeof q.lon === "number" &&
        typeof q.lat === "number" &&
        q.mag >= 5.5
      ) {
        return {
          id: q.id,
          mag: q.mag,
          place: typeof q.place === "string" ? q.place : "Estados Unidos",
          lon: q.lon,
          lat: q.lat,
          depthKm: typeof q.depthKm === "number" ? q.depthKm : undefined,
          time: typeof q.time === "number" ? q.time : undefined,
          timeLabel: typeof q.timeLabel === "string" ? q.timeLabel : undefined,
          tsunami: q.tsunami ? 1 : 0,
          felt: typeof q.felt === "number" ? q.felt : undefined,
        };
      }
    }
  } catch (e) {
    console.warn("[conus] quake (cdn):", e);
  }
  // 2) Fallback de TEST: USGS directo, con el filtro de producción (M≥5.5, bbox
  // CONUS, últimas 6 h). El más fuerte de los que cualifican.
  if (QUAKE_TEST) {
    try {
      const r = await fetch(USGS_DAY_URL, { signal });
      if (!r.ok) return null;
      const d = await r.json();
      const fs: any[] = Array.isArray(d?.features) ? d.features : [];
      const now = Date.now();
      const bb = CONUS_QUAKE_BBOX;
      let best: any = null;
      for (const f of fs) {
        const m = f?.properties?.mag;
        const t = f?.properties?.time;
        const c = f?.geometry?.coordinates;
        if (typeof m !== "number" || !Array.isArray(c)) continue;
        if (m < 5.5) continue; // solo sismos fuertes
        const lon = c[0];
        const lat = c[1];
        if (lon < bb.west || lon > bb.east || lat < bb.south || lat > bb.north) continue; // solo CONUS
        if (typeof t === "number" && now - t > QUAKE_WINDOW_MS) continue; // últimas 6 h
        if (!best || m > best.properties.mag) best = f;
      }
      if (!best) return null;
      const p = best.properties;
      const c = best.geometry.coordinates;
      console.warn(`[conus] quake TEST (USGS): M${p.mag} ${p.place}`);
      return {
        id: best.id,
        mag: p.mag,
        place: typeof p.place === "string" ? p.place : "—",
        lon: c[0],
        lat: c[1],
        depthKm: typeof c[2] === "number" ? c[2] : undefined,
        time: typeof p.time === "number" ? Math.round(p.time / 1000) : undefined,
        tsunami: p.tsunami ? 1 : 0,
        felt: typeof p.felt === "number" ? p.felt : undefined,
      };
    } catch (e) {
      console.warn("[conus] quake (usgs test):", e);
      return null;
    }
  }
  return null;
}

// Modo cromático: Modo Rojo si hay tornado o tiempo severo (conteos del feed).
// (Los huracanes viven en otro feed; se podrá añadir esa señal más adelante.)
export function computeMode(alerts?: AlertsData): ThemeMode {
  const c = alerts?.conteos;
  if (!c) return "normal";
  if ((c.tornado || 0) > 0 || (c.tormenta || 0) > 0) return "alert";
  return "normal";
}

// ─────────────────────────────────────────────────────────────
// Plan de escenas (fijo por ahora; ampliable con más gráficas)
// ─────────────────────────────────────────────────────────────
export const SCENE_SECONDS = {
  quake_intro: 3, // cartel "Última hora · Terremoto" (solo si hay sismo M≥5.5)
  quake: 8, // mapa del epicentro + magnitud/lugar/profundidad
  open: 3.5,
  geocolor: 8, // satélite IR CONUS + ciudades (últimas 6 h)
  radar: 8, // radar últimas 6 h
  fronts: 8, // mapa de superficie: frentes + centros de presión (A/B)
  reports: 8, // reportes de tormenta últimas 24 h (lo que pasó)
  drought: 8, // monitor de sequía USDM
  condiciones: 8, // temperatura NBM "ahora" + cajas de ciudad
  precip_fcst: 8, // "radar a futuro": precip NBM próximas 24 h (lluvia/nieve/hielo)
  precip_accum: 8, // precipitación acumulada 24 h (lluvia/nieve/hielo)
  alerts: 8, // vigilancias + cajas por categoría
  aeropuertos: 8, // demoras de aeropuertos (FAA)
  uv: 8, // índice UV máximo de hoy (EPA)
  aqi: 8, // calidad del aire / AQI (AirNow)
  spc: 8, // riesgo de tiempo severo (SPC día 1)
  tmax_today: 8, // temperatura máxima de hoy
  tvar: 8, // cambio de temperatura (próximas 24 h)
  tmax_tomorrow: 8, // temperatura máxima de mañana
  outro: 4,
} as const;

// Disponibilidad de los productos del cierre (algunos feeds pueden faltar, p. ej.
// la máxima de HOY en runs de tarde). Las escenas sin datos no se incluyen.
export type SceneAvail = {
  quake?: boolean;
  fronts?: boolean;
  reports?: boolean;
  drought?: boolean;
  spc?: boolean;
  tmaxToday?: boolean;
  tvar?: boolean;
  tmaxTomorrow?: boolean;
};

export function buildScenePlan(avail?: SceneAvail): ScenePlanItem[] {
  const a: SceneAvail =
    avail ?? { fronts: true, reports: true, drought: true, spc: true, tmaxToday: true, tvar: true, tmaxTomorrow: true };
  const order: (keyof typeof SCENE_SECONDS)[] = [];
  // Última hora: si hay un terremoto fuerte (M≥5.5) sobre EEUU, ABRE el vídeo con
  // el cartel de última hora + el mapa del epicentro, ANTES de la portada.
  if (a.quake) order.push("quake_intro", "quake");
  order.push("open", "geocolor", "radar");
  // (Mapa de superficie/frentes retirado del plan: gráfica descartada. El feed y
  // el Still "Mockup-frentes" se mantienen por si se reactiva.)
  order.push("alerts");
  // Bloque "tiempo severo": riesgo SPC (aviso) seguido de reportes (lo que pasó).
  if (a.spc) order.push("spc");
  if (a.reports) order.push("reports");
  order.push("condiciones", "precip_fcst", "precip_accum", "aeropuertos", "uv", "aqi");
  // Sequía antes del bloque de temperatura (estado del terreno).
  if (a.drought) order.push("drought");
  if (a.tmaxToday) order.push("tmax_today");
  if (a.tvar) order.push("tvar");
  if (a.tmaxTomorrow) order.push("tmax_tomorrow");
  order.push("outro");
  return order.map((type) => ({
    id: type,
    type,
    seconds: SCENE_SECONDS[type],
  }));
}

export function planDurationInFrames(plan: ScenePlanItem[], fps: number): number {
  const total = plan.reduce((acc, s) => acc + s.seconds, 0);
  return Math.round(total * fps);
}
