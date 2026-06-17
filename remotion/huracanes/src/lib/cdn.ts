import type {
  ActiveStorms,
  Storm,
  ScenePlanItem,
  SatData,
  SatView,
  SatFrame,
  PrecipData,
  Basin,
} from "../types";
import { stormBasin } from "./names2026";
import { TROP_CAT, TROP_WW } from "./theme";
import { isDaytime } from "./sun";

export const CDN = "https://canalmeteo-public.sfo3.digitaloceanspaces.com";
export const TROP_BASE = `${CDN}/data/tropical`;

// Resuelve una ruta relativa del índice (s.layers.*) a URL absoluta del CDN
export function tropURL(rel: string): string {
  return `${CDN}/${String(rel).replace(/^\//, "")}?ts=${Date.now()}`;
}

export async function fetchActiveStorms(
  signal?: AbortSignal
): Promise<ActiveStorms> {
  try {
    const r = await fetch(`${TROP_BASE}/active_storms.json?ts=${Date.now()}`, {
      signal,
    });
    const raw = await r.json();
    // No usamos zod.parse aquí: es nuestro propio CDN y un esquema estricto
    // descartaría TODAS las tormentas si un campo no encaja. Normalizamos suave.
    const storms = Array.isArray(raw?.storms) ? raw.storms : [];
    // eslint-disable-next-line no-console
    console.log(`[huracanes] active_storms → ${storms.length} tormenta(s)`);
    return { ...(raw || {}), storms } as ActiveStorms;
  } catch (e) {
    console.warn("[huracanes] no se pudo leer active_storms.json:", e);
    return { storms: [] };
  }
}

export async function fetchGeoJSON(rel: string, signal?: AbortSignal) {
  const r = await fetch(tropURL(rel), { signal });
  return r.json();
}

// ---- Duraciones de cada escena (segundos) ----
export const SCENE_SECONDS = {
  open: 3.5,
  countIntro: 3.5, // slide "N tormentas activas" + nombres
  satGlobal: 10, // vistazo global ampliado — el doble de duración
  basinIntro: 2.5, // slide de marca "Cuenca Atlántica" / "Pacífico"
  stormSat: 6, // satélite zoom + tarjeta de datos
  stormTrack: 7, // trayectoria + cono + avisos (animado)
  investStatus: 6, // invest: caja de situación (probabilidad de formación)
  stormRain: 9, // lluvia acumulada creciente (5 días) — más larga para que se lea
  nameList: 6, // lista de nombres de la temporada (por cuenca)
  basinStatus: 5, // "No hay tormentas activas" / "Zona en vigilancia" (GeoColor cuenca)
  genesis: 5, // áreas de desarrollo
  outro: 4,
} as const;

// Encuadre GeoColor por cuenca (bbox lon/lat) para los slides de estado de cuenca
export const BASIN_VIEW: Record<Basin, [[number, number], [number, number]]> = {
  atlantic: [
    [-100, 7],
    [-30, 45],
  ],
  epac: [
    [-140, 5],
    [-88, 30],
  ],
};

// Atribuye un área/punto de génesis a una cuenca: por campo si existe, si no
// por geografía (centroide). PROVISIONAL hasta ver la estructura real de NHC.
function deepCoords(o: unknown, out: number[][] = []): number[][] {
  if (Array.isArray(o)) {
    if (
      o.length === 2 &&
      typeof o[0] === "number" &&
      typeof o[1] === "number" &&
      Math.abs(o[0]) <= 180 &&
      Math.abs(o[1]) <= 90
    ) {
      out.push([o[0], o[1]]);
    } else {
      o.forEach((x) => deepCoords(x, out));
    }
  } else if (o && typeof o === "object") {
    const g = (o as any).geometry ?? (o as any).coordinates ?? null;
    if (g) deepCoords((o as any).coordinates ?? (o as any).geometry, out);
  }
  return out;
}

