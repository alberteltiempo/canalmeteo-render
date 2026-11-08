// Tipos de la configuración por región (ver regions/<id>.ts).
export type LonLat = [number, number];
export type CityKeyed = { key: string; name: string; lon: number; lat: number };
export type CityId = { id: string; name: string; lon: number; lat: number };
export type AirportEntry = { iata: string; city: string; lon: number; lat: number };
export type Dir = "left" | "right" | "up" | "down";
export type NudgeMap = Record<string, [number, number]>;
export type ForceMap = Record<string, Dir>;

export type RegionConfig = {
  id: string; // "conus" | "ne" | …
  compositionId: string; // id del <Composition> del segmento (lo usa render.sh)
  escaletaSlug: string; // data/escaleta/<slug>.json
  openTitle: string; // rótulo grande de la portada
  noAlertsName: string; // «<nombre> · sin alertas del NWS»
  subSuffix: string; // " · EE. UU." en CONUS, "" en regionales
  airportsSub: string;
  quakeSub: string;
  droughtSub: string;
  feedSuffix: string | null; // population_by_level_<suf>, population_<suf>, regions.<suf>
  features: { conus: boolean }; // escenas solo CONUS: severo en vivo, mínimas, outlooks, humo
  deltaScale: "coarse" | "fine"; // escala de la variación de temperatura
  musicFile: string; // pista de código (public/audio/)
  view: [LonLat, LonLat];
  states: string[]; // [] = sin filtro por estado (CONUS)
  quakeBbox: { west: number; east: number; south: number; north: number };
  conditionCities: CityKeyed[];
  airports: AirportEntry[];
  serviceCities: CityId[];
  tmaxCities: CityId[];
  sampleTmax: Record<string, number>;
  layout: {
    airportNudge: NudgeMap;
    airportForce: ForceMap;
    serviceForce: ForceMap;
    serviceNudge: NudgeMap;
    tempNudge: NudgeMap;
    tempForce: ForceMap;
    condForce: ForceMap;
  };
};
