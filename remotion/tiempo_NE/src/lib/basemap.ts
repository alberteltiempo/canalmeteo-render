// Base cartográfica "sistema de TV" de Canal Meteo (look elegido en los mockups):
// tierra gris con relieve sombreado real (raster Natural Earth), océano azul con
// batimetría real, costas marcadas como fronteras y fronteras grises. Mapa plano
// (mercator). Compartido por la base de producción (SatMap) y los mockups.
//
// Desde 2026-08: SIN MAPBOX. buildSystemStyle() devuelve un estilo MapLibre
// autocontenido (Natural Earth en public/basemap/ + relief/batimetría propios).
// Los helpers antiguos se conservan para los mockups; en producción ya no hacen
// falta porque el estilo nace con la base puesta.
import { staticFile } from "remotion";

// Bounds geográficos del raster de relieve y de la batimetría (recorte Natural
// Earth). DEBEN coincidir con el -projwin/-clipsrc usado al generar los assets
// en public/ (relief_conus.png, bathymetry.geojson).
export const RELIEF_RASTER_BOUNDS = { west: -142, north: 60, east: -52, south: 2 };

// Paleta del sistema.
export const BASEMAP = {
  ocean: "#2e6088", // azul base oscuro (lagos / agua fuera de batimetría)
  land: "#c6c9cb", // gris de tierra (fallback fuera del raster de relieve)
  coastBorder: "rgba(55,65,75,0.9)", // costa marcada como frontera
  coastBorderWidth: 1.2,
  border: "rgba(70,80,90,0.85)", // fronteras de países/estados
  borderOpacity: 0.85,
};

// Rampa de profundidad OSCURA: azul medio en plataformas someras → azul marino
// casi negro en fondo profundo. Da contraste para el satélite blanco y los datos.
export const BATHY_RAMP: (number | string)[] = [
  0, "#3a76a0",
  200, "#2e6088",
  1000, "#264f72",
  2000, "#20425f",
  3000, "#1b3850",
  4000, "#162f44",
  5000, "#122838",
  6000, "#0e202e",
  8000, "#0a1822",
];

// ─── Helpers de recoloreado / capas ───

export function setWaterColor(map: any, ocean: string) {
  (map.getStyle()?.layers || []).forEach((l: any) => {
    if (l.type === "fill" && /water/.test(l.id) && !/waterway/.test(l.id)) {
      try {
        map.setPaintProperty(l.id, "fill-color", ocean);
      } catch {
        /* noop */
      }
    }
  });
}

// La tierra base en dark-v11/light-v11 es una capa `background` con id "land";
// encima hay rellenos landuse/landcover que también recoloreamos.
export function setLandColor(map: any, land: string) {
  (map.getStyle()?.layers || []).forEach((l: any) => {
    try {
      if (l.type === "background") {
        map.setPaintProperty(l.id, "background-color", land);
      } else if (l.type === "fill" && /^(land|landuse|landcover)/.test(l.id)) {
        map.setPaintProperty(l.id, "fill-color", land);
      }
    } catch {
      /* noop */
    }
  });
}

// Raster de relieve sombreado gris drapeado bajo la capa de agua → textura de
// montañas nítida (imposible con hillshade vectorial a escala continental).
export function addReliefRaster(map: any, url: string) {
  if (map.getLayer("cm-relief")) return;
  try {
    const b = RELIEF_RASTER_BOUNDS;
    map.addSource("cm-relief", {
      type: "image",
      url,
      coordinates: [
        [b.west, b.north],
        [b.east, b.north],
        [b.east, b.south],
        [b.west, b.south],
      ],
    });
    const firstWater = (map.getStyle()?.layers || []).find(
      (l: any) => l.type === "fill" && /water/.test(l.id) && !/waterway/.test(l.id)
    )?.id;
    map.addLayer(
      {
        id: "cm-relief",
        type: "raster",
        source: "cm-relief",
        paint: {
          "raster-fade-duration": 0,
          "raster-contrast": 0.18,
          "raster-brightness-max": 0.92,
        },
      },
      firstWater
    );
  } catch {
    /* noop */
  }
}

