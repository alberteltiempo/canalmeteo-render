// Variantes de base cartográfica para evaluar el look de broadcast de tiempo_CONUS.
// Cada variante cambia: estilo Mapbox, color de océano, tratamiento de la tierra
// (color plano o relieve/hillshade) y el estilo de los rótulos de ciudad.
// Se comparan en Remotion Studio (composiciones Mockup1…Mockup5) sin satélite,
// para juzgar la cartografía limpia que se ve en Radar/Alertas.

export type MockupVariant = {
  id: string;
  name: string;
  desc: string;
  style: string; // URL de estilo Mapbox
  ocean?: string; // recolorea el agua (fill water)
  landColor?: string; // recolorea tierra (land/background) — color plano
  relief?: boolean; // añade hillshade (relieve sombreado) sobre la tierra
  reliefExaggeration?: number; // 0–1, intensidad del sombreado
  borderColor: string; // fronteras (países/estados)
  borderOpacity?: number;
  cityDotColor: string; // punto del rótulo de ciudad
  cityTextColor: string; // texto del rótulo de ciudad
  // Color del texto del título superpuesto (para legibilidad sobre la base).
  titleColor: string;
  // ── Opcionales para el look "sistema de TV" (globo) ──
  projection?: "globe" | "mercator"; // por defecto mercator (plano)
  atmosphere?: boolean; // espacio negro + atmósfera azul (setFog)
  coastGlow?: string; // halo costero (agua somera brillante)
  coastBorder?: string; // línea de costa marcada como frontera de país
  coastBorderWidth?: number;
  hillshadeShadow?: string; // sombra del relieve (override del valor por defecto)
  hillshadeHighlight?: string; // realce del relieve
  center?: [number, number]; // encuadre manual (necesario en globo)
  zoom?: number;
  showCities?: boolean; // por defecto true; el look de sistema va sin rótulos
  // Raster de relieve sombreado (PNG gris en public/) drapeado bajo el agua.
  // Da textura de montañas nítida, imposible con el hillshade vectorial a escala
  // continental. Bounds en RELIEF_RASTER_BOUNDS (MapMockup).
  reliefRaster?: string;
  // GeoJSON de batimetría (bandas de profundidad de Natural Earth en public/).
  // Colorea el océano de claro (somero) a marino (profundo).
  bathymetry?: string;
};

const W = "rgba(255,255,255,0.95)";

export const MOCKUPS: MockupVariant[] = [
  {
    id: "navy",
    name: "1 · Navy marca",
    desc: "Base oscura, océano azul marino de marca, tierra plana oscura, fronteras blancas.",
    style: "mapbox://styles/mapbox/dark-v11",
    ocean: "#2c5066",
    landColor: "#16242e",
    borderColor: W,
    borderOpacity: 0.95,
    cityDotColor: "#ffffff",
    cityTextColor: "#ffffff",
    titleColor: "#ffffff",
  },
  {
    id: "white-land",
    name: "2 · Tierra blanca",
    desc: "Mapa claro clásico de TV: tierra blanca/gris, océano azul suave, fronteras grises.",
    style: "mapbox://styles/mapbox/light-v11",
    ocean: "#a9cee0",
    landColor: "#f2f0ea",
    borderColor: "rgba(40,70,90,0.85)",
    borderOpacity: 0.85,
    cityDotColor: "#22445B",
    cityTextColor: "#16242e",
    titleColor: "#16242e",
  },
  {
    id: "white-relief",
    name: "3 · Tierra blanca + relieve",
    desc: "Base clara con relieve sombreado (hillshade): se ven montañas, océano azul suave.",
    style: "mapbox://styles/mapbox/light-v11",
    ocean: "#9ec7dd",
    landColor: "#efe9df",
    relief: true,
    reliefExaggeration: 0.85,
    borderColor: "rgba(40,70,90,0.9)",
    borderOpacity: 0.9,
    cityDotColor: "#22445B",
    cityTextColor: "#16242e",
    titleColor: "#16242e",
  },
  {
    id: "dark-relief",
    name: "4 · Relieve oscuro cine",
    desc: "Base oscura con relieve sombreado, océano teal profundo, fronteras y ciudades brillantes.",
    style: "mapbox://styles/mapbox/dark-v11",
    ocean: "#10303f",
    landColor: "#1b2b22",
    relief: true,
    reliefExaggeration: 1,
    borderColor: "rgba(255,255,255,0.95)",
    borderOpacity: 0.95,
    cityDotColor: "#F39C12",
    cityTextColor: "#ffffff",
    titleColor: "#ffffff",
  },
  {
    id: "satellite",
    name: "5 · Satélite real (ref.)",
    desc: "Imagen de satélite real de Mapbox como referencia de terreno, fronteras y ciudades blancas.",
    style: "mapbox://styles/mapbox/satellite-v9",
    // sin recolor de océano/tierra: terreno real
    borderColor: "rgba(255,255,255,0.9)",
    borderOpacity: 0.9,
    cityDotColor: "#ffffff",
    cityTextColor: "#ffffff",
    titleColor: "#ffffff",
  },
];

