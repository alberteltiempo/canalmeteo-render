import mapboxgl from "mapbox-gl";
import { fetchGeoJSON, tropMarkerSVG, tropWWColor } from "./cdn";
import { catKeyFromKt, ktToMph, localizeDatelbl } from "./tropical";
import { Storm } from "../types";

export type ConeMarker = { inner: HTMLDivElement; appear: number };

// Dibuja cono + trayectoria + avisos + puntos de pronóstico de una tormenta
// sobre un mapa Mapbox ya cargado. Capas con opacidad 0 (se revelan con
// revealCone). Devuelve los marcadores de puntos para animarlos.
// Reutilizado por la escena del cono (TropMap) y la de lluvia (SatMap).
export async function drawStormCone(
  map: mapboxgl.Map,
  storm: Storm,
  opts: { beforeId?: string; ptStart: number; ptStagger: number; idPrefix?: string; skipPoints?: boolean }
): Promise<ConeMarker[]> {
  const L = storm.layers;
  if (!L) return [];
  const before = opts.beforeId;
  const pfx = opts.idPrefix ?? "cn";
  const markers: ConeMarker[] = [];
  try {
    if (L.cone) {
      const gj = await fetchGeoJSON(L.cone);
      map.addSource(`${pfx}-cone-${storm.id}`, { type: "geojson", data: gj });
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
    if (L.track) {
      const gj = await fetchGeoJSON(L.track);
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
    if (L.ww) {
      const gj = await fetchGeoJSON(L.ww);
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
    if (L.points && !opts.skipPoints) {
      const gj = await fetchGeoJSON(L.points);
      (gj.features || []).forEach((f: any, i: number) => {
        const p = f.properties || {};
        const ck = catKeyFromKt(p.maxwind);
        const isHU = /^H[1-5]$/.test(ck);
        const size = isHU ? 72 : 58;
        const mph = ktToMph(p.maxwind);
        const dl = p.datelbl || "";
        const root = document.createElement("div");
        const inner = document.createElement("div");
        inner.style.cssText = `position:relative;width:${size}px;height:${size}px;opacity:0;transform-origin:center;will-change:opacity,transform;`;
        inner.innerHTML =
          tropMarkerSVG(ck) +
          `<div style="position:absolute;left:calc(100% + 6px);top:50%;transform:translateY(-50%);white-space:nowrap;font:800 18px/1.15 Outfit,system-ui,sans-serif;color:#fff;text-shadow:0 0 4px #000,0 0 4px #000;pointer-events:none">${
            mph != null ? mph + " mph" : ""
          }${
            dl
              ? `<br><span style="font-weight:600;opacity:.9;font-size:14px">${localizeDatelbl(dl)}</span>`
              : ""
          }</div>`;
        root.appendChild(inner);
        new mapboxgl.Marker({ element: root }).setLngLat(f.geometry.coordinates).addTo(map);
        markers.push({ inner, appear: opts.ptStart + i * opts.ptStagger });
      });
    }
  } catch (e) {
    console.warn("[huracanes] drawStormCone", e);
  }
  return markers;
}

// Revela (anima) el cono ya dibujado: fundido del cono/trayectoria/avisos y
// aparición escalonada de los puntos. Llamar cada frame.
export function revealCone(
  map: mapboxgl.Map,
  markers: ConeMarker[],
  frame: number,
  revealFrames: number,
  idPrefix = "cn"
) {
  const r = Math.max(0, Math.min(1, frame / Math.max(1, revealFrames)));
  const set = (id: string, prop: string, val: number) => {
    if (map.getLayer(id)) map.setPaintProperty(id, prop as any, val);
  };
  set(`${idPrefix}-cone-f`, "fill-opacity", 0.16 * r);
  set(`${idPrefix}-cone-b`, "line-opacity", 0.65 * r);
  set(`${idPrefix}-track-l`, "line-opacity", 0.9 * r);
  set(`${idPrefix}-ww-l`, "line-opacity", 0.95 * r);
  markers.forEach((m) => {
    const a = Math.max(0, Math.min(1, (frame - m.appear) / 8));
    m.inner.style.opacity = String(a);
    m.inner.style.transform = `scale(${0.5 + 0.5 * a})`;
  });
}