function areaBasin(area: any): Basin | null {
  const p = area?.properties ?? area ?? {};
  const tag = String(
    p.basin ?? p.BASIN ?? p.area ?? p.AREA ?? p.region ?? p.REGION ?? ""
  ).toLowerCase();
  if (tag.includes("atl")) return "atlantic";
  if (tag.includes("pac") || tag.includes("epac") || tag.includes("east")) return "epac";
  // geografía: centroide de las coordenadas que encontremos
  const pts = deepCoords(area.geometry ?? area.coordinates ?? area);
  if (pts.length) {
    const lon = pts.reduce((a, c) => a + c[0], 0) / pts.length;
    const lat = pts.reduce((a, c) => a + c[1], 0) / pts.length;
    if (lon <= -100 || (lon <= -84 && lat <= 16)) return "epac";
    return "atlantic";
  }
  return null;
}

// Posiciones de TODOS los sistemas activos (invests Y sistemas con nombre:
// depresión/tormenta/PC). Sirve para no mostrar su zona de génesis otra vez como
// "Zona en vigilancia": si ya hay un sistema ahí (con sus escenas o su cono), esa
// perturbación ya está contada.
function systemClaims(data: ActiveStorms): Array<[number, number]> {
  return (data.storms || [])
    .filter((s) => typeof s.lon === "number" && typeof s.lat === "number")
    .map((s) => [s.lon as number, s.lat as number]);
}

// Quita los invests ya REEMPLAZADOS por un sistema con nombre. El NHC numera la
// perturbación (90L/01L) y, cuando la clasifica, la publica TAMBIÉN como sistema
// con nombre (depresión "One", PC, tormenta…) con su cono. Llegan los dos en el
// feed → el vídeo repetía satélite+situación+lluvia del invest justo después de
// la trayectoria del sistema con nombre. Si hay un sistema NO-invest a ≲2.5° del
// invest, es el mismo: descartamos el invest. (Posición, no id: al desarrollarse,
// 90L se renumera a AL01, así que los ids no casan.)
export function dedupeInvests(data: ActiveStorms): ActiveStorms {
  const named = (data.storms || []).filter(
    (s) => !s.is_invest && typeof s.lon === "number" && typeof s.lat === "number"
  );
  if (!named.length) return data;
  const storms = (data.storms || []).filter((s) => {
    if (!s.is_invest || typeof s.lon !== "number" || typeof s.lat !== "number") return true;
    const replaced = named.some(
      (n) =>
        Math.abs((n.lon as number) - (s.lon as number)) <= 2.5 &&
        Math.abs((n.lat as number) - (s.lat as number)) <= 2.5
    );
    return !replaced;
  });
  return { ...data, storms };
}

function featureCentroid(f: any): [number, number] | null {
  const pts = deepCoords(f?.geometry ?? f?.coordinates ?? f);
  if (!pts.length) return null;
  const lon = pts.reduce((a, c) => a + c[0], 0) / pts.length;
  const lat = pts.reduce((a, c) => a + c[1], 0) / pts.length;
  return [lon, lat];
}

// ¿Esta zona de génesis ya está representada por un invest activo? (centroide a
// menos de ~2.5° de la posición del invest). Si sí, no la contamos/mostramos
// como zona genérica de vigilancia.
function claimedByInvest(f: any, claims: Array<[number, number]>): boolean {
  if (!claims.length) return false;
  const c = featureCentroid(f);
  if (!c) return false;
  return claims.some(([lon, lat]) => Math.abs(lon - c[0]) <= 2.5 && Math.abs(lat - c[1]) <= 2.5);
}

// objectid (id NHC) de una feature de génesis, normalizado a string.
function featureObjectId(f: any): string | null {
  const p = f?.properties ?? f ?? {};
  const id = p.objectid ?? p.OBJECTID ?? p.id ?? p.ID;
  return id != null ? String(id) : null;
}