// Batimetría: colorea el océano por profundidad (bandas Natural Earth). Features
// ordenadas de somero a profundo, así el profundo se dibuja encima.
export function addBathymetry(map: any, url: string) {
  if (map.getLayer("cm-bathy")) return;
  try {
    map.addSource("cm-bathy", { type: "geojson", data: url });
    map.addLayer({
      id: "cm-bathy",
      type: "fill",
      source: "cm-bathy",
      paint: {
        "fill-color": ["interpolate", ["linear"], ["get", "depth"], ...BATHY_RAMP] as any,
        "fill-opacity": 1,
        "fill-antialias": true,
      },
    });
  } catch {
    /* noop */
  }
}

// Frontera de costa: línea nítida sobre el límite del agua (costas marcadas como
// fronteras de país).
export function addCoastBorder(map: any, color: string, width: number) {
  if (map.getLayer("cm-coast-border")) return;
  try {
    map.addLayer({
      id: "cm-coast-border",
      type: "line",
      source: "composite",
      "source-layer": "water",
      paint: { "line-color": color, "line-width": width, "line-opacity": 0.9 },
    });
  } catch {
    /* noop */
  }
}

// Sube y realza las fronteras (países y estados) por encima de la base.
export function raiseBorders(map: any, color: string, opacity: number) {
  (map.getStyle()?.layers || [])
    .filter(
      (l: any) =>
        l.type === "line" && /admin/.test(l.id) && /boundary/.test(l.id) && !/bg/.test(l.id)
    )
    .forEach((l: any) => {
      try {
        map.moveLayer(l.id);
        const isCountry = /admin-0/.test(l.id);
        map.setPaintProperty(l.id, "line-color", color);
        map.setPaintProperty(l.id, "line-width", isCountry ? 5.5 : 5.0);
        map.setPaintProperty(l.id, "line-opacity", isCountry ? opacity : opacity * 0.95);
      } catch {
        /* noop */
      }
    });
}

// Oculta los rótulos automáticos de Mapbox (estados, países, carreteras).
export function hideAutoLabels(map: any) {
  (map.getStyle()?.layers || []).forEach((l: any) => {
    if (l.type === "symbol" && /label/.test(l.id)) {
      try {
        map.setLayoutProperty(l.id, "visibility", "none");
      } catch {
        /* noop */
      }
    }
  });
}

// Reactiva SOLO los rótulos de poblaciones (ciudades/pueblos) de Mapbox y los
// estiliza en blanco con halo oscuro para que se lean sobre la base gris. Útil en
// mapas con zoom a una zona concreta (p. ej. el epicentro de un terremoto), donde
// los marcadores fijos de CONUS (MAJOR_CITIES) no llegan. Llamar DESPUÉS de
// applyBaseMap (que oculta todos los rótulos).
export function showPlaceLabels(map: any) {
  (map.getStyle()?.layers || []).forEach((l: any) => {
    if (l.type !== "symbol") return;
    // Solo poblaciones MENORES (pueblos): las grandes ya las pone MAJOR_CITIES con
    // el estilo broadcast (nombre + punto), así no se duplican. Se omiten también
    // las subdivisiones (barrios). Esto rellena contexto donde MAJOR_CITIES (lista
    // CONUS) no llega.
    if (!/settlement-minor-label|place-town/i.test(l.id)) return;
    try {
      map.setLayoutProperty(l.id, "visibility", "visible");
      map.setLayoutProperty(l.id, "text-size", 20);
      map.setPaintProperty(l.id, "text-color", "#ffffff");
      map.setPaintProperty(l.id, "text-halo-color", "rgba(0,0,0,0.9)");
      map.setPaintProperty(l.id, "text-halo-width", 1.8);
    } catch {
      /* noop */
    }
  });
}