// ─── Iteración sobre "4 · Relieve oscuro cine" ───
// Albert quiere el mismo look pero con tierra y océano más claros. Gradación de
// 4 pasos: de carbón (menos claro) a pizarra clara (más claro). Mantiene relieve,
// fronteras blancas y ciudades naranjas de marca.
const RELIEF_BASE = {
  style: "mapbox://styles/mapbox/dark-v11",
  relief: true,
  reliefExaggeration: 0.75,
  borderColor: "rgba(255,255,255,0.95)",
  borderOpacity: 0.95,
  cityDotColor: "#F39C12",
  cityTextColor: "#ffffff",
  titleColor: "#ffffff",
} as const;

export const RELIEF_MOCKUPS: MockupVariant[] = [
  {
    ...RELIEF_BASE,
    id: "relief-carbon",
    name: "A · Relieve carbón",
    desc: "Tierra gris carbón, océano azul noche. El más oscuro de los cuatro.",
    landColor: "#3d4c43",
    ocean: "#244a60",
  },
  {
    ...RELIEF_BASE,
    id: "relief-pizarra",
    name: "B · Relieve pizarra",
    desc: "Tierra gris pizarra media, océano azul acero. Un paso más claro.",
    landColor: "#526157",
    ocean: "#316277",
  },
  {
    ...RELIEF_BASE,
    id: "relief-salvia",
    name: "C · Relieve salvia",
    desc: "Tierra verde-gris media-clara, océano azul medio. Equilibrado.",
    landColor: "#67766b",
    ocean: "#3d7088",
  },
  {
    ...RELIEF_BASE,
    id: "relief-claro",
    name: "D · Relieve claro",
    desc: "Tierra pizarra clara, océano azul claro. El más claro de los cuatro.",
    landColor: "#808d82",
    ocean: "#4d86a0",
  },
];

// ─── Look "sistema de TV" (referencia tierra.png) ───
// Globo 3D sobre espacio negro con atmósfera azul, tierra en grises con relieve
// y océano azul vivo con halo costero (agua somera brillante). Sin rótulos, como
// los sistemas Baron/Max. El degradado real por profundidad (batimetría) no lo
// trae Mapbox; se aproxima con el halo costero + oscurecimiento del horizonte.
export const SYSTEM_MOCKUPS: MockupVariant[] = [
  {
    id: "sistema",
    name: "Sistema TV (plano)",
    desc: "Mapa plano: relieve sombreado real (raster), océano azul + halo costero, fronteras grises. Estilo Baron/Max.",
    style: "mapbox://styles/mapbox/dark-v11",
    landColor: "#c6c9cb", // fallback gris para tierra fuera del raster
    ocean: "#5aa9e2", // azul claro base (lagos y agua fuera de batimetría)
    reliefRaster: "relief_conus.png",
    bathymetry: "bathymetry.geojson",
    coastBorder: "rgba(55,65,75,0.9)", // costa marcada como frontera
    coastBorderWidth: 1.2,
    projection: "mercator",
    showCities: false,
    borderColor: "rgba(70,80,90,0.85)",
    borderOpacity: 0.85,
    cityDotColor: "#ffffff",
    cityTextColor: "#ffffff",
    titleColor: "#cfd8e0",
  },
];

export function mockupById(id: string): MockupVariant {
  const all = [...MOCKUPS, ...RELIEF_MOCKUPS, ...SYSTEM_MOCKUPS];
  return all.find((m) => m.id === id) || all[0];
}
