// Base cartográfica PROPIA del trópico (sin Mapbox): MapLibre + Natural Earth
// autoalojado en public/basemap/ (recorte 165°O–5°E · 10°S–66°N, ver
// scripts de generación en la auditoría 2026-08). Reproduce el look oscuro que
// daba dark-v11 recoloreado: tierra carbón, océano #3d5a6e con batimetría,
// fronteras finas y rótulos blancos con halo.
//
// Los IDS DE CAPA están elegidos para que los helpers existentes sigan
// funcionando sin cambios: raiseBorders filtra /admin/&&/boundary/,
// enhanceLabels/raiseCityLabels buscan settlement-*-label. No renombrar.
import { staticFile } from "remotion";

export const OCEAN_BASE = "#3d5a6e";
export const LAND_DARK = "#232a31";

// Rampa de batimetría oscura: #3d5a6e en plataforma → azul noche en fondo.
// Mantiene contraste con el cono/trayectoria blancos y el satélite IR.
const BATHY_RAMP: (number | string)[] = [
  0, "#41637a",
  200, OCEAN_BASE,
  1000, "#375163",
  2000, "#314857",
  3000, "#2b404d",
  4000, "#263843",
  6000, "#1c2a33",
  8000, "#16222a",
];

const asset = (f: string) => staticFile(`basemap/${f}`);

// Estilo completo y AUTOCONTENIDO (cero peticiones externas en render).
export function buildTropStyle(): any {
  return {
    version: 8,
    glyphs: staticFile("basemap") + "/glyphs/{fontstack}/{range}.pbf",
    sources: {
      land: { type: "geojson", data: asset("land.geojson") },
      ocean: { type: "geojson", data: asset("ocean.geojson") },
      bathy: { type: "geojson", data: asset("bathymetry.geojson") },
      admin0: { type: "geojson", data: asset("admin0.geojson") },
      admin1: { type: "geojson", data: asset("admin1.geojson") },
      lakes: { type: "geojson", data: asset("lakes.geojson") },
      places: { type: "geojson", data: asset("places.geojson") },
    },
    layers: [
      { id: "background", type: "background", paint: { "background-color": OCEAN_BASE } },
      {
        id: "bathy",
        type: "fill",
        source: "bathy",
        paint: {
          "fill-color": ["interpolate", ["linear"], ["get", "depth"], ...BATHY_RAMP],
          "fill-opacity": 1,
          "fill-antialias": false,
        },
      },
      { id: "land-fill", type: "fill", source: "land", paint: { "fill-color": LAND_DARK } },
      { id: "lakes-fill", type: "fill", source: "lakes", paint: { "fill-color": OCEAN_BASE } },
      {
        id: "coastline",
        type: "line",
        source: "land",
        paint: { "line-color": "rgba(255,255,255,0.30)", "line-width": 0.9 },
      },
      {
        id: "admin-1-boundary",
        type: "line",
        source: "admin1",
        paint: { "line-color": "rgba(255,255,255,0.26)", "line-width": 0.8 },
      },
      {
        id: "admin-0-boundary",
        type: "line",
        source: "admin0",
        paint: { "line-color": "rgba(255,255,255,0.45)", "line-width": 1.3 },
      },
      {
        id: "settlement-major-label",
        type: "symbol",
        source: "places",
        filter: ["any", ["==", ["get", "cap"], 1], ["<=", ["get", "sr"], 3]],
        layout: {
          "text-field": ["get", "name"],
          "text-font": ["Noto Sans Regular"],
          "text-size": 24,
          "symbol-sort-key": ["get", "sr"],
          "text-padding": 8,
        },
        paint: {
          "text-color": "#ffffff",
          "text-halo-color": "rgba(0,0,0,0.85)",
          "text-halo-width": 1.8,
        },
      },
      {
        id: "settlement-minor-label",
        type: "symbol",
        source: "places",
        minzoom: 4.6,
        filter: ["all", ["==", ["get", "cap"], 0], [">", ["get", "sr"], 3]],
        layout: {
          "text-field": ["get", "name"],
          "text-font": ["Noto Sans Regular"],
          "text-size": 17,
          "symbol-sort-key": ["get", "sr"],
          "text-padding": 6,
        },
        paint: {
          "text-color": "#ffffff",
          "text-halo-color": "rgba(0,0,0,0.85)",
          "text-halo-width": 1.6,
        },
      },
    ],
  };
}

// Línea de costa realzada POR ENCIMA de un raster (satélite/lluvia).
export function addCoastlineOverRaster(map: any) {
  if (map.getLayer("cm-coastline")) return;
  try {
    map.addLayer({
      id: "cm-coastline",
      type: "line",
      source: "land",
      paint: { "line-color": "rgba(255,255,255,0.85)", "line-width": 1.6, "line-blur": 0.2 },
    });
  } catch {
    /* noop */
  }
}

// Atenúa el raster sobre el agua: océano por encima con opacidad parcial.
export function addOceanDim(map: any, dim: number, color: string) {
  if (map.getLayer("cm-water-dim")) return;
  try {
    map.addLayer({
      id: "cm-water-dim",
      type: "fill",
      source: "ocean",
      paint: { "fill-color": color, "fill-opacity": dim },
    });
  } catch {
    /* noop */
  }
}
