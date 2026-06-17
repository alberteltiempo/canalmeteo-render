import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { SatMap } from "../components/SatMap";
import { TopicBar } from "../components/Overlay";
import { satViewDayNight } from "../lib/cdn";
import { catKeyFor, tropCat, stormName } from "../lib/tropical";
import { SatData, SatView, Storm } from "../types";

const { fontFamily } = loadFont();

// Color y etiqueta por nivel de riesgo de formación (NHC: amarillo/naranja/rojo)
const RISK = {
  low: { color: "#f4d03f", label: "Baja", range: "menos del 40%" },
  medium: { color: "#e67e22", label: "Media", range: "40-60%" },
  high: { color: "#e74c3c", label: "Alta", range: "más del 60%" },
} as const;
type RiskKey = keyof typeof RISK;

function riskKey(v: unknown): RiskKey {
  const t = String(v || "").toLowerCase();
  if (t.startsWith("high")) return "high";
  if (t.startsWith("med")) return "medium";
  return "low";
}

// Escena 2 de un invest (en lugar de la trayectoria, que aún no existe): caja de
// situación con la probabilidad de formación a 7 días del NHC, encuadrada sobre
// el satélite en la posición del sistema.
export const InvestStatus: React.FC<{ storm: Storm; sat?: SatData; ir?: SatView }> = ({
  storm,
  sat,
  ir,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const lon = storm.lon ?? -90;
  const lat = storm.lat ?? 15;
  const hasPos = storm.lon != null && storm.lat != null;
  // IR windy (colorido + transparente) si está disponible; si no, GeoColor/IR del
  // disco según día/noche.
  const useWindy = !!(ir && ir.frames.length && ir.bounds);
  const view = useWindy ? (ir as SatView) : satViewDayNight(sat, lat, lon);
  const ck = catKeyFor(storm); // "INV"
  const cat = tropCat(ck);

  const rk = riskKey(storm.genesis_risk);
  const risk = RISK[rk];
  const prob = storm.genesis_prob;

  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const cardIn = spring({ frame: frame - 6, fps, config: { damping: 16 } });
  const cardScale = interpolate(cardIn, [0, 1], [0.9, 1]);

  const sub =
    prob != null
      ? `Probabilidad de formación a 7 días: ${prob}% (${risk.label})`
      : "El NHC vigila este sistema en busca de desarrollo tropical";

  const badgeHTML = `<div style="width:64px;height:64px;border-radius:50%;background:${cat.color};border:4px solid #fff;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:34px;line-height:1;box-shadow:0 8px 28px rgba(0,0,0,0.55);font-family:Outfit,system-ui,sans-serif;pointer-events:none">${cat.letter}</div>`;

  return (
    <AbsoluteFill style={{ fontFamily, background: "#000" }}>
      <SatMap
        sat={view}
        center={[lon, lat]}
        zoom={4.6}
        opacity={op}
        fitPoints={hasPos ? [{ lon, lat }] : []}
        marginDeg={5}
        minSpan={12}
        centerBadge={hasPos ? { lon, lat, html: badgeHTML } : undefined}
      />

      <TopicBar
        topic="SITUACIÓN"
        sub={stormName(storm).toUpperCase()}
        catKey={ck}
        opacity={op}
      />

      {/* Caja de situación (deja ver el sistema encuadrado arriba) */}
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "flex-end", paddingBottom: 90 }}>
        <div
          style={{
            opacity: op,
            transform: `scale(${cardScale})`,
            background: "rgba(13,26,38,0.9)",
            border: "1px solid rgba(255,255,255,0.14)",
            borderRadius: 22,
            padding: "34px 60px",
            textAlign: "center",
            boxShadow: "0 20px 60px rgba(0,0,0,0.55)",
            maxWidth: 1180,
          }}
        >
          <div
            style={{
              width: 120,
              height: 8,
              borderRadius: 4,
              background: risk.color,
              margin: "0 auto 22px",
            }}
          />
          <div style={{ fontSize: 60, fontWeight: 800, color: "#fff", lineHeight: 1.05 }}>
            Zona en vigilancia
          </div>
          <div style={{ fontSize: 30, color: "rgba(255,255,255,0.85)", marginTop: 14 }}>{sub}</div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
