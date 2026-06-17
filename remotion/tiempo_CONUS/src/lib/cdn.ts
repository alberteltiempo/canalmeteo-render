import type {
  SatData,
  SatView,
  SatFrame,
  RadarData,
  AlertsData,
  AlertItem,
  ScenePlanItem,
  ThemeMode,
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
  open: 3.5,
  geocolor: 8, // satélite IR CONUS + ciudades (últimas 6 h)
  radar: 8, // radar últimas 6 h
  condiciones: 8, // temperatura NBM "ahora" + cajas de ciudad
  precip_fcst: 8, // "radar a futuro": precip NBM próximas 24 h (lluvia/nieve/hielo)
  precip_accum: 8, // precipitación acumulada 24 h (lluvia/nieve/hielo)
  alerts: 8, // vigilancias + cajas por categoría
  outro: 4,
} as const;

export function buildScenePlan(): ScenePlanItem[] {
  const order: (keyof typeof SCENE_SECONDS)[] = [
    "open",
    "geocolor",
    "radar",
    "alerts",
    "condiciones",
    "precip_fcst",
    "precip_accum",
    "outro",
  ];
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
