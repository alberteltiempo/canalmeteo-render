// Ciudades principales de FLORIDA, bien distribuidas por el estado, para
// rotular el mapa. Nombres en español donde aplica. Coordenadas lon/lat.
export type City = { name: string; lon: number; lat: number };

// Ordenadas por IMPORTANCIA (de mayor a menor). El orden es la prioridad: cuando
// dos rótulos se solapan en pantalla, gana el que va antes (el otro se descarta).
export const MAJOR_CITIES: City[] = [
  { name: "Miami", lon: -80.19, lat: 25.76 },
  { name: "Orlando", lon: -81.38, lat: 28.54 },
  { name: "Tampa", lon: -82.46, lat: 27.95 },
  { name: "Jacksonville", lon: -81.66, lat: 30.33 },
  { name: "Tallahassee", lon: -84.28, lat: 30.44 },
  { name: "Fort Lauderdale", lon: -80.14, lat: 26.12 },
  { name: "West Palm Beach", lon: -80.05, lat: 26.72 },
  { name: "Fort Myers", lon: -81.87, lat: 26.64 },
  { name: "Cayo Hueso", lon: -81.78, lat: 24.56 },
  { name: "Pensacola", lon: -87.22, lat: 30.42 },
  { name: "St. Petersburg", lon: -82.64, lat: 27.77 },
  { name: "Sarasota", lon: -82.53, lat: 27.34 },
  { name: "Daytona Beach", lon: -81.02, lat: 29.21 },
  { name: "Gainesville", lon: -82.32, lat: 29.65 },
  { name: "Naples", lon: -81.79, lat: 26.14 },
  { name: "Panama City", lon: -85.66, lat: 30.16 },
  { name: "Melbourne", lon: -80.61, lat: 28.08 },
  { name: "Ocala", lon: -82.14, lat: 29.19 },
  { name: "Lakeland", lon: -81.95, lat: 28.04 },
  { name: "Port St. Lucie", lon: -80.36, lat: 27.27 },
  { name: "St. Augustine", lon: -81.31, lat: 29.9 },
  { name: "Kissimmee", lon: -81.41, lat: 28.29 },
];