// Estilo MapLibre completo y AUTOCONTENIDO con la base "sistema" ya puesta:
// cero peticiones externas en render. Ids de capa compatibles con los helpers
// (cm-relief/cm-bathy, admin-*-boundary, settlement-minor-label).
export function buildSystemStyle(): any {
  const b = RELIEF_RASTER_BOUNDS;
  const asset = (f: string) => staticFile(`basemap/${f}`);
  return {
    version: 8,
    glyphs: staticFile("basemap") + "/glyphs/{fontstack}/{range}.pbf",
    sources: {
      land: { type: "geojson", data: asset("land.geojson") },
      ocean: { type: "geojson", data: asset("ocean.geojson") },
      "cm-bathy": { type: "geojson", data: staticFile("bathymetry.geojson") },
      admin0: { type: "geojson", data: asset("admin0.geojson") },
      admin1: { type: "geojson", data: asset("admin1.geojson") },
      lakes: { type: "geojson", data: asset("lakes.geojson") },
      places: { type: "geojson", data: asset("places.geojson") },
      "cm-relief": {
        type: "image",
        url: staticFile("relief_conus.png"),
        coordinates: [
          [b.west, b.north],
          [b.east, b.north],
          [b.east, b.south],
          [b.west, b.south],
        ],
      },
    },
    layers: [
      // Tierra gris de fondo; el relieve se drapea encima y la batimetría tapa
      // el océano (mismo orden visual que la pila Mapbox original).
      { id: "land", type: "background", paint: { "background-color": BASEMAP.land } },
      {
        id: "cm-relief",
        type: "raster",
        source: "cm-relief",
        paint: {
          "raster-fade-duration": 0,
          "raster-contrast": 0.18,
          "raster-brightness-max": 0.92,
        },
      },
      {
        id: "cm-bathy",
        type: "fill",
        source: "cm-bathy",
        paint: {
          "fill-color": ["interpolate", ["linear"], ["get", "depth"], ...BATHY_RAMP],
          "fill-opacity": 1,
          "fill-antialias": true,
        },
      },
      { id: "lakes-fill", type: "fill", source: "lakes", paint: { "fill-color": BASEMAP.ocean } },
      {
        id: "cm-coast-border",
        type: "line",
        source: "land",
        paint: {
          "line-color": BASEMAP.coastBorder,
          "line-width": BASEMAP.coastBorderWidth,
          "line-opacity": 0.9,
        },
      },
      {
        id: "admin-1-boundary",
        type: "line",
        source: "admin1",
        paint: {
          "line-color": BASEMAP.border,
          "line-width": 1.6,
          "line-opacity": BASEMAP.borderOpacity * 0.95,
        },
      },
      {
        id: "admin-0-boundary",
        type: "line",
        source: "admin0",
        paint: {
          "line-color": BASEMAP.border,
          "line-width": 2.2,
          "line-opacity": BASEMAP.borderOpacity,
        },
      },
      // Rótulos de poblaciones menores: apagados por defecto (las ciudades del
      // segmento las ponen los marcadores curados); showPlaceLabels los enciende
      // en mapas con zoom (p. ej. terremoto).
      {
        id: "settlement-minor-label",
        type: "symbol",
        source: "places",
        filter: [">", ["get", "sr"], 3],
        layout: {
          "text-field": ["get", "name"],
          "text-font": ["Noto Sans Regular"],
          "text-size": 20,
          "symbol-sort-key": ["get", "sr"],
          "text-padding": 6,
          visibility: "none",
        },
        paint: {
          "text-color": "#ffffff",
          "text-halo-color": "rgba(0,0,0,0.9)",
          "text-halo-width": 1.8,
        },
      },
    ],
  };
}

// Compat: la base ya viene puesta en buildSystemStyle(); se mantiene por los
// puntos de llamada existentes (SatMap/CondicionesNow/mockups).
export function applyBaseMap(_map: any) {
  /* la base ya está en el estilo */
}
