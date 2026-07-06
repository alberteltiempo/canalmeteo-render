// Ciudades principales del SURESTE de EEUU, bien distribuidas por la región, para
// rotular el mapa. Nombres en español donde aplica. Coordenadas lon/lat.
export type City = { name: string; lon: number; lat: number };

// Ordenadas por IMPORTANCIA (de mayor a menor). El orden es la prioridad: cuando
// dos rótulos se solapan en pantalla, gana el que va antes (el otro se descarta).
export const MAJOR_CITIES: City[] = [
  { name: "Atlanta", lon: -84.39, lat: 33.75 },
  { name: "Charlotte", lon: -80.84, lat: 35.23 },
  { name: "Nashville", lon: -86.78, lat: 36.16 },
  { name: "Memphis", lon: -90.05, lat: 35.15 },
  { name: "Raleigh", lon: -78.64, lat: 35.78 },
  { name: "Richmond", lon: -77.46, lat: 37.54 },
  { name: "Norfolk", lon: -76.29, lat: 36.85 },
  { name: "Birmingham", lon: -86.8, lat: 33.52 },
  { name: "Louisville", lon: -85.76, lat: 38.25 },
  { name: "Columbia", lon: -81.03, lat: 34.0 },
  { name: "Knoxville", lon: -83.92, lat: 35.96 },
  { name: "Charleston", lon: -79.93, lat: 32.78 },
  { name: "Savannah", lon: -81.1, lat: 32.08 },
  { name: "Jackson", lon: -90.18, lat: 32.3 },
  { name: "Mobile", lon: -88.04, lat: 30.69 },
  { name: "Montgomery", lon: -86.3, lat: 32.38 },
  { name: "Chattanooga", lon: -85.31, lat: 35.05 },
  { name: "Lexington", lon: -84.5, lat: 38.05 },
  { name: "Greensboro", lon: -79.79, lat: 36.07 },
  { name: "Huntsville", lon: -86.59, lat: 34.73 },
  { name: "Augusta", lon: -82.01, lat: 33.47 },
  { name: "Greenville", lon: -82.39, lat: 34.85 },
  { name: "Asheville", lon: -82.55, lat: 35.6 },
  { name: "Wilmington", lon: -77.95, lat: 34.23 },
  { name: "Roanoke", lon: -79.94, lat: 37.27 },
  { name: "Macon", lon: -83.63, lat: 32.84 },
  { name: "Tupelo", lon: -88.7, lat: 34.26 },
  { name: "Paducah", lon: -88.6, lat: 37.08 },
];
