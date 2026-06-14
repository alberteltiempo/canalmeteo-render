// ─── Datos tropicales (data/tropical/active_storms.json) ───
export type StormLayers = {
  cone?: string;
  track?: string;
  points?: string;
  forecast_radii?: string;
  ww?: string;
  arrival_earliest?: string;
  arrival_likely?: string;
  past_swath?: string;
  past_track?: string;
  [k: string]: string | undefined;
};

// Datos del punto actual (primer feature de points.geojson)
export type StormCur = {
  maxwind?: number | null; // kt
  gust?: number | null; // kt
  mslp?: number | null; // mb
  datelbl?: string;
};

export type Storm = {
  id: string;
  name: string;
  intensity_kt?: number | null;
  lon?: number | null;
  lat?: number | null;
  last_update?: string;
  layers?: StormLayers;
  // enriquecido en calculateMetadata:
  _cur?: StormCur;
  _precip?: PrecipData;
  // bbox del cono [[w,s],[e,n]] para encuadrar igual cono y lluvia
  _coneBounds?: [[number, number], [number, number]];
  // movimiento (si el pipeline lo publica):
  _maxFcstKt?: number; // viento máx. previsto (kt) → categoría máxima
  movement_dir?: string | number | null; // p.ej. "NW" o grados
  movement_mph?: number | null;
  [k: string]: unknown;
};

export type GenesisData = {
  areas?: unknown[];
  points?: unknown[];
  [k: string]: unknown;
};

export type ActiveStorms = {
  updated?: string;
  storms: Storm[];
  genesis?: GenesisData;
  [k: string]: unknown;
};

// ─── Satélite full-disk (data/satellite-fd/{vista}/manifest.json) ───
export type SatFrame = { url: string; time: number };
export type SatBounds = { north: number; south: number; west: number; east: number };

// Multi-banda: guardamos varias bandas del mismo manifest (geocolor + ir)
export type SatData = {
  view: string;
  sat?: string; // GOES19 | GOES18
  bounds: SatBounds | null;
  bands: Record<string, SatFrame[]>; // { geocolor:[...], ir:[...] }
};

// Vista de una sola banda (lo que consume SatMap)
export type SatView = {
  view: string;
  band: string;
  sat?: string;
  bounds: SatBounds | null;
  frames: SatFrame[];
};

// ─── Lluvia (NBM CONUS / GFS global) ───
export type PrecipData = {
  model: string; // "NBM" | "GFS Global"
  bounds: SatBounds | null;
  frames: SatFrame[]; // precipAccum (acumulado creciente) o precipRate por hora
  colors?: string[]; // paleta para la leyenda
  vmax?: number; // in
  accumulated?: boolean; // true si es precipAccum
  horizonH?: number; // última hora de pronóstico incluida (p.ej. 120)
};

// ─── Plan de escenas ───
export type SceneType =
  | "open"
  | "satGlobal"
  | "stormSat"
  | "stormTrack"
  | "countIntro"
  | "stormRain"
  | "basinIntro"
  | "basinStatus"
  | "nameList"
  | "genesis"
  | "outro";

export type Basin = "atlantic" | "epac";

export type ScenePlanItem = {
  id: string;
  type: SceneType;
  seconds: number;
  stormIndex?: number;
  basin?: Basin;
  mode?: "none" | "monitoring";
};

export type TropicoProps = {
  data: ActiveStorms;
  plan: ScenePlanItem[];
  sat?: SatData;
};
