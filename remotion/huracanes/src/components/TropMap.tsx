import React, { useEffect, useRef, useState } from "react";
import {
  AbsoluteFill,
  continueRender,
  delayRender,
  getRemotionEnvironment,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import {
  MAPBOX_TOKEN,
  MAPBOX_STYLE,
  fetchGeoJSON,
  tropMarkerSVG,
  tropWWColor,
  geoBounds,
  lightenWater,
  FRAME_PADDING,
} from "../lib/cdn";
import { catKeyFromKt, ktToMph, localizeDatelbl } from "../lib/tropical";
import { Storm } from "../types";

// Agranda y blanquea las etiquetas del basemap (look broadcast tipo Tormenta).
function enhanceLabels(map: mapboxgl.Map) {
  const sizes: Record<string, number> = {
    "settlement-major-label": 30,
    "settlement-minor-label": 22,
    "settlement-subdivision-label": 18,
    "state-label": 26,
    "country-label": 30,
  };
  (map.getStyle()?.layers || []).forEach((l: any) => {
    if (l.type !== "symbol") return;
    const sz = sizes[l.id];
    try {
      if (sz) map.setLayoutProperty(l.id, "text-size", sz);
      if (sz) {
        map.setPaintProperty(l.id, "text-color", "#ffffff");
        map.setPaintProperty(l.id, "text-halo-color", "rgba(0,0,0,0.85)");
        map.setPaintProperty(l.id, "text-halo-width", 1.8);
      }
    } catch {
      /* layer sin esa propiedad */
    }
  });
}

// Escena 2 por tormenta: basemap (sin satélite) con cono + trayectoria + avisos
// + puntos de pronóstico (marcador de categoría D/T/1-5). Reveal animado.
export const TropMap: React.FC<{ storm: Storm }> = ({ storm }) => {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const markersRef = useRef<{ inner: HTMLDivElement; appear: number }[]>([]);
  const [ready, setReady] = useState(false);
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const REVEAL = Math.round(fps * 0.9); // cono/track aparecen en ~0.9s
  const PT_START = Math.round(fps * 0.6);
  const PT_STAGGER = Math.max(2, Math.round(fps * 0.18));

  useEffect(() => {
    if (!ref.current || !storm.layers) return;
    const handle = delayRender(`trop-map-${storm.id}`);
    mapboxgl.accessToken = MAPBOX_TOKEN;
    const map = new mapboxgl.Map({
      container: ref.current,
      style: MAPBOX_STYLE,
      center: [storm.lon ?? -90, storm.lat ?? 15],
      zoom: 4.5,
      interactive: false,
      attributionControl: false,
      preserveDrawingBuffer: true,
      fadeDuration: 0,
      projection: "mercator",
    });
    mapRef.current = map;

    const firstSymbol = () => {
      const ls = map.getStyle()?.layers || [];
      const s = ls.find((l: any) => l.type === "symbol");
      return s?.id;
    };

    map.on("load", async () => {
      const L = storm.layers!;
      lightenWater(map);
      enhanceLabels(map);
      const before = firstSymbol();
      try {
        // Cono
        let coneGj: any = null;
        if (L.cone) {
          coneGj = await fetchGeoJSON(L.cone);
          map.addSource(`cone-${storm.id}`, { type: "geojson", data: coneGj });
          map.addLayer(
            { id: `cone-f`, type: "fill", source: `cone-${storm.id}`, paint: { "fill-color": "#ffffff", "fill-opacity": 0 } },
            before
          );
          map.addLayer(
            { id: `cone-b`, type: "line", source: `cone-${storm.id}`, paint: { "line-color": "#ffffff", "line-width": 1.5, "line-opacity": 0, "line-dasharray": [2, 1.5] } },
            before
          );
        }
        // Trayectoria
        if (L.track) {
          const gj = await fetchGeoJSON(L.track);
          map.addSource(`track-${storm.id}`, { type: "geojson", data: gj });
          map.addLayer(
            { id: `track-l`, type: "line", source: `track-${storm.id}`, paint: { "line-color": "#ffffff", "line-width": 2.5, "line-opacity": 0, "line-dasharray": [1.5, 1] } },
            before
          );
        }
        // Avisos / vigilancias (ww)
        if (L.ww) {
          const gj = await fetchGeoJSON(L.ww);
          (gj.features || []).forEach((f: any) => {
            f.properties = f.properties || {};
            f.properties._c = tropWWColor(f.properties.tcww);
          });
          map.addSource(`ww-${storm.id}`, { type: "geojson", data: gj });
          map.addLayer({ id: `ww-l`, type: "line", source: `ww-${storm.id}`, paint: { "line-color": ["get", "_c"], "line-width": 6, "line-opacity": 0 } });
        }
        // Puntos de pronóstico (marcadores de categoría)
        if (L.points) {
          const gj = await fetchGeoJSON(L.points);
          const feats = gj.features || [];
          feats.forEach((f: any, i: number) => {
            const p = f.properties || {};
            const ck = catKeyFromKt(p.maxwind);
            const isHU = /^H[1-5]$/.test(ck);
            const size = isHU ? 84 : 68;
            const mph = ktToMph(p.maxwind);
            const dl = p.datelbl || "";
            const root = document.createElement("div");
            const inner = document.createElement("div");
            inner.style.cssText = `position:relative;width:${size}px;height:${size}px;opacity:0;transform-origin:center;will-change:opacity,transform;`;
            inner.innerHTML =
              tropMarkerSVG(ck) +
              `<div style="position:absolute;left:calc(100% + 6px);top:50%;transform:translateY(-50%);white-space:nowrap;font:800 20px/1.15 Outfit,system-ui,sans-serif;color:#fff;text-shadow:0 0 4px #000,0 0 4px #000,0 0 5px #000;pointer-events:none">${mph != null ? mph + " mph" : ""}${dl ? `<br><span style="font-weight:600;opacity:.9;font-size:16px">${localizeDatelbl(dl)}</span>` : ""}</div>`;
            root.appendChild(inner);
            new mapboxgl.Marker({ element: root }).setLngLat(f.geometry.coordinates).addTo(map);
            markersRef.current.push({ inner, appear: PT_START + i * PT_STAGGER });
          });
        }

        // Encuadre al cono (mismo bbox y padding que la escena de lluvia)
        const bb = storm._coneBounds || (coneGj && geoBounds(coneGj)) || null;
        if (bb) {
          map.fitBounds(bb, { padding: FRAME_PADDING, animate: false });
        } else if (storm.lon != null && storm.lat != null) {
          map.jumpTo({ center: [storm.lon, storm.lat], zoom: 5 });
        }
      } catch (e) {
        console.warn("[huracanes] trop layers", e);
      }
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        setReady(true);
        map.off("idle", onIdle);
        clearTimeout(fb);
        continueRender(handle);
      };
      const onIdle = () => finish();
      map.on("idle", onIdle);
      const fb = setTimeout(finish, 90000);
    });

    return () => {
      try {
        continueRender(handle);
      } catch {
        /* noop */
      }
      map.remove();
      mapRef.current = null;
      markersRef.current = [];
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reveal animado cada frame
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const r = Math.max(0, Math.min(1, frame / REVEAL));
    const set = (id: string, prop: string, val: number) => {
      if (map.getLayer(id)) map.setPaintProperty(id, prop as any, val);
    };
    set("cone-f", "fill-opacity", 0.16 * r);
    set("cone-b", "line-opacity", 0.65 * r);
    set("track-l", "line-opacity", 0.9 * r);
    set("ww-l", "line-opacity", 0.95 * r);
    // puntos: aparición escalonada
    markersRef.current.forEach((m) => {
      const a = Math.max(0, Math.min(1, (frame - m.appear) / 8));
      m.inner.style.opacity = String(a);
      m.inner.style.transform = `scale(${0.5 + 0.5 * a})`;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frame, ready]);

  // Espera de repintado para el render (solo al renderizar, no en preview)
  const step = Math.floor(frame / 3);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !getRemotionEnvironment().isRendering) return;
    const handle = delayRender(`trop-step-${step}`);
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      map.off("idle", onIdle);
      clearTimeout(fb);
      continueRender(handle);
    };
    const onIdle = () => finish();
    map.on("idle", onIdle);
    const fb = setTimeout(finish, 60000);
    return () => {
      try {
        continueRender(handle);
      } catch {
        /* noop */
      }
      clearTimeout(fb);
    };
  }, [step, ready]);

  return (
    <AbsoluteFill style={{ background: "#0d1a26" }}>
      <style>{`.mapboxgl-ctrl-logo,.mapboxgl-ctrl-attrib,.mapboxgl-ctrl-bottom-left,.mapboxgl-ctrl-bottom-right{display:none !important;}`}</style>
      <div ref={ref} style={{ position: "absolute", inset: 0 }} />
    </AbsoluteFill>
  );
};
