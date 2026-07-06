import { ThemeMode } from "../types";

// Sistema de diseño Canal Meteo TV
export const BRAND = {
  navy: "#22445B",
  navyDark: "#1a2f4a",
  navyDeep: "#0d1a26",
  blue: "#457A99",
  blueVivid: "#1d6fb8",
  orange: "#F39C12",
  white: "#ffffff",
  // Modo Rojo del tiempo EEUU (tiempo severo / tornado / huracán).
  // Crimson deliberadamente distinto del rojo ladrillo de Trópico (#c01818).
  alertRed: "#d81e3f",
  alertRedDeep: "#7a0f23",
};

export const LOGO_URL = "https://dev.canalmeteo.tv/logos/logo-canalmeteo-30.png";

// Paleta dependiente del modo. En condiciones normales, navy/azul de marca;
// en Modo Rojo (tornado / tiempo severo / huracán), crimson de alerta.
export type Palette = {
  topicColor: string; // color de la TopicBar
  accent: string; // acentos (barras, puntos)
  openFrom: string; // degradado de la portada
  openMid: string;
  openTo: string;
};

export function palette(mode: ThemeMode): Palette {
  if (mode === "alert") {
    return {
      topicColor: BRAND.alertRed,
      accent: BRAND.orange,
      openFrom: BRAND.alertRed,
      openMid: BRAND.alertRedDeep,
      openTo: "#3a0610",
    };
  }
  return {
    topicColor: BRAND.blueVivid,
    accent: BRAND.orange,
    openFrom: BRAND.navyDark,
    openMid: BRAND.navy,
    openTo: BRAND.navyDeep,
  };
}

// ─── Categorías de vigilancia (NWS) → etiqueta + color + icono ───
// `tipo` es el campo interno del pipeline de alertas.
export type AlertCategoryMeta = { label: string; color: string; icon: string };

export const ALERT_CATEGORIES: Record<string, AlertCategoryMeta> = {
  tornado: { label: "Tornado", color: "#b026ff", icon: "🌪️" },
  tormenta: { label: "Tiempo severo", color: "#e74c3c", icon: "⛈️" },
  inundacion: { label: "Inundación", color: "#2e86de", icon: "🌊" },
  calor: { label: "Calor extremo", color: "#e67e22", icon: "🥵" },
  invierno: { label: "Tiempo invernal", color: "#5dade2", icon: "❄️" },
  costera: { label: "Costera", color: "#16a085", icon: "🌊" },
  viento: { label: "Viento", color: "#7f8c8d", icon: "💨" },
  fuego: { label: "Incendios", color: "#e67e22", icon: "🔥" },
};

export const ALERT_FALLBACK: AlertCategoryMeta = {
  label: "Otras vigilancias",
  color: "#95a5a6",
  icon: "⚠️",
};

export function alertCategoryMeta(tipo: string): AlertCategoryMeta {
  return ALERT_CATEGORIES[tipo] || ALERT_FALLBACK;
}