// objectids de génesis ya cubiertos por un invest. El NHC publica la MISMA
// perturbación como punto (la "X", justo sobre el invest) y como polígono (el
// área de desarrollo, que puede extenderse grados mar adentro → su centroide
// queda lejos del invest). claimedByInvest acierta con el punto pero falla con
// el polígono aunque compartan objectid. Al reunir por objectid, si CUALQUIER
// feature del id está sobre un invest, todo el id queda cubierto y la zona no se
// duplica como "Zona en vigilancia".
function claimedObjectIds(
  data: ActiveStorms,
  claims: Array<[number, number]>
): Set<string> {
  const ids = new Set<string>();
  if (!claims.length) return ids;
  const all = [
    ...((data.genesis?.areas as any[]) || []),
    ...((data.genesis?.points as any[]) || []),
  ];
  all.forEach((f) => {
    const oid = featureObjectId(f);
    if (oid != null && claimedByInvest(f, claims)) ids.add(oid);
  });
  return ids;
}

// ¿Esta feature de génesis ya está representada por un invest? Por cercanía
// directa o por compartir objectid con otra feature que sí lo está.
function isClaimed(
  f: any,
  claims: Array<[number, number]>,
  ids: Set<string>
): boolean {
  if (claimedByInvest(f, claims)) return true;
  const oid = featureObjectId(f);
  return oid != null && ids.has(oid);
}

// Encuadre de lluvia para un invest sin cono: une el punto del invest con el
// polígono de su zona de génesis (misma perturbación, enlazada por el objectid
// del punto del NHC más cercano). El área de desarrollo suele extenderse mar
// adentro respecto al punto, así que encuadrar solo al punto recorta la lluvia.
// Añade margen y un span mínimo para no quedar excesivamente cerca.
function investGenesisBounds(
  storm: Storm,
  genesis: ActiveStorms["genesis"] | undefined
): [[number, number], [number, number]] | null {
  if (!genesis || storm.lon == null || storm.lat == null) return null;
  const slon = storm.lon as number;
  const slat = storm.lat as number;
  const pts = (genesis.points as any[]) || [];
  let oid: string | null = null;
  let bestD = Infinity;
  pts.forEach((f) => {
    const c = featureCentroid(f);
    const id = featureObjectId(f);
    if (!c || id == null) return;
    const d = Math.abs(c[0] - slon) + Math.abs(c[1] - slat);
    if (d < bestD) {
      bestD = d;
      oid = id;
    }
  });
  if (oid == null || bestD > 5) return null;
  const linked = ((genesis.areas as any[]) || []).filter((a) => featureObjectId(a) === oid);
  const bb = geoBounds({ type: "FeatureCollection", features: linked } as any);
  let w = slon,
    e = slon,
    s = slat,
    n = slat;
  if (bb) {
    w = Math.min(w, bb[0][0]);
    s = Math.min(s, bb[0][1]);
    e = Math.max(e, bb[1][0]);
    n = Math.max(n, bb[1][1]);
  }
  const M = 1.5; // grados de margen
  const MIN = 9; // span mínimo (grados)
  w -= M;
  e += M;
  s -= M;
  n += M;
  const cx = (w + e) / 2;
  const cy = (s + n) / 2;
  if (e - w < MIN) {
    w = cx - MIN / 2;
    e = cx + MIN / 2;
  }
  if (n - s < MIN) {
    s = cy - MIN / 2;
    n = cy + MIN / 2;
  }
  return [
    [w, s],
    [e, n],
  ];
}

// Una "zona" de génesis = UNA perturbación del NHC. El feed la publica por
// duplicado: como polígono en genesis.areas Y como punto (la "X") en
// genesis.points; además cada punto sale dos veces (outlook a 2 y a 7 días).
// Sumar areas + points cuenta la misma perturbación 2-3 veces. Deduplicamos por
// cuenca + objectid para contar perturbaciones distintas, no features. Las areas
// van primero: si una perturbación aparece como área y como punto, conservamos
// el área (lleva el polígono dibujable).
export function genesisZones(
  data: ActiveStorms
): Array<{ basin: Basin | null; feature: any }> {
  const g = data.genesis;
  if (!g) return [];
  const claims = systemClaims(data);
  const claimedIds = claimedObjectIds(data, claims);
  const all = [...((g.areas as any[]) || []), ...((g.points as any[]) || [])];
  const seen = new Map<string, { basin: Basin | null; feature: any }>();
  all.forEach((f, i) => {
    if (isClaimed(f, claims, claimedIds)) return; // ya se muestra como invest
    const p = f?.properties ?? f ?? {};
    const id = p.objectid ?? p.OBJECTID ?? p.id ?? p.ID;
    const basin = areaBasin(f);
    const key = id != null ? `${basin}#${id}` : `idx#${i}`;
    if (!seen.has(key)) seen.set(key, { basin, feature: f });
  });
  return [...seen.values()];
}

