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
import { MAPBOX_TOKEN, MAPBOX_STYLE, lightenWater, OCEAN } from "../lib/cdn";
import { drawStormCone, revealCone, ConeMarker } from "../lib/cone";
import { SatView, Storm } from "../types";

type Props = {
  sat: SatView;
  center: [number, number];
  zoom: number;
  opacity?: number;
  // Si se pasan puntos (tormentas), el mapa los encuadra a todos (fitBounds).
  fitPoints?: { lon: number; lat: number }[];
  marginDeg?: number;
  minSpan?: number;
  // Encuadre por bbox explícito (tiene prioridad sobre fitPoints)
  fitBounds?: [[number, number], [number, number]] | null;
  fitPadding?: { top: number; bottom: number; left: number; right: number };
  showLabels?: boolean;
  // Atenúa el raster sobre el agua (0–1). P.ej. 0.3 → lluvia ~70% sobre el mar.
  dimWater?: number;
  // Icono/etiqueta a colocar sobre un punto geográfico (centro de la tormenta)
  centerBadge?: { lon: number; lat: number; html: string };
  // Si se pasa, dibuja el cono + trayectoria de la tormenta encima del raster
  coneStorm?: Storm;
  // Polígonos a dibujar encima del raster (p. ej. zonas de génesis del NHC)
  polygons?: { data: any; fill: string; line: string; fillOpacity?: number }[];
};

// Calcula un bounding box [SO, NE] que englobe los puntos, con margen y span mínimo.
function pointsBounds(
  pts: { lon: number; lat: number }[],
  marginDeg = 7,
  minSpan = 22
): [[number, number], [number, number]] | null {
  const valid = pts.filter((p) => isFinite(p.lon) && isFinite(p.lat));
  if (!valid.length) return null;
  let w = Math.min(...valid.map((p) => p.lon));
  let e = Math.max(...valid.map((p) => p.lon));
  let s = Math.min(...valid.map((p) => p.lat));
  let nN = Math.max(...valid.map((p) => p.lat));
  w -= marginDeg;
  e += marginDeg;
  s -= marginDeg;
  nN += marginDeg;
  const cx = (w + e) / 2;
  const cy = (s + nN) / 2;
  if (e - w < minSpan) {
    w = cx - minSpan / 2;
    e = cx + minSpan / 2;
  }
  if (nN - s < minSpan) {
    s = cy - minSpan / 2;
    nN = cy + minSpan / 2;
  }
  return [
    [w, s],
    [e, nN],
  ];
}

// Aplica el encuadre: bbox explícito > fitBounds a tormentas > center/zoom.
function applyCamera(
  map: mapboxgl.Map,
  fitPoints: { lon: number; lat: number }[] | undefined,
  center: [number, number],
  zoom: number,
  marginDeg: number,
  minSpan: number,
  fitBounds?: [[number, number], [number, number]] | null,
  fitPadding?: { top: number; bottom: number; left: number; right: number }
) {
  const pad = fitPadding || { top: 140, bottom: 70, left: 70, right: 70 };
  const bb =
    fitBounds ||
    (fitPoints && fitPoints.length ? pointsBounds(fitPoints, marginDeg, minSpan) : null);
  if (bb) {
    map.fitBounds(bb, { padding: pad, animate: false });
  } else {
    map.jumpTo({ center, zoom });
  }
}

// Sube las fronteras (países y estados) por ENCIMA del satélite y las realza.
function raiseBorders(map: mapboxgl.Map) {
  const layers = map.getStyle()?.layers || [];
  const ids = layers
    .filter(
      (l: any) =>
        l.type === "line" &&
        /admin/.test(l.id) &&
        /boundary/.test(l.id) &&
        !/bg/.test(l.id)
    )
    .map((l: any) => l.id);
  ids.forEach((id: string) => {
    try {
      map.moveLayer(id); // sin beforeId → al tope (encima del raster)
      const isCountry = /admin-0/.test(id);
      map.setPaintProperty(id, "line-color", "rgba(255,255,255,0.95)");
      map.setPaintProperty(id, "line-width", isCountry ? 2.4 : 1.0);
      map.setPaintProperty(id, "line-opacity", isCountry ? 0.95 : 0.55);
    } catch {
      /* noop */
    }
  });
}

// Dibuja la línea de costa (contorno de los polígonos de agua) para que las
// costas se lean bien sobre el satélite/lluvia.
function addCoastline(map: mapboxgl.Map) {
  if (map.getLayer("cm-coastline")) return;
  try {
    map.addLayer({
      id: "cm-coastline",
      type: "line",
      source: "composite",
      "source-layer": "water",
      paint: {
        "line-color": "rgba(255,255,255,0.85)",
        "line-width": 1.6,
        "line-blur": 0.2,
      },
    });
  } catch {
    /* noop */
  }
}

