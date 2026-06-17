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
import { MAPBOX_TOKEN, MAPBOX_STYLE, LOOP_SECONDS, loopFrameIndex } from "../lib/cdn";
import { applyBaseMap } from "../lib/basemap";
import { SatView } from "../types";

export type CityMarker = { name: string; lon: number; lat: number };
export type MapPolygon = {
  data: any;
  fill: string;
  line: string;
  fillOpacity?: number;
};

type Props = {
  sat: SatView;
  center: [number, number];
  zoom: number;
  opacity?: number;
  fitBounds?: [[number, number], [number, number]] | null;
  fitPadding?: { top: number; bottom: number; left: number; right: number };
  // Rótulos grandes de ciudad (marcadores Mapbox anclados a lon/lat).
  cityMarkers?: CityMarker[];
  // Polígonos a dibujar encima de la base (p. ej. vigilancias NWS).
  polygons?: MapPolygon[];
  // Drapear los frames del satélite GOES sobre la base. Por defecto NO: el
  // producto usa la base cartográfica "sistema" (gris + relieve + batimetría).
  showSatellite?: boolean;
  // Segundos por vuelta completa de la animación en bucle (satélite/radar).
  secondsPerLoop?: number;
};

function applyCamera(
  map: mapboxgl.Map,
  center: [number, number],
  zoom: number,
  fitBounds?: [[number, number], [number, number]] | null,
  fitPadding?: { top: number; bottom: number; left: number; right: number }
) {
  const pad = fitPadding || { top: 80, bottom: 80, left: 60, right: 60 };
  // resize() fuerza a Mapbox a releer el tamaño real del contenedor. Es necesario
  // cuando el mapa va dentro de un elemento con transform (p. ej. el push-in de
  // GeocolorConus): sin esto, cameraForBounds calcula con un tamaño erróneo y deja
  // el mundo entero en vez de encuadrar.
  map.resize();
  if (fitBounds) {
    // cameraForBounds + jumpTo es más robusto que fitBounds en el render headless.
    const cam = map.cameraForBounds(fitBounds, { padding: pad });
    if (cam) map.jumpTo(cam);
    else map.fitBounds(fitBounds, { padding: pad, animate: false });
  } else {
    map.jumpTo({ center, zoom });
  }
}

// Rótulo grande de ciudad: nombre con halo a la IZQUIERDA + punto localizador a la
// derecha (el punto cae sobre la coordenada). Estilo broadcast.
function cityMarkerHTML(name: string): string {
  return (
    `<div style="display:flex;align-items:center;gap:8px;transform:translate(6px,-50%);` +
    `font-family:Outfit,sans-serif;white-space:nowrap;pointer-events:none;">` +
    `<div style="font-size:30px;font-weight:800;color:#fff;` +
    `text-shadow:0 2px 6px rgba(0,0,0,0.95),0 0 14px rgba(0,0,0,0.85);">${name}</div>` +
    `<div style="width:12px;height:12px;border-radius:50%;background:#fff;` +
    `border:2px solid rgba(0,0,0,0.7);box-shadow:0 0 6px rgba(0,0,0,0.7);flex:0 0 auto;"></div>` +
    `</div>`
  );
}