// ¿Cuántas zonas en monitoreo (génesis) distintas hay? Sin basin: total.
export function genesisZoneCount(data: ActiveStorms, basin?: Basin): number {
  const zones = genesisZones(data);
  return basin ? zones.filter((z) => z.basin === basin).length : zones.length;
}

// ¿Cuántas zonas en monitoreo (génesis) tiene una cuenca?
export function genesisCountForBasin(data: ActiveStorms, basin: Basin): number {
  return genesisZoneCount(data, basin);
}

// Áreas de génesis (polígonos) de una cuenca, con geometría utilizable.
export function genesisAreasForBasin(data: ActiveStorms, basin: Basin): any[] {
  const areas = (data.genesis?.areas as any[]) || [];
  const claims = systemClaims(data);
  const claimedIds = claimedObjectIds(data, claims);
  return areas.filter(
    (a) =>
      areaBasin(a) === basin &&
      (a?.geometry?.coordinates || a?.coordinates) &&
      !isClaimed(a, claims, claimedIds)
  );
}

// Construye el plan de escenas según los datos (timeline dinámico)
export function buildScenePlan(data: ActiveStorms): ScenePlanItem[] {
  const plan: ScenePlanItem[] = [];
  const push = (
    type: ScenePlanItem["type"],
    seconds: number,
    opts: { stormIndex?: number; basin?: Basin; mode?: "none" | "monitoring" } = {}
  ) =>
    plan.push({
      id: `${type}-${opts.basin ?? ""}-${opts.mode ?? ""}-${opts.stormIndex ?? "x"}`,
      type,
      seconds,
      stormIndex: opts.stormIndex,
      basin: opts.basin,
      mode: opts.mode,
    });

  push("open", SCENE_SECONDS.open);
  push("satGlobal", SCENE_SECONDS.satGlobal);
  push("countIntro", SCENE_SECONDS.countIntro); // tras el GeoColor general

  const storms = data.storms || [];
  const idxsOf = (basin: Basin) =>
    storms
      .map((s, i) => ({ s, i }))
      .filter((o) => stormBasin(o.s) === basin)
      .map((o) => o.i);

  // Orden: primero la(s) cuenca(s) CON tormentas activas; luego la(s) vacía(s).
  // Si ambas tienen, se mantiene Atlántico → Pacífico.
  const basins: Basin[] = (["atlantic", "epac"] as Basin[]).sort(
    (a, b) => (idxsOf(b).length > 0 ? 1 : 0) - (idxsOf(a).length > 0 ? 1 : 0)
  );

  basins.forEach((basin) => {
    const idxs = idxsOf(basin);

    push("basinIntro", SCENE_SECONDS.basinIntro, { basin });
    idxs.forEach((i) => {
      push("stormSat", SCENE_SECONDS.stormSat, { stormIndex: i });
      // Un invest no tiene cono/trayectoria oficial del NHC → en su lugar
      // mostramos la caja de situación (probabilidad de formación). Tormentas y
      // depresiones mantienen la escena de trayectoria.
      if (storms[i]?.is_invest) {
        push("investStatus", SCENE_SECONDS.investStatus, { stormIndex: i });
      } else {
        push("stormTrack", SCENE_SECONDS.stormTrack, { stormIndex: i });
      }
      push("stormRain", SCENE_SECONDS.stormRain, { stormIndex: i });
    });

    // Estado de cuenca (antes de los nombres):
    const monitoring = genesisCountForBasin(data, basin) > 0;
    if (monitoring) {
      push("basinStatus", SCENE_SECONDS.basinStatus, { basin, mode: "monitoring" });
    } else if (!idxs.length) {
      // sin tormentas: el satélite es el protagonista → dura el doble
      push("basinStatus", SCENE_SECONDS.basinStatus * 2, { basin, mode: "none" });
    }

    // Los nombres SIEMPRE al final de la cuenca
    push("nameList", SCENE_SECONDS.nameList, { basin });
  });

  push("outro", SCENE_SECONDS.outro);
  return plan;
}