// Atenúa la lluvia/satélite sobre el agua: dibuja el polígono de agua POR ENCIMA
// del raster con opacidad parcial (la lluvia queda ~70% sobre el mar).
function dimWaterOverRaster(map: mapboxgl.Map, dim: number, ocean: string) {
  if (map.getLayer("cm-water-dim")) return;
  try {
    map.addLayer({
      id: "cm-water-dim",
      type: "fill",
      source: "composite",
      "source-layer": "water",
      paint: { "fill-color": ocean, "fill-opacity": dim },
    });
  } catch {
    /* noop */
  }
}

// Sube y realza los nombres de ciudades/estados por ENCIMA del satélite.
function raiseCityLabels(map: mapboxgl.Map) {
  const sizes: Record<string, number> = {
    "settlement-major-label": 24,
    "settlement-minor-label": 17,
    "state-label": 18,
    "country-label": 22,
  };
  const layers = map.getStyle()?.layers || [];
  layers.forEach((l: any) => {
    if (l.type !== "symbol") return;
    const sz = sizes[l.id];
    if (!sz) return;
    try {
      map.moveLayer(l.id); // al tope (encima del raster y las fronteras)
      map.setLayoutProperty(l.id, "text-size", sz);
      map.setPaintProperty(l.id, "text-color", "#ffffff");
      map.setPaintProperty(l.id, "text-halo-color", "rgba(0,0,0,0.9)");
      map.setPaintProperty(l.id, "text-halo-width", 1.8);
    } catch {
      /* noop */
    }
  });
}

