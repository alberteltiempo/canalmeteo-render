// Sistema de diseño Canal Meteo TV
export const BRAND = {
  navy: "#22445B",
  navyDark: "#1a2f4a",
  navyDeep: "#0d1a26",
  blue: "#457A99",
  orange: "#F39C12",
  // Acento del producto Trópico
  red: "#c01818",
  redDeep: "#6e0c0c",
  white: "#ffffff",
};

export const LOGO_URL = "https://dev.canalmeteo.tv/logos/logo-canalmeteo-30.png";

// Escala Saffir-Simpson (igual que el frontend Tormenta)
export const TROP_CAT: Record<string, { color: string; letter: string }> = {
  TD: { color: "#5ebaff", letter: "D" },
  TS: { color: "#00c853", letter: "T" },
  H1: { color: "#ffeb3b", letter: "1" },
  H2: { color: "#ff9800", letter: "2" },
  H3: { color: "#ff5722", letter: "3" },
  H4: { color: "#e53935", letter: "4" },
  H5: { color: "#d500f9", letter: "5" },
};

// Colores de avisos/vigilancias NHC (campo tcww)
export const TROP_WW: Record<string, string> = {
  HWR: "#cc0000", // Aviso de huracán
  HWA: "#ff66cc", // Vigilancia de huracán
  TWR: "#1e6fff", // Aviso de tormenta tropical
  TWA: "#ffd000", // Vigilancia de tormenta tropical
  SSW: "#b026ff", // Aviso de marejada ciclónica
  SSA: "#db7ff5", // Vigilancia de marejada ciclónica
};

// Radios de viento
export const TROP_RADII: Record<number, string> = {
  34: "#ffd24a",
  50: "#ff8c00",
  64: "#e53935",
};
