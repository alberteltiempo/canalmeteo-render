// Ciudades principales de las LLANURAS DEL SUR (TX·OK·AR·LA·NM), bien
// distribuidas por la región, para rotular el mapa. Nombres en español donde
// aplica. Coordenadas lon/lat.
export type City = { name: string; lon: number; lat: number };

// Ordenadas por IMPORTANCIA (de mayor a menor). El orden es la prioridad: cuando
// dos rótulos se solapan en pantalla, gana el que va antes (el otro se descarta).
export const MAJOR_CITIES: City[] = [
  { name: "Houston", lon: -95.37, lat: 29.76 },
  { name: "Dallas", lon: -96.8, lat: 32.78 },
  { name: "San Antonio", lon: -98.49, lat: 29.42 },
  { name: "Austin", lon: -97.74, lat: 30.27 },
  { name: "El Paso", lon: -106.49, lat: 31.76 },
  { name: "Oklahoma City", lon: -97.52, lat: 35.47 },
  { name: "Nueva Orleans", lon: -90.07, lat: 29.95 },
  { name: "Albuquerque", lon: -106.65, lat: 35.08 },
  { name: "Fort Worth", lon: -97.33, lat: 32.76 },
  { name: "Tulsa", lon: -95.99, lat: 36.15 },
  { name: "Baton Rouge", lon: -91.19, lat: 30.45 },
  { name: "Little Rock", lon: -92.29, lat: 34.75 },
  { name: "Corpus Christi", lon: -97.4, lat: 27.8 },
  { name: "Lubbock", lon: -101.86, lat: 33.58 },
  { name: "Amarillo", lon: -101.83, lat: 35.19 },
  { name: "Shreveport", lon: -93.75, lat: 32.52 },
  { name: "Santa Fe", lon: -105.94, lat: 35.69 },
  { name: "Laredo", lon: -99.51, lat: 27.51 },
  { name: "Brownsville", lon: -97.5, lat: 25.9 },
  { name: "McAllen", lon: -98.23, lat: 26.2 },
  { name: "Midland", lon: -102.08, lat: 32.0 },
  { name: "Waco", lon: -97.15, lat: 31.55 },
  { name: "Beaumont", lon: -94.13, lat: 30.08 },
  { name: "Las Cruces", lon: -106.76, lat: 32.32 },
  { name: "Lafayette", lon: -92.02, lat: 30.22 },
  { name: "Abilene", lon: -99.73, lat: 32.45 },
  { name: "Roswell", lon: -104.52, lat: 33.39 },
  { name: "Wichita Falls", lon: -98.49, lat: 33.91 },
];
