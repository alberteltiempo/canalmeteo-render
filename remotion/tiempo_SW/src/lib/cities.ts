// Ciudades principales de Suroeste, bien distribuidas por la región, para
// rotular el mapa. Nombres en español donde aplica. Coordenadas lon/lat.
export type City = { name: string; lon: number; lat: number };

// Ordenadas por IMPORTANCIA (de mayor a menor). El orden es la prioridad: cuando
// dos rótulos se solapan en pantalla, gana el que va antes (el otro se descarta).
export const MAJOR_CITIES: City[] = [
  { name: "Los Ángeles", lon: -118.24, lat: 34.05 },
  { name: "San Francisco", lon: -122.42, lat: 37.77 },
  { name: "San Diego", lon: -117.16, lat: 32.72 },
  { name: "Las Vegas", lon: -115.14, lat: 36.17 },
  { name: "Phoenix", lon: -112.07, lat: 33.45 },
  { name: "Sacramento", lon: -121.49, lat: 38.58 },
  { name: "Salt Lake City", lon: -111.89, lat: 40.76 },
  { name: "San José", lon: -121.89, lat: 37.34 },
  { name: "Fresno", lon: -119.77, lat: 36.75 },
  { name: "Tucson", lon: -110.97, lat: 32.22 },
  { name: "Reno", lon: -119.81, lat: 39.53 },
  { name: "Bakersfield", lon: -119.02, lat: 35.37 },
  { name: "Santa Bárbara", lon: -119.7, lat: 34.42 },
  { name: "Palm Springs", lon: -116.55, lat: 33.83 },
  { name: "Flagstaff", lon: -111.65, lat: 35.2 },
  { name: "Yuma", lon: -114.62, lat: 32.69 },
  { name: "St. George", lon: -113.58, lat: 37.1 },
  { name: "Provo", lon: -111.66, lat: 40.23 },
  { name: "Ogden", lon: -111.97, lat: 41.22 },
  { name: "Eureka", lon: -124.16, lat: 40.8 },
  { name: "Redding", lon: -122.39, lat: 40.59 },
  { name: "Modesto", lon: -121.0, lat: 37.64 },
  { name: "Monterey", lon: -121.89, lat: 36.6 },
  { name: "Elko", lon: -115.76, lat: 40.83 },
  { name: "Carson City", lon: -119.77, lat: 39.16 },
];
