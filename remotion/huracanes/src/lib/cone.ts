import maplibregl from "maplibre-gl";
import { fetchGeoJSON, tropMarkerSVG, tropWWColor } from "./cdn";
import { TROP_RADII } from "./theme";
import { catKeyFromKt, ktToMph, localizeDatelbl } from "./tropical";
import { Storm } from "../types";

export type ConeMarker = { inner: HTMLDivElement; appear: number };

// Tamaños del marcador de punto de pronóstico. La escena del cono (TropMap) usa
// el grande (pase de legibilidad móvil); la de lluvia el compacto.
export type MarkerStyle = { hu: number; other: number; font: number; subFont: number };
export const MARKER_COMPACT: MarkerStyle = { hu: 72, other: 58, font: 18, subFont: 14 };
export const MARKER_BIG: MarkerStyle = { hu: 84, other: 68, font: 20, subFont: 16 };

export type DrawConeResult = { markers: ConeMarker[]; coneGj: any | null };

// Dibuja cono + trayectoria + avisos + puntos de pronóstico de una tormenta
// sobre un mapa Mapbox ya cargado. Capas con opacidad 0 (se revelan con
// revealCone). Devuelve los marcadores de puntos (para animarlos) y el GeoJSON
// del cono (para encuadres). Cada capa es opcional: si su fetch falla
// (fetchGeoJSON → null) se salta y el resto se dibuja igual.
// Reutilizado por la escena del cono (TropMap) y la de lluvia (SatMap).
export async function drawStormCone(
  map: maplibregl.Map,
  storm: Storm,
  opts: {
    beforeId?: string;
    ptStart: number;
    ptStagger: number;
    idPrefix?: string;
    skipPoints?: boolean;
    markerStyle?: MarkerStyle;
    // Extensión ACTUAL de los vientos 34/50/64 kt (advisory_wind, tau=0) —
    // solo en la escena de trayectoria; en la de lluvia taparía el ráster.
    windField?: boolean;
  }
): Promise<DrawConeResult> {
  const L = storm.layers;
  if (!L) return { markers: [], coneGj: null };
  const before = opts.beforeId;
  const pfx = opts.idPrefix ?? "cn";
  const ms = opts.markerStyle ?? MARKER_COMPACT;
  const markers: ConeMarker[] = [];
  let coneGj: any | null = null;
  try {
    if (L.cone) {
      coneGj = await fetchGeoJSON(L.cone);
      if (coneGj) {
        map.addSource(`${pfx}-cone-${storm.id}`, { type: "geojson", data: coneGj });
        map.addLayer(
          {
            id: `${pfx}-cone-f`,
            type: "fill",
            source: `${pfx}-cone-${storm.id}`,
            paint: { "fill-color": "#ffffff", "fill-opacity": 0 },
          },
          before
        );
        map.addLayer(
          {
            id: `${pfx}-cone-b`,
            type: "line",
            source: `${pfx}-cone-${storm.id}`,
            paint: {
              "line-color": "#ffffff",
              "line-width": 1.5,
              "line-opacity": 0,
              "line-dasharray": [2, 1.5],
            },
          },
          before
        );
      }
    }
    if (opts.windField && L.advisory_wind) {
      const gj = await fetchGeoJSON(L.advisory_wind);
      if (gj) {
        // Color por radio (34/50/64 kt). Los features vienen del NHC ordenados
        // de mayor a menor extensión (34→64), así el 64 kt pinta encima.
        (gj.features || []).forEach((f: any) => {
          f.properties = f.properties || {};
          f.properties._c = TROP_RADII[f.properties.radii as number] || "#ffd24a";
        });
        map.addSource(`${pfx}-wind-${storm.id}`, { type: "geojson", data: gj });
        map.addLayer(
          {
            id: `${pfx}-wind-f`,
            type: "fill",
            source: `${pfx}-wind-${storm.id}`,
            paint: { "fill-color": ["get", "_c"], "fill-opacity": 0 },
          },
          before
        );
        map.addLayer(
          {
            id: `${pfx}-wind-l`,
            type: "line",
            source: `${pfx}-wind-${storm.id}`,
            paint: { "line-color": ["get", "_c"], "line-width": 1.5, "line-opacity": 0 },
          },
          before
        );
      }
    }
    if (L.track) {
      const gj = await fetchGeoJSON(L.track);
      if (gj) {
        map.addSource(`${pfx}-track-${storm.id}`, { type: "geojson", data: gj });
        map.addLayer(
          {
            id: `${pfx}-track-l`,
            type: "line",
            source: `${pfx}-track-${storm.id}`,
            paint: {
              "line-color": "#ffffff",
              "line-width": 2.5,
              "line-opacity": 0,
              "line-dasharray": [1.5, 1],
            },
          },
          before
        );
      }
    }
    if (L.ww) {
      const gj = await fetchGeoJSON(L.ww);
      if (gj) {
        (gj.features || []).forEach((f: any) => {
          f.properties = f.properties || {};
          f.properties._c = tropWWColor(f.properties.tcww);
        });
        map.addSource(`${pfx}-ww-${storm.id}`, { type: "geojson", data: gj });
        map.addLayer({
          id: `${pfx}-ww-l`,
          type: "line",
          source: `${pfx}-ww-${storm.id}`,
          paint: { "line-color": ["get", "_c"], "line-width": 6, "line-opacity": 0 },
        });
      }
    }
    if (L.points && !opts.skipPoints) {
      const gj = await fetchGeoJSON(L.points);
      (gj?.features || []).forEach((f: any, i: number) => {
        const p = f.properties || {};
        const ck = catKeyFromKt(p.maxwind);
        const isHU = /^H[1-5]$/.test(ck);
        const size = isHU ? ms.hu : ms.other;
        const mph = ktToMph(p.maxwind);
        const dl = p.datelbl || "";
        const root = document.createElement("div");
        const inner = document.createElement("div");
        inner.style.cssText = `position:relative;width:${size}px;height:${size}px;opacity:0;transform-origin:center;will-change:opacity,transform;`;
        inner.innerHTML =
          tropMarkerSVG(ck) +
          `<div style="position:absolute;left:calc(100% + 6px);top:50%;transform:translateY(-50%);white-space:nowrap;font:800 ${ms.font}px/1.15 Outfit,system-ui,sans-serif;color:#fff;text-shadow:0 0 4px #000,0 0 4px #000,0 0 5px #000;pointer-events:none">${
            mph != null ? mph + " mph" : ""
          }${
            dl
              ? `<br><span style="font-weight:600;opacity:.9;font-size:${ms.subFont}px">${localizeDatelbl(dl)}</span>`
              : ""
          }</div>`;
        root.appendChild(inner);
        new maplibregl.Marker({ element: root }).setLngLat(f.geometry.coordinates).addTo(map);
        markers.push({ inner, appear: opts.ptStart + i * opts.ptStagger });
      });
    }
  } catch (e) {
    console.warn("[huracanes] drawStormCone", e);
  }
  return { markers, coneGj };
}

