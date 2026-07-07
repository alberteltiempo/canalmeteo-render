// Ciudades principales de Medio Oeste, bien distribuidas por la región, para
// rotular el mapa. Nombres en español donde aplica. Coordenadas lon/lat.
export type City = { name: string; lon: number; lat: number };

// Ordenadas por IMPORTANCIA (de mayor a menor). El orden es la prioridad: cuando
// dos rótulos se solapan en pantalla, gana el que va antes (el otro se descarta).
export const MAJOR_CITIES: City[] = [
  { name: "Chicago", lon: -87.63, lat: 41.88 },
  { name: "Detroit", lon: -83.05, lat: 42.33 },
  { name: "Mineápolis", lon: -93.27, lat: 44.98 },
  { name: "San Luis", lon: -90.2, lat: 38.63 },
  { name: "Kansas City", lon: -94.58, lat: 39.1 },
  { name: "Indianápolis", lon: -86.16, lat: 39.77 },
  { name: "Columbus", lon: -82.99, lat: 39.96 },
  { name: "Cleveland", lon: -81.69, lat: 41.5 },
  { name: "Cincinnati", lon: -84.51, lat: 39.1 },
  { name: "Milwaukee", lon: -87.91, lat: 43.04 },
  { name: "Des Moines", lon: -93.63, lat: 41.59 },
  { name: "Madison", lon: -89.4, lat: 43.07 },
  { name: "Grand Rapids", lon: -85.67, lat: 42.96 },
  { name: "Toledo", lon: -83.54, lat: 41.65 },
  { name: "Dayton", lon: -84.19, lat: 39.76 },
  { name: "Duluth", lon: -92.1, lat: 46.79 },
  { name: "Fort Wayne", lon: -85.14, lat: 41.08 },
  { name: "Green Bay", lon: -88.02, lat: 44.51 },
  { name: "Springfield", lon: -93.29, lat: 37.21 },
  { name: "Cedar Rapids", lon: -91.66, lat: 41.98 },
  { name: "Evansville", lon: -87.57, lat: 37.97 },
  { name: "Peoria", lon: -89.59, lat: 40.69 },
  { name: "Rochester", lon: -92.46, lat: 44.02 },
  { name: "Lansing", lon: -84.56, lat: 42.73 },
  { name: "Akron", lon: -81.52, lat: 41.08 },
  { name: "Sioux City", lon: -96.4, lat: 42.5 },
];