// Frames de cross-dissolve entre escenas (las transiciones SOLAPAN frames).
export const TRANSITION_FRAMES = 12;

export function planDurationInFrames(
  plan: ScenePlanItem[],
  fps: number,
  transitionFrames = 0
): number {
  const total = plan.reduce((acc, s) => acc + s.seconds, 0);
  const frames = Math.round(total * fps);
  const overlaps = Math.max(0, plan.length - 1) * transitionFrames;
  return frames - overlaps;
}

// ─────────────────────────────────────────────────────────────
// Satélite GOES (mismo CDN y estructura que el viewer Tormenta)
// ─────────────────────────────────────────────────────────────
export const MAPBOX_TOKEN =
  "pk.eyJ1IjoiYWxiZXJ0ZWx0aWVtcG8iLCJhIjoiY21rM2pqa29zMGd6NjNncHdlMWZ1NTNlayJ9.0d2lAZ-CmqEuoPe_h2JEHA";
export const MAPBOX_STYLE = "mapbox://styles/mapbox/dark-v11";
// Padding de encuadre COMPARTIDO entre la escena de cono y la de lluvia, para
// que el fitBounds al mismo bbox del cono dé exactamente la misma cámara.
export const FRAME_PADDING = { top: 150, bottom: 90, left: 90, right: 90 };
export const SAT_FD_BASE = `${CDN}/data/satellite-fd`;

// Vistas full-disk disponibles: disco-este | caribe-golfo | mexico-ca |
// atlantico | disco-oeste | epac. Descargamos varias bandas del mismo manifest
// (geocolor + ir) para poder elegir día/noche por tormenta.
// Comprueba (HEAD) qué frames de satélite existen en el CDN y descarta 404.
// Ante error de red transitorio, conserva el frame (no sobre-podar).
async function filterExistingFrames(
  frames: SatFrame[],
  signal?: AbortSignal
): Promise<SatFrame[]> {
  if (!frames.length) return frames;
  const ok = await Promise.all(
    frames.map(async (f) => {
      try {
        const res = await fetch(f.url, { method: "HEAD", signal });
        return res.ok || res.status === 405; // 405 = HEAD no permitido → asumir que existe
      } catch {
        return true;
      }
    })
  );
  const kept = frames.filter((_, i) => ok[i]);
  return kept.length ? kept : frames; // si todo falla, no dejar vacío
}

export async function fetchSatelliteData(
  view: string,
  bands: string[] = ["geocolor", "ir"],
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
      // El manifest puede ir por delante del CDN (último frame aún subiendo) →
      // descartamos los que devuelven 404 para que no salgan en blanco.
      out[b] = await filterExistingFrames(sliced, signal);
    }
    return { view, sat: vm?.sat, bounds: vm?.bounds || null, bands: out };
  } catch (e) {
    console.warn(`[huracanes] satélite ${view}:`, e);
    return { view, bounds: null, bands: {} };
  }
}

// Construye una vista de una sola banda (lo que consume SatMap).
export function satViewFromBand(data: SatData | undefined, band: string): SatView {
  const bands = data?.bands || {};
  // banda pedida; si vacía, la primera no vacía disponible
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
    // Diezmar a un máximo de texturas para no saturar la GPU en el render
    // (todos los frames se cargan como capas raster a la vez). Conserva el span
    // temporal completo (p.ej. 6h) pero con menos frames (paso mayor).
    frames: decimateFrames(all, MAX_SAT_FRAMES),
  };
}

// GeoColor de día / Infrarrojo de noche, según el sol en (lat,lon) en el instante
// del último frame disponible. GeoColor se vuelve negro en el lado nocturno del
// disco (el terminador cruza con frecuencia el Golfo/Caribe a horas UTC de
// madrugada americana); el IR realzado se ve igual de día y de noche. Cae a la
// banda que exista si falta la elegida (satViewFromBand ya hace ese fallback).
export function satViewDayNight(
  data: SatData | undefined,
  lat: number,
  lon: number
): SatView {
  const gc = data?.bands?.geocolor || [];
  const ir = data?.bands?.ir || [];
  const ref = gc[gc.length - 1] || ir[ir.length - 1];
  const day = ref ? isDaytime(new Date(ref.time * 1000), lat, lon) : true;
  return satViewFromBand(data, day ? "geocolor" : "ir");
}