// Mapa Mapbox dentro de Remotion: drapea los frames del satélite (image source
// por bounds del manifest) y conmuta opacidad por frame. preserveDrawingBuffer
// es OBLIGATORIO para que Remotion capture el canvas en el render.
export const SatMap: React.FC<Props> = ({
  sat,
  center,
  zoom,
  opacity = 0.9,
  fitPoints,
  marginDeg = 7,
  minSpan = 22,
  fitBounds = null,
  fitPadding,
  showLabels = true,
  dimWater,
  centerBadge,
  coneStorm,
  polygons,
}) => {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const readyRef = useRef(false);
  const coneMarkersRef = useRef<ConeMarker[]>([]);
  const [ready, setReady] = useState(false);
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();

  const n = sat.frames.length;
  // Anti-vibración: mostramos UN SOLO frame a la vez (el más cercano), sin
  // superponer dos rásters. Superponer dos capas raster con opacidad fraccionaria
  // hace que Mapbox las re-muestree y "bailen" pixel a pixel. Con un frame por vez
  // se ve como un time-lapse limpio de TV, totalmente estable.
  const fpos = n > 1 ? (frame / Math.max(1, durationInFrames - 1)) * (n - 1) : 0;
  const iCur = Math.min(n - 1, Math.max(0, Math.round(fpos)));

  // Init del mapa (una vez)
  useEffect(() => {
    if (!ref.current || !sat.bounds || !n) return;
    const handle = delayRender("sat-map-init");
    mapboxgl.accessToken = MAPBOX_TOKEN;
    const b = sat.bounds;
    const coords: [[number, number], [number, number], [number, number], [number, number]] = [
      [b.west, b.north],
      [b.east, b.north],
      [b.east, b.south],
      [b.west, b.south],
    ];

    const map = new mapboxgl.Map({
      container: ref.current,
      style: MAPBOX_STYLE,
      center,
      zoom,
      interactive: false,
      attributionControl: false,
      preserveDrawingBuffer: true, // imprescindible para el render
      fadeDuration: 0,
      projection: "mercator",
    });
    mapRef.current = map;

    map.on("load", async () => {
      lightenWater(map);
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
      // Encuadre inicial con lo que haya en este momento (puede re-aplicarse
      // luego cuando lleguen las tormentas — ver efecto de cámara).
      applyCamera(map, fitPoints, center, zoom, marginDeg, minSpan, fitBounds, fitPadding);
      // Muestra ya el primer frame para que el primer paint no salga en negro.
      if (map.getLayer("sat-0")) map.setPaintProperty("sat-0", "raster-opacity", opacity);
      // Atenúa la lluvia/satélite sobre el agua (si se pide) y dibuja la costa.
      if (dimWater != null) dimWaterOverRaster(map, dimWater, OCEAN);
      addCoastline(map);
      // Cono + trayectoria de la tormenta ENCIMA del raster. Sin beforeId para
      // que quede sobre el satélite; luego raiseBorders/raiseCityLabels suben
      // fronteras y nombres por encima.
      if (coneStorm) {
        coneMarkersRef.current = await drawStormCone(map, coneStorm, {
          beforeId: undefined,
          ptStart: Math.round(fps * 0.5),
          ptStagger: Math.max(2, Math.round(fps * 0.16)),
          idPrefix: "rain",
          skipPoints: true, // en la lluvia solo cono + trayectoria (sin saturar)
        });
      }
      // Polígonos (zonas de génesis del NHC) ENCIMA del raster (sin beforeId).
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
              "line-width": 4,
              "line-opacity": 0,
              "line-dasharray": [2, 1.5],
            },
          });
        });
      }
      // Fronteras (países/estados) por encima del satélite.
      raiseBorders(map);
      // Nombres de ciudades por encima del satélite.
      if (showLabels) raiseCityLabels(map);
      // Icono del sistema sobre el centro de la tormenta.
      if (centerBadge) {
        const el = document.createElement("div");
        el.innerHTML = centerBadge.html;
        new mapboxgl.Marker({ element: el })
          .setLngLat([centerBadge.lon, centerBadge.lat])
          .addTo(map);
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
      // Fallback: si 'idle' no llega (WebGL por software muy lento o un tile
      // que cuelga), continúa igualmente pasados 90s para no agotar delayRender.
      const fb = setTimeout(() => {
        console.warn(
          `[SatMap] timeout en init (view ${sat.view}, ${n} frames) — el mapa pudo no pintar`
        );
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

  // Re-aplica el encuadre cuando el mapa está listo o cambian las tormentas.
  // (Soluciona el caso en que el mapa se monta antes de que calculateMetadata
  // entregue los datos: el efecto [] no se reejecutaría con los storms nuevos.)
  const fpKey = JSON.stringify(fitPoints || []);
  const fbKey = JSON.stringify(fitBounds || []);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    applyCamera(map, fitPoints, center, zoom, marginDeg, minSpan, fitBounds, fitPadding);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, fpKey, fbKey, center[0], center[1], zoom, marginDeg, minSpan]);

  // Crossfade SIN pulso oscuro: la capa actual (i0) SIEMPRE a opacidad completa,
  // y la siguiente (i1, dibujada encima) se funde de 0→1. Como i1 está por encima,
  // al llegar a 1 cubre a i0. Nunca quedan ambas a media opacidad → nunca asoma el fondo.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !n) return;
    for (let i = 0; i < n; i++) {
      map.setPaintProperty(`sat-${i}`, "raster-opacity", i === iCur ? opacity : 0);
    }
    map.triggerRepaint(); // fuerza un paint nuevo → 'idle' reflejará este frame
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frame, ready, n, opacity]);

  // Reveal animado del cono (si se dibujó), igual que en la escena de trayectoria.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !coneStorm) return;
    revealCone(map, coneMarkersRef.current, frame, Math.round(fps * 0.9), "rain");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frame, ready]);

  // Fundido de los polígonos de génesis.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !polygons || !polygons.length) return;
    const r = Math.max(0, Math.min(1, frame / Math.round(fps * 0.8)));
    polygons.forEach((pg, i) => {
      const fo = pg.fillOpacity ?? 0.22;
      if (map.getLayer(`poly-${i}-f`))
        map.setPaintProperty(`poly-${i}-f`, "fill-opacity", fo * r);
      if (map.getLayer(`poly-${i}-l`))
        map.setPaintProperty(`poly-${i}-l`, "line-opacity", 0.95 * r);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frame, ready]);

  // Solo en RENDER: esperar repintado del frame entero (en preview no, para fluidez).
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !n || !getRemotionEnvironment().isRendering) return;
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
      console.warn(
        `[SatMap] timeout esperando 'idle' (frame ${iCur}/${n}, view ${sat.view}) — posible captura en negro`
      );
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
  }, [iCur, ready, n]);

  if (!sat.bounds || !n) {
    return (
      <AbsoluteFill
        style={{
          background: "#0d1a26",
          color: "#90a4ae",
          justifyContent: "center",
          alignItems: "center",
          fontSize: 24,
        }}
      >
        Sin frames de satélite (manifest vacío)
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <style>{`.mapboxgl-ctrl-logo,.mapboxgl-ctrl-attrib,.mapboxgl-ctrl-bottom-left,.mapboxgl-ctrl-bottom-right{display:none !important;}`}</style>
      <div ref={ref} style={{ position: "absolute", inset: 0 }} />
    </AbsoluteFill>
  );
};
