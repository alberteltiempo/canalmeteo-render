// Ciudades principales de Noroeste, bien distribuidas por la región, para
// rotular el mapa. Nombres en español donde aplica. Coordenadas lon/lat.
export type City = { name: string; lon: number; lat: number };

// Ordenadas por IMPORTANCIA (de mayor a menor). El orden es la prioridad: cuando
// dos rótulos se solapan en pantalla, gana el que va antes (el otro se descarta).
export const MAJOR_CITIES: City[] = [
  { name: "Seattle", lon: -122.33, lat: 47.61 },
  { name: "Portland", lon: -122.68, lat: 45.52 },
  { name: "Boise", lon: -116.2, lat: 43.62 },
  { name: "Spokane", lon: -117.43, lat: 47.66 },
  { name: "Tacoma", lon: -122.44, lat: 47.25 },
  { name: "Salem", lon: -123.04, lat: 44.94 },
  { name: "Eugene", lon: -123.09, lat: 44.05 },
  { name: "Yakima", lon: -120.51, lat: 46.6 },
  { name: "Tri-Cities", lon: -119.14, lat: 46.21 },
  { name: "Bellingham", lon: -122.48, lat: 48.75 },
  { name: "Everett", lon: -122.2, lat: 47.98 },
  { name: "Olympia", lon: -122.9, lat: 47.04 },
  { name: "Medford", lon: -122.87, lat: 42.33 },
  { name: "Bend", lon: -121.31, lat: 44.06 },
  { name: "Idaho Falls", lon: -112.03, lat: 43.49 },
  { name: "Pocatello", lon: -112.44, lat: 42.86 },
  { name: "Twin Falls", lon: -114.46, lat: 42.56 },
  { name: "Lewiston", lon: -117.02, lat: 46.42 },
  { name: "Coeur d'Alene", lon: -116.78, lat: 47.68 },
  { name: "Astoria", lon: -123.83, lat: 46.19 },
  { name: "Walla Walla", lon: -118.34, lat: 46.06 },
];
