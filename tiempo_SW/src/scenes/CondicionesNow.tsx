import React, { useEffect, useRef, useState } from "react";
import {
  AbsoluteFill,
  continueRender,
  delayRender,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { MAPBOX_TOKEN, MAPBOX_STYLE, CONUS_VIEW, CONUS_PAD } from "../lib/cdn";
import { applyBaseMap } from "../lib/basemap";
import { TopicBar } from "../components/Overlay";
import { CondBox } from "../components/CondBox";
import { CityCond, Placed, estimateBox } from "../lib/conditions";
import { placeChips } from "./ServicesMockups";
import { SatView, ThemeMode } from "../types";
import { palette } from "../lib/theme";

const { fontFamily } = loadFont();

// Escena "CONDICIONES AHORA": capa de temperatura NBM (raster coloreado drapeado
// sobre el mapa base, como el satélite/radar) + cajas por ciudad (símbolo, temp y
// viento). Datos reales: temp del manifest NBM, cajas de data/cities/weather.json.
export const CondicionesNow: React.FC<{
  temp?: SatView;
  cityConds?: CityCond[];
  mode?: ThemeMode;
}> = ({ temp, cityConds = [], mode = "normal" }) => {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const readyRef = useRef(false);
  const [placed, setPlaced] = useState<Placed<CityCond>[]>([]);
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const pal = palette(mode);

  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });

  useEffect(() => {
    if (!ref.current) return;
    const handle = delayRender("condiciones-now");
    mapboxgl.accessToken = MAPBOX_TOKEN;

    const map = new mapboxgl.Map({
      container: ref.current,
      style: MAPBOX_STYLE,
      center: [-96, 38],
      zoom: 3.4,
      interactive: false,
      attributionControl: false,
      preserveDrawingBuffer: true,
      fadeDuration: 0,
      projection: "mercator",
    });
    mapRef.current = map;

    map.on("load", () => {
      // Base "sistema TV" IDÉNTICA a las demás escenas (misma proyección y look).
      applyBaseMap(map);

      // Capa de temperatura NBM (drapeada por bounds) DEBAJO de costas/fronteras,
      // para que los límites de países/estados queden visibles por encima.
      const b = temp?.bounds;
      const url = temp?.frames?.[0]?.url;
      if (b && url) {
        map.addSource("nbm-temp", {
          type: "image",
          url,
          coordinates: [
            [b.west, b.north],
            [b.east, b.north],
            [b.east, b.south],
            [b.west, b.south],
          ],
        });
        const beforeId = map.getLayer("cm-coast-border") ? "cm-coast-border" : undefined;
        map.addLayer(
          {
            id: "nbm-temp",
            type: "raster",
            source: "nbm-temp",
            paint: { "raster-opacity": 0.72, "raster-fade-duration": 0 },
          },
          beforeId
        );
      }

      map.resize();
      const cam = map.cameraForBounds(CONUS_VIEW, { padding: CONUS_PAD });
      if (cam) map.jumpTo(cam);
      else map.fitBounds(CONUS_VIEW, { animate: false });

      const finish = () => {
        if (readyRef.current) return;
        readyRef.current = true;
        // placeChips (el colocador de máximas/servicios, con sesgo al interior y
        // anti-solape fuerte): con las 12 capitales del corredor NE, el placeBoxes
        // antiguo dejaba las cajas en cascada pisándose. Los nudges heredados de
        // CONUS (NY/Houston/Seattle) se retiran: aquí no aplican.
        const projected = cityConds.map((c) => {
          const p = map.project([c.lon, c.lat]);
          return { ...c, id: c.name, x: p.x, y: p.y, ...estimateBox(c.name) };
        });
        const boxes = placeChips(projected, width, height, 170, height - 56); // 170: que las cajas del norte no se metan bajo el banner
        setPlaced(boxes);
        map.off("idle", finish);
        clearTimeout(fb);
        continueRender(handle);
      };
      map.on("idle", finish);
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
      readyRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <AbsoluteFill style={{ background: "#000", fontFamily }}>
      <style>{`.mapboxgl-ctrl-logo,.mapboxgl-ctrl-attrib,.mapboxgl-ctrl-bottom-left,.mapboxgl-ctrl-bottom-right{display:none !important;}`}</style>
      <div ref={ref} style={{ position: "absolute", inset: 0 }} />

      {/* Viñeta para legibilidad de cajas, título y leyenda. */}
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          background:
            "linear-gradient(180deg, rgba(0,0,0,0.45) 0%, rgba(0,0,0,0) 18%, rgba(0,0,0,0) 82%, rgba(0,0,0,0.5) 100%)",
        }}
      />

      {/* Cajas por ciudad: caja sin solape (bx,by) + punto sobre la coordenada. */}
      <div style={{ opacity: op }}>
        {placed.map((c) => (
          <React.Fragment key={c.name}>
            <div style={{ position: "absolute", left: c.bx, top: c.by, transform: "translate(-50%, -50%)" }}>
              <CondBox c={c} />
            </div>
            <div
              style={{
                position: "absolute",
                left: c.x,
                top: c.y,
                width: 12,
                height: 12,
                borderRadius: "50%",
                background: "#fff",
                border: "2px solid rgba(0,0,0,0.6)",
                boxShadow: "0 0 6px rgba(0,0,0,0.6)",
                transform: "translate(-50%, -50%)",
              }}
            />
          </React.Fragment>
        ))}
      </div>

      <TopicBar
        topic="CONDICIONES AHORA"
        sub="TEMPERATURA Y VIENTO"
        topicColor={pal.topicColor}
        opacity={op}
      />

      {/* Leyenda de temperatura (colorbar °F). */}
      <div
        style={{
          position: "absolute",
          right: 48,
          bottom: 40,
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-end",
          gap: 6,
          opacity: op,
        }}
      >
        <div style={{ color: "#fff", fontSize: 18, fontWeight: 700, opacity: 0.9 }}>Temperatura (°F)</div>
        <div
          style={{
            width: 360,
            height: 14,
            borderRadius: 7,
            border: "1px solid rgba(255,255,255,0.3)",
            background:
              "linear-gradient(90deg,#7c4dff 0%,#3d7bff 18%,#21b6c9 32%,#2ecc71 46%,#f4d03f 60%,#ef8e2d 74%,#e74c3c 88%,#c0298a 100%)",
          }}
        />
        <div style={{ width: 360, display: "flex", justifyContent: "space-between", color: "#dfe8f0", fontSize: 14 }}>
          <span>10°</span>
          <span>60°</span>
          <span>110°</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};
