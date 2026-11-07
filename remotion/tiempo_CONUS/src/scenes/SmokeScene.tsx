// SmokeScene.tsx — humo HMS (NOAA) sobre la base "sistema TV".
// 11/09/2026: sustituye a CONUS_Fire_Smoke de lynx-hub. Feed:
// data/fires/hms_smoke.json (FeatureCollection de polígonos con
// properties.density = Light | Medium | Heavy, varias pasadas GOES al día).
import React from "react";
import { AbsoluteFill } from "remotion";
import { SatMap, MapPolygon } from "../components/SatMap";
import { TopicBar } from "../components/Overlay";
import { CONUS_VIEW, CONUS_PAD } from "../lib/cdn";
import { MAJOR_CITIES } from "../lib/cities";
import type { SatView } from "../types";

export type SmokeData = { features: any[]; counts?: Record<string, number> } | null;

// Gris-amarillo ascendente: el humo denso tapa, el ligero apenas tiñe.
const DENSITY: Record<string, { fill: string; line: string; op: number }> = {
  light: { fill: "#d9d2c4", line: "#efe9dc", op: 0.28 },
  medium: { fill: "#c9a45c", line: "#e2c48a", op: 0.42 },
  heavy: { fill: "#8c6b3f", line: "#c39a5e", op: 0.62 },
};

export const SmokeMockup: React.FC<{ smoke?: SmokeData }> = ({ smoke }) => {
  const empty: SatView = { view: "base", band: "", bounds: null, frames: [] };
  const feats = Array.isArray(smoke?.features) ? smoke!.features : [];
  // Ligero primero: el humo denso queda ENCIMA (las pasadas se solapan).
  const order = ["light", "medium", "heavy"];
  const polygons: MapPolygon[] = feats
    .map((f) => ({ f, d: String(f?.properties?.density || "light").toLowerCase() }))
    .filter((x) => DENSITY[x.d])
    .sort((a, b) => order.indexOf(a.d) - order.indexOf(b.d))
    .map(({ f, d }) => ({
      data: f,
      fill: DENSITY[d].fill,
      line: DENSITY[d].line,
      fillOpacity: DENSITY[d].op,
    }));
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <SatMap
        sat={empty}
        center={[-96, 38]}
        zoom={3.4}
        fitBounds={CONUS_VIEW}
        fitPadding={CONUS_PAD}
        polygons={polygons}
        animatePolygons={false}
        cityMarkers={MAJOR_CITIES.slice(0, 10)}
        showSatellite={false}
      />
      <TopicBar topic="INCENDIOS Y HUMO" sub="ÚLTIMO ANÁLISIS HMS" topicColor="#F39C12" opacity={1} />
      {/* Leyenda de densidad, tamaño TV (Albert 12/09: "mucho más grande"). */}
      <div
        style={{
          position: "absolute",
          right: 48,
          bottom: 40,
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-end",
          gap: 10,
        }}
      >
        <div style={{ color: "#fff", fontSize: 38, fontWeight: 800, opacity: 0.95,
          textShadow: "0 3px 12px rgba(0,0,0,0.6)" }}>
          Densidad del humo
        </div>
        <div style={{ display: "flex", gap: 18 }}>
          {[["light", "Ligero"], ["medium", "Moderado"], ["heavy", "Denso"]].map(([k, txt]) => (
            <div key={k} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div
                style={{
                  width: 54,
                  height: 30,
                  borderRadius: 8,
                  background: DENSITY[k].fill,
                  opacity: Math.min(1, DENSITY[k].op + 0.35),
                  border: `2px solid ${DENSITY[k].line}`,
                }}
              />
              <span style={{ color: "#fff", fontSize: 30, fontWeight: 700,
                textShadow: "0 3px 10px rgba(0,0,0,0.6)" }}>{txt}</span>
            </div>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
