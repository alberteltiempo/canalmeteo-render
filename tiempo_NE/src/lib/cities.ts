// Ciudades principales del NORESTE de EEUU, bien distribuidas por la región, para
// rotular el mapa. Nombres en español donde aplica. Coordenadas lon/lat.
export type City = { name: string; lon: number; lat: number };

// Ordenadas por IMPORTANCIA (de mayor a menor). El orden es la prioridad: cuando
// dos rótulos se solapan en pantalla, gana el que va antes (el otro se descarta).
export const MAJOR_CITIES: City[] = [
  { name: "Nueva York", lon: -74.01, lat: 40.71 },
  { name: "Washington", lon: -77.04, lat: 38.91 },
  { name: "Filadelfia", lon: -75.16, lat: 39.95 },
  { name: "Boston", lon: -71.06, lat: 42.36 },
  { name: "Baltimore", lon: -76.61, lat: 39.29 },
  { name: "Pittsburgh", lon: -79.996, lat: 40.44 },
  { name: "Buffalo", lon: -78.87, lat: 42.89 },
  { name: "Providence", lon: -71.41, lat: 41.82 },
  { name: "Hartford", lon: -72.69, lat: 41.76 },
  { name: "Albany", lon: -73.76, lat: 42.65 },
  { name: "Rochester", lon: -77.61, lat: 43.16 },
  { name: "Portland", lon: -70.26, lat: 43.66 },
  { name: "Syracuse", lon: -76.15, lat: 43.05 },
  { name: "Manchester", lon: -71.46, lat: 42.99 },
  { name: "Burlington", lon: -73.21, lat: 44.48 },
  { name: "New Haven", lon: -72.93, lat: 41.31 },
  { name: "Worcester", lon: -71.8, lat: 42.26 },
  { name: "Springfield", lon: -72.59, lat: 42.1 },
  { name: "Allentown", lon: -75.49, lat: 40.6 },
  { name: "Harrisburg", lon: -76.88, lat: 40.27 },
  { name: "Scranton", lon: -75.66, lat: 41.41 },
  { name: "Wilmington", lon: -75.55, lat: 39.74 },
  { name: "Trenton", lon: -74.76, lat: 40.22 },
  { name: "Atlantic City", lon: -74.42, lat: 39.36 },
  { name: "Bangor", lon: -68.78, lat: 44.8 },
  { name: "Erie", lon: -80.09, lat: 42.13 },
  { name: "Binghamton", lon: -75.91, lat: 42.1 },
  { name: "Montpelier", lon: -72.58, lat: 44.26 },
  { name: "Augusta", lon: -69.78, lat: 44.31 },
  { name: "Concord", lon: -71.54, lat: 43.21 },
];
