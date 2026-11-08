// Ciudades principales de EEUU, bien distribuidas por el territorio, para rotular
// el GEOCOLOR de CONUS. Nombres en español donde aplica. Coordenadas lon/lat.
export type City = { name: string; lon: number; lat: number };

// Ordenadas por IMPORTANCIA (de mayor a menor). El orden es la prioridad: cuando
// dos rótulos se solapan en pantalla, gana el que va antes (el otro se descarta).
export const MAJOR_CITIES: City[] = [] // se rellena por región en applyRegionRuntime (lib/cdn.ts);