// Revela (anima) el cono ya dibujado: fundido del cono/trayectoria/avisos y
// aparición escalonada de los puntos. Llamar cada frame. `appearFrames` es la
// duración de la aparición de cada punto (pásalo derivado de fps: ~0.27s).
export function revealCone(
  map: maplibregl.Map,
  markers: ConeMarker[],
  frame: number,
  revealFrames: number,
  idPrefix = "cn",
  appearFrames = 8
) {
  const r = Math.max(0, Math.min(1, frame / Math.max(1, revealFrames)));
  const set = (id: string, prop: string, val: number) => {
    if (map.getLayer(id)) map.setPaintProperty(id, prop as any, val);
  };
  set(`${idPrefix}-cone-f`, "fill-opacity", 0.16 * r);
  set(`${idPrefix}-cone-b`, "line-opacity", 0.65 * r);
  set(`${idPrefix}-wind-f`, "fill-opacity", 0.34 * r);
  set(`${idPrefix}-wind-l`, "line-opacity", 0.85 * r);
  set(`${idPrefix}-track-l`, "line-opacity", 0.9 * r);
  set(`${idPrefix}-ww-l`, "line-opacity", 0.95 * r);
  markers.forEach((m) => {
    const a = Math.max(0, Math.min(1, (frame - m.appear) / Math.max(1, appearFrames)));
    m.inner.style.opacity = String(a);
    m.inner.style.transform = `scale(${0.5 + 0.5 * a})`;
  });
}