// Mapa Mapbox dentro de Remotion. Por defecto dibuja la base cartográfica
// "sistema" (tierra gris con relieve, océano con batimetría, costas y fronteras).
// Si showSatellite, drapea además los frames del satélite GOES (image source por
// bounds del manifest). preserveDrawingBuffer es OBLIGATORIO para que Remotion
// capture el canvas en el render.
export const SatMap: React.FC<Props> = ({
  sat,
  center,
  zoom,
  opacity = 0.95,
  fitBounds = null,
  fitPadding,
  cityMarkers,
  polygons,
  showSatellite = false,
  secondsPerLoop = LOOP_SECONDS,
}) => {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const readyRef = useRef(false);
  const [ready, setReady] = useState(false);
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const n = sat?.frames?.length ?? 0;
  const useSat = showSatellite && n > 0 && !!sat.bounds;
  // Anti-vibración: mostramos UN SOLO frame a la vez. La animación se reproduce en
  // BUCLE a velocidad fija (loopFrameIndex) en vez de estirarse por toda la escena.
  const iCur = loopFrameIndex(frame, fps, n, secondsPerLoop);

  useEffect(() => {
    if (!ref.current) return;
    const handle = delayRender("sat-map-init");
    mapboxgl.accessToken = MAPBOX_TOKEN;

    const map = new mapboxgl.Map({
      container: ref.current,
      style: MAPBOX_STYLE,
      center,
      zoom,
      interactive: false,
      attributionControl: false,
      preserveDrawingBuffer: true,
      fadeDuration: 0,
      projection: "mercator",
    });
    mapRef.current = map;

    map.on("load", async () => {
      // Base cartográfica "sistema" (gris + relieve + batimetría + costas).
      applyBaseMap(map);

      // Satélite GOES opcional, drapeado por encima de la base.
      if (useSat && sat.bounds) {
        const b = sat.bounds;
        const coords: [
          [number, number],
          [number, number],
          [number, number],
          [number, number]
        ] = [
          [b.west, b.north],
          [b.east, b.north],
          [b.east, b.south],
          [b.west, b.south],
        ];
        sat.frames.forEach((f, i) => {
          const sid = `sat-${i}`;
          map.addSource(sid, { type: "image", url: f.url, coordinates: coords });
          map.addLayer({
            id: sid,
            type: "raster",
            source: sid,
            paint: { "raster-opacity": 0, "raster-fade-duration": 0 },
          });
        });
        if (map.getLayer("sat-0"))
          map.setPaintProperty("sat-0", "raster-opacity", opacity);
      }

      applyCamera(map, center, zoom, fitBounds, fitPadding);

      // Polígonos (vigilancias NWS) ENCIMA de todo (base y satélite).
      if (polygons && polygons.length) {
        polygons.forEach((pg, i) => {
          const sid = `poly-${i}`;
          map.addSource(sid, { type: "geojson", data: pg.data });
          map.addLayer({
            id: `${sid}-f`,
            type: "fill",
            source: sid,
            paint: { "fill-color": pg.fill, "fill-opacity": 0 },
          });
          map.addLayer({
            id: `${sid}-l`,
            type: "line",
            source: sid,
            paint: {
              "line-color": pg.line,
              "line-width": 3.5,
              "line-opacity": 0,
            },
          });
        });
      }

      // Rótulos curados de ciudad con DESCARTE POR COLISIÓN: recorremos por orden
      // de prioridad (el array ya viene ordenado por importancia) y solo añadimos
      // un rótulo si su caja en pantalla no se solapa con otra ya colocada.
      if (cityMarkers && cityMarkers.length) {
        const FS = 30; // font-size del rótulo
        const placed: { x0: number; y0: number; x1: number; y1: number }[] = [];
        cityMarkers.forEach((c) => {
          const p = map.project([c.lon, c.lat]);
          // Caja aproximada: texto a la IZQUIERDA + punto (≈20px) sobre la coord;
          // alto ≈ FS*1.2.
          const w = 26 + c.name.length * FS * 0.56;
          const h = FS * 1.2;
          const box = { x0: p.x - w, y0: p.y - h / 2, x1: p.x + 8, y1: p.y + h / 2 };
          const pad = 4;
          const hit = placed.some(
            (b) =>
              box.x0 < b.x1 + pad &&
              box.x1 > b.x0 - pad &&
              box.y0 < b.y1 + pad &&
              box.y1 > b.y0 - pad
          );
          if (hit) return; // se solapa con una ciudad más importante → descartar
          placed.push(box);
          const el = document.createElement("div");
          el.innerHTML = cityMarkerHTML(c.name);
          new mapboxgl.Marker({ element: el, anchor: "right" })
            .setLngLat([c.lon, c.lat])
            .addTo(map);
        });
      }

      const finish = () => {
        if (readyRef.current) return;
        readyRef.current = true;
        setReady(true);
        map.off("idle", onIdle);
        clearTimeout(fb);
        continueRender(handle);
      };
      const onIdle = () => finish();
      map.on("idle", onIdle);
      const fb = setTimeout(() => {
        console.warn(`[SatMap] timeout en init (sat ${sat?.view}, ${n} frames)`);
        finish();
      }, 90000);
    });

    return () => {
      try {
        continueRender(handle);
      } catch {
        /* noop */
      }
      map.remove();
      mapRef.current = null;
      readyRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-aplica el encuadre cuando el mapa está listo o cambia el bbox.
  const fbKey = JSON.stringify(fitBounds || []);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    applyCamera(map, center, zoom, fitBounds, fitPadding);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, fbKey, center[0], center[1], zoom]);

  // Conmuta el frame de satélite visible (solo si se drapea el satélite).
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !useSat) return;
    for (let i = 0; i < n; i++) {
      if (map.getLayer(`sat-${i}`))
        map.setPaintProperty(`sat-${i}`, "raster-opacity", i === iCur ? opacity : 0);
    }
    map.triggerRepaint();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frame, ready, n, opacity, useSat]);

  // Fundido de los polígonos de vigilancia.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !polygons || !polygons.length) return;
    const r = Math.max(0, Math.min(1, frame / Math.round(fps * 0.8)));
    polygons.forEach((pg, i) => {
      const fo = pg.fillOpacity ?? 0.28;
      if (map.getLayer(`poly-${i}-f`))
        map.setPaintProperty(`poly-${i}-f`, "fill-opacity", fo * r);
      if (map.getLayer(`poly-${i}-l`))
        map.setPaintProperty(`poly-${i}-l`, "line-opacity", 0.95 * r);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frame, ready]);

  // Solo en RENDER con satélite: esperar repintado del frame entero.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !useSat || !getRemotionEnvironment().isRendering) return;
    const handle = delayRender(`sat-frame-${iCur}`);
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
    const fb = setTimeout(() => {
      console.warn(`[SatMap] timeout esperando 'idle' (frame ${iCur}/${n})`);
      finish();
    }, 60000);
    return () => {
      try {
        continueRender(handle);
      } catch {
        /* noop */
      }
      clearTimeout(fb);
    };
  }, [iCur, ready, useSat, n]);

  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <style>{`.mapboxgl-ctrl-logo,.mapboxgl-ctrl-attrib,.mapboxgl-ctrl-bottom-left,.mapboxgl-ctrl-bottom-right{display:none !important;}`}</style>
      <div ref={ref} style={{ position: "absolute", inset: 0 }} />
    </AbsoluteFill>
  );
};
