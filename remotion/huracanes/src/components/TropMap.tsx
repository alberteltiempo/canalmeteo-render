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
  geoBounds,
  lightenWater,
  FRAME_PADDING,
} from "../lib/cdn";
import { drawStormCone, revealCone, ConeMarker, MARKER_BIG } from "../lib/cone";
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
  const markersRef = useRef<ConeMarker[]>([]);
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
      lightenWater(map);
      enhanceLabels(map);
      const before = firstSymbol();
      try {
        // Cono + trayectoria + avisos + puntos (helper compartido con la
        // escena de lluvia; aquí con el marcador grande del pase de legibilidad)
        const drawn = await drawStormCone(map, storm, {
          beforeId: before,
          ptStart: PT_START,
          ptStagger: PT_STAGGER,
          idPrefix: "trop",
          markerStyle: MARKER_BIG,
        });
        markersRef.current = drawn.markers;

        // Encuadre al cono (mismo bbox y padding que la escena de lluvia)
        const bb = storm._coneBounds || (drawn.coneGj && geoBounds(drawn.coneGj)) || null;
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

  // Reveal animado cada frame (helper compartido; puntos a ~0.27s según fps)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    revealCone(map, markersRef.current, frame, REVEAL, "trop", Math.max(1, Math.round(fps * 0.27)));
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
