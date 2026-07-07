// Ciudades principales de Llanuras del Norte, bien distribuidas por la región, para
// rotular el mapa. Nombres en español donde aplica. Coordenadas lon/lat.
export type City = { name: string; lon: number; lat: number };

// Ordenadas por IMPORTANCIA (de mayor a menor). El orden es la prioridad: cuando
// dos rótulos se solapan en pantalla, gana el que va antes (el otro se descarta).
export const MAJOR_CITIES: City[] = [
  { name: "Denver", lon: -104.99, lat: 39.74 },
  { name: "Omaha", lon: -95.93, lat: 41.26 },
  { name: "Wichita", lon: -97.34, lat: 37.69 },
  { name: "Colorado Springs", lon: -104.82, lat: 38.83 },
  { name: "Billings", lon: -108.5, lat: 45.78 },
  { name: "Fargo", lon: -96.79, lat: 46.88 },
  { name: "Sioux Falls", lon: -96.73, lat: 43.55 },
  { name: "Rapid City", lon: -103.23, lat: 44.08 },
  { name: "Bismarck", lon: -100.78, lat: 46.81 },
  { name: "Cheyenne", lon: -104.82, lat: 41.14 },
  { name: "Lincoln", lon: -96.7, lat: 40.81 },
  { name: "Topeka", lon: -95.68, lat: 39.05 },
  { name: "Casper", lon: -106.31, lat: 42.87 },
  { name: "Missoula", lon: -113.99, lat: 46.87 },
  { name: "Great Falls", lon: -111.3, lat: 47.51 },
  { name: "Helena", lon: -112.04, lat: 46.59 },
  { name: "Bozeman", lon: -111.04, lat: 45.68 },
  { name: "Pierre", lon: -100.35, lat: 44.37 },
  { name: "Grand Forks", lon: -97.03, lat: 47.93 },
  { name: "Grand Junction", lon: -108.55, lat: 39.06 },
  { name: "Fort Collins", lon: -105.08, lat: 40.59 },
  { name: "Pueblo", lon: -104.61, lat: 38.25 },
  { name: "North Platte", lon: -100.77, lat: 41.12 },
  { name: "Dodge City", lon: -100.02, lat: 37.75 },
  { name: "Sheridan", lon: -106.96, lat: 44.8 },
  { name: "Minot", lon: -101.3, lat: 48.23 },
  { name: "Aberdeen", lon: -98.49, lat: 45.46 },
  { name: "Scottsbluff", lon: -103.66, lat: 41.87 },
];