// GOES IR banda 13, paleta "windy" (colorida) + transparencia — data/goes_ir_windy
// (producido por goes_ir_pipeline.py en nimbus-01). PNG transparentes: despejado =
// transparente, nubes en blanco/gris y topes fríos coloreados (azul→cian→verde→
// amarillo→rojo). Se drapean a opacidad 1 sobre el mapa base y se ven IGUAL de día
// y de noche (a diferencia del GeoColor, que se vuelve negro en el lado nocturno).
// Lo usamos en el zoom del invest. Vistas: conus | este | oeste.
export const GOES_IR_WINDY_BASE = `${CDN}/data/goes_ir_windy`;
export async function fetchGoesIr(
  view: string,
  signal?: AbortSignal
): Promise<SatView> {
  try {
    const r = await fetch(`${GOES_IR_WINDY_BASE}/${view}/manifest.json?ts=${Date.now()}`, {
      signal,
    });
    const m = await r.json();
    const all: SatFrame[] = (Array.isArray(m?.frames) ? m.frames : []).map((f: any) => ({
      url: f.url,
      time: f.timestamp ?? 0,
    }));
    // Mismo límite de texturas y verificación de 404 que el satélite full-disk.
    const kept = await filterExistingFrames(decimateFrames(all, MAX_SAT_FRAMES), signal);
    return {
      view: `goes_ir_windy_${view}`,
      band: "ir",
      sat: m?.sat,
      bounds: m?.bounds || null,
      frames: kept,
    };
  } catch (e) {
    console.warn(`[huracanes] goes_ir_windy ${view}:`, e);
    return { view: `goes_ir_windy_${view}`, band: "ir", bounds: null, frames: [] };
  }
}

// Máximo de frames de satélite a renderizar simultáneamente (límite GPU).
export const MAX_SAT_FRAMES = 18;

function decimateFrames<T>(arr: T[], max: number): T[] {
  const n = arr.length;
  if (n <= max) return arr;
  const step = (n - 1) / (max - 1);
  const out: T[] = [];
  for (let i = 0; i < max; i++) out.push(arr[Math.round(i * step)]);
  // garantiza el último (más reciente) frame
  out[out.length - 1] = arr[n - 1];
  return out;
}

// ─────────────────────────────────────────────────────────────
// Enriquecer tormentas con el punto actual (viento/ráfaga/presión)
// ─────────────────────────────────────────────────────────────
export async function enrichStorms(
  data: ActiveStorms,
  signal?: AbortSignal
): Promise<ActiveStorms> {
  const storms = await Promise.all(
    (data.storms || []).map(async (s): Promise<Storm> => {
      const out: Storm = { ...s };
      // Punto actual (viento/ráfaga/presión)
      try {
        if (s.layers?.points) {
          const gj = await fetchGeoJSON(s.layers.points, signal);
          const feats = gj?.features || [];
          const f0 = feats[0];
          const p = f0?.properties || {};
          // Posición autoritativa: geometría del primer punto del fichero de
          // trayectoria (TAU=0). Sobrescribe lon/lat del boletín (redondeados)
          // para que satélite, cono y lluvia compartan EXACTAMENTE el mismo punto.
          const c0 = f0?.geometry?.coordinates;
          if (Array.isArray(c0) && typeof c0[0] === "number" && typeof c0[1] === "number") {
            out.lon = c0[0];
            out.lat = c0[1];
          }
          out._cur = {
            maxwind: p.maxwind ?? null,
            gust: p.gust ?? null,
            mslp: p.mslp != null && p.mslp < 9000 ? p.mslp : null,
            datelbl: p.datelbl,
          };
          // Categoría máxima prevista: mayor maxwind a lo largo del pronóstico
          let maxKt = 0;
          feats.forEach((f: any) => {
            const w = f?.properties?.maxwind;
            if (typeof w === "number" && w < 9000 && w > maxKt) maxKt = w;
          });
          if (maxKt > 0) out._maxFcstKt = maxKt;
        }
      } catch {
        /* noop */
      }
      // Invest sin points.geojson: el viento/ráfaga/presión vienen inline en el
      // índice (intensity_kt/gust_kt/mslp_mb del ATCF) → construimos _cur a mano
      // para que la tarjeta de datos los muestre igual que en una tormenta.
      if (s.is_invest && (!out._cur || out._cur.maxwind == null)) {
        out._cur = {
          maxwind: s.intensity_kt ?? out._cur?.maxwind ?? null,
          gust: s.gust_kt ?? out._cur?.gust ?? null,
          mslp: s.mslp_mb ?? out._cur?.mslp ?? null,
          datelbl: out._cur?.datelbl,
        };
      }
      // Bbox del cono → encuadre compartido entre escena de cono y de lluvia
      try {
        if (s.layers?.cone) {
          const cone = await fetchGeoJSON(s.layers.cone, signal);
          const bb = geoBounds(cone);
          if (bb) out._coneBounds = bb;
        }
      } catch {
        /* noop */
      }
      return out;
    })
  );

  // Génesis: el pipeline publica genesis.areas/points como RUTA a un GeoJSON.
  // El vídeo necesita las features inline → las descargamos aquí. Nos quedamos
  // solo con polígonos (la zona de desarrollo; descartamos LineString de motion).
  const genesis = { ...(data.genesis || {}) } as any;
  for (const key of ["areas", "points"] as const) {
    const v = (data.genesis as any)?.[key];
    if (typeof v === "string") {
      try {
        const gj = await fetchGeoJSON(v, signal);
        let feats = (gj?.features || []) as any[];
        if (key === "areas") {
          const polys = feats.filter((f) => /Polygon/i.test(f?.geometry?.type || ""));
          if (polys.length) feats = polys; // preferimos el polígono de la zona
        }
        genesis[key] = feats;
      } catch {
        genesis[key] = [];
      }
    }
  }

  // Encuadre de lluvia para invests (sin cono): a partir de su zona de génesis,
  // ya con las features de génesis descargadas inline.
  const stormsFramed = storms.map((s) =>
    s.is_invest && !s._coneBounds
      ? { ...s, _genesisBounds: investGenesisBounds(s, genesis) ?? undefined }
      : s
  );

  return { ...data, storms: stormsFramed, genesis };
}

// ─────────────────────────────────────────────────────────────
// Helpers tropicales (idénticos al viewer Tormenta)
// ─────────────────────────────────────────────────────────────
export function tropMarkerSVG(catKey: string): string {
  const info = TROP_CAT[catKey] || { color: "#90caf9", letter: "?" };
  const txt = catKey === "H1" ? "#333" : "#fff";
  return (
    `<svg viewBox="0 0 36 36" width="100%" height="100%"><circle cx="18" cy="18" r="14" fill="${info.color}" stroke="#fff" stroke-width="2.5"/>` +
    `<text x="18" y="18" dy="0.35em" text-anchor="middle" font-family="Outfit,sans-serif" font-size="16" font-weight="800" fill="${txt}">${info.letter}</text></svg>`
  );
}

export function tropWWColor(v: unknown): string {
  const s = String(v ?? "").toUpperCase().trim();
  if (TROP_WW[s]) return TROP_WW[s];
  if (/HU.*W|HURRICANE WARNING/.test(s)) return "#cc0000";
  if (/HU.*A|HURRICANE WATCH/.test(s)) return "#ff66cc";
  if (/(TR|TS).*W|TROPICAL STORM WARNING/.test(s)) return "#1e6fff";
  if (/(TR|TS).*A|TROPICAL STORM WATCH/.test(s)) return "#ffd000";
  return "#9e9e9e";
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
  (gj?.features || []).forEach((f: any) => f?.geometry?.coordinates && scan(f.geometry.coordinates));
  if (!isFinite(w)) return null;
  return [
    [w, s],
    [e, n],
  ];
}

// Aclara el océano del basemap (dark-v11 lo trae casi negro). Para todos los mapas.
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

// ─────────────────────────────────────────────────────────────
// Lluvia: NBM (CONUS) para sistemas en EEUU, GFS global para el resto.
// Mismo formato de manifest: { bounds, variables.precipIn{colors,vmax},
// hours:[{fhour, validTimeUnix, images.precipIn}] }. precipIn es por hora.
// ─────────────────────────────────────────────────────────────
export const NBM_MANIFEST = `${CDN}/data/nbm/nbm_manifest.json`;
export const GFS_MANIFEST = `${CDN}/data/gfs_global/gfs_global_manifest.json`;

type ModelManifest = {
  model?: string;
  bounds?: { north: number; south: number; west: number; east: number };
  variables?: Record<string, { colors?: string[]; vmax?: number }>;
  hours?: { fhour: number; validTimeUnix?: number; images?: Record<string, string> }[];
};

async function fetchManifest(url: string, signal?: AbortSignal): Promise<ModelManifest | null> {
  try {
    const r = await fetch(`${url}?ts=${Date.now()}`, { signal });
    return (await r.json()) as ModelManifest;
  } catch (e) {
    console.warn("[huracanes] manifest precip:", url, e);
    return null;
  }
}

export async function fetchPrecipManifests(signal?: AbortSignal) {
  const [nbm, gfs] = await Promise.all([
    fetchManifest(NBM_MANIFEST, signal),
    fetchManifest(GFS_MANIFEST, signal),
  ]);
  return { nbm, gfs };
}

// ¿La tormenta está sobre/junto a EEUU? (posición actual dentro de bounds NBM
// con un pequeño margen). Si sí → NBM; si no → GFS global.
function inUS(lon?: number | null, lat?: number | null, b?: ModelManifest["bounds"]): boolean {
  if (lon == null || lat == null || !b) return false;
  const m = 1.5;
  return (
    lon >= b.west - m && lon <= b.east + m && lat >= b.south - m && lat <= b.north + m
  );
}

function absUrl(u: string): string {
  return /^https?:\/\//.test(u) ? u : `${CDN}/${String(u).replace(/^\//, "")}`;
}

// Construye los frames de precip para una tormenta (animación próximas `maxH` h).
// Prefiere el acumulado creciente (precipAccum); si no existe, cae a precipRate/precipIn.
function buildPrecip(
  m: ModelManifest | null,
  stepH = 6,
  maxH = 120
): PrecipData | undefined {
  if (!m?.hours?.length) return undefined;
  const candidates = ["precipAccum", "precipRate", "precipIn"];
  const varName = candidates.find(
    (v) => m.variables?.[v] && m.hours!.some((h) => h.images?.[v])
  );
  if (!varName) return undefined;
  const pv = m.variables?.[varName];
  const used = m.hours.filter(
    (h) =>
      h.fhour >= 1 && h.fhour <= maxH && h.fhour % stepH === 0 && h.images?.[varName]
  );
  const frames: SatFrame[] = used.map((h) => ({
    url: absUrl(h.images![varName] as string),
    time: h.validTimeUnix ?? 0,
  }));
  if (!frames.length) return undefined;
  const horizonH = used.length ? used[used.length - 1].fhour : maxH;
  return {
    model: m.model || "Modelo",
    bounds: m.bounds || null,
    frames,
    colors: pv?.colors,
    vmax: pv?.vmax ?? 2,
    accumulated: varName === "precipAccum",
    horizonH,
  };
}

// Adjunta _precip a cada tormenta eligiendo modelo según ubicación.
export function attachPrecip(
  data: ActiveStorms,
  manifests: { nbm: ModelManifest | null; gfs: ModelManifest | null }
): ActiveStorms {
  const storms = (data.storms || []).map((s): Storm => {
    const useNBM = inUS(s.lon, s.lat, manifests.nbm?.bounds);
    const precip = buildPrecip(useNBM ? manifests.nbm : manifests.gfs);
    return precip ? { ...s, _precip: precip } : s;
  });
  return { ...data, storms };
}
