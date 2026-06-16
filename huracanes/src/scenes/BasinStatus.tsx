import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { SatMap } from "../components/SatMap";
import { TopicBar } from "../components/Overlay";
import { satViewFromBand, BASIN_VIEW, genesisAreasForBasin, geoBounds } from "../lib/cdn";
import { BRAND } from "../lib/theme";
import { SatData, Basin, ActiveStorms } from "../types";

const { fontFamily } = loadFont();

// Recorta un bbox [[oeste,sur],[este,norte]] a la cobertura del satélite, dejando
// un pequeño margen para no pegar el encuadre al borde exacto del disco. Si no
// hay bounds (o el solape es nulo), devuelve el bbox original sin tocar.
function clampBoxToSat(
  box: [[number, number], [number, number]],
  bounds: SatData["bounds"]
): [[number, number], [number, number]] {
  if (!bounds) return box;
  const m = 1; // grados de margen hacia dentro del disco
  const w = Math.max(box[0][0], bounds.west + m);
  const e = Math.min(box[1][0], bounds.east - m);
  const s = Math.max(box[0][1], bounds.south + m);
  const n = Math.min(box[1][1], bounds.north - m);
  if (w >= e || s >= n) return box; // sin solape útil → no recortar
  return [
    [w, s],
    [e, n],
  ];
}

const BASIN_NAME: Record<Basin, string> = {
  atlantic: "Cuenca Atlántica",
  epac: "Cuenca del Pacífico Oriental",
};

// Color y etiqueta por nivel de riesgo de formación (NHC: amarillo/naranja/rojo)
const RISK = {
  low: { color: "#f4d03f", label: "Baja", range: "menos del 40%" },
  medium: { color: "#e67e22", label: "Media", range: "40-60%" },
  high: { color: "#e74c3c", label: "Alta", range: "más del 60%" },
} as const;
type RiskKey = keyof typeof RISK;
const RISK_RANK: Record<RiskKey, number> = { low: 1, medium: 2, high: 3 };

// Slide al cierre de una cuenca:
//  - mode "none": "No hay tormentas activas" (GeoColor de la cuenca + caja verde)
//  - mode "monitoring": "Zona en vigilancia" → dibuja el/los polígono(s) de
//    génesis del NHC, encuadra a la zona y muestra la probabilidad de formación.
export const BasinStatus: React.FC<{
  basin: Basin;
  sat?: SatData;
  mode: "none" | "monitoring";
  data?: ActiveStorms;
}> = ({ basin, sat, mode, data }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const view = satViewFromBand(sat, "geocolor");
  const monitoring = mode === "monitoring";

  // Áreas de génesis de esta cuenca (solo en modo monitoreo)
  const areas = monitoring && data ? genesisAreasForBasin(data, basin) : [];
  const hasAreas = areas.length > 0;

  // Normalizadores: el NHC publica risk como "Low/Medium/High" y prob como "10%"
  const riskKey = (v: any): RiskKey | undefined => {
    const t = String(v || "").toLowerCase();
    if (t.startsWith("high")) return "high";
    if (t.startsWith("med")) return "medium";
    if (t.startsWith("low")) return "low";
    return undefined;
  };
  const probNum = (v: any): number | null => {
    const m = String(v ?? "").match(/-?\d+(\.\d+)?/);
    return m ? Math.round(parseFloat(m[0])) : null;
  };

  // Riesgo y probabilidad máximos entre las áreas de la cuenca
  let topRisk: RiskKey = "low";
  let topProb: number | null = null;
  areas.forEach((a) => {
    const pr = a?.properties || {};
    const rk = riskKey(pr.risk7day) || riskKey(pr.risk2day);
    if (rk && RISK_RANK[rk] > RISK_RANK[topRisk]) topRisk = rk;
    const p = probNum(pr.prob7day) ?? probNum(pr.prob2day);
    if (p != null && (topProb == null || p > topProb)) topProb = p;
  });
  const risk = RISK[topRisk];

  // Encuadre: a la(s) zona(s) si las hay; si no, a la cuenca entera
  const basinBox = BASIN_VIEW[basin];
  const fc = { type: "FeatureCollection", features: areas } as any;
  const areaBox = hasAreas ? geoBounds(fc) : null;
  // Recorta el encuadre a la cobertura real del satélite para no mostrar bandas
  // negras fuera del disco (p.ej. el borde del Pacífico que GOES-East no ve).
  const box = clampBoxToSat(areaBox || basinBox, view.bounds);
  const center: [number, number] = [(box[0][0] + box[1][0]) / 2, (box[0][1] + box[1][1]) / 2];

  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const cardIn = spring({ frame: frame - 6, fps, config: { damping: 16 } });
  const cardScale = interpolate(cardIn, [0, 1], [0.9, 1]);

  const accent = monitoring ? risk.color : "#2ecc71";
  const title = monitoring ? "Zona en vigilancia" : "No hay tormentas activas";
  const sub = monitoring
    ? topProb != null
      ? `Probabilidad de formación a 7 días: ${topProb}% (${risk.label})`
      : "El NHC monitorea una posible zona de desarrollo"
    : `${BASIN_NAME[basin]} · sin sistemas tropicales`;

  // Polígonos a dibujar (con su color de riesgo)
  const polygons = hasAreas
    ? areas.map((a) => {
        const pr = a?.properties || {};
        const rk = riskKey(pr.risk7day) || riskKey(pr.risk2day) || "low";
        const c = RISK[rk]?.color || RISK.low.color;
        return { data: a, fill: c, line: c, fillOpacity: 0.32 };
      })
    : undefined;

  return (
    <AbsoluteFill style={{ fontFamily, background: "#000" }}>
      <SatMap
        sat={view}
        center={center}
        zoom={hasAreas ? 4.2 : 3.4}
        fitBounds={box}
        fitPadding={
          hasAreas
            ? { top: 220, bottom: 320, left: 160, right: 160 }
            : { top: 120, bottom: 120, left: 90, right: 90 }
        }
        opacity={op}
        polygons={polygons}
      />

      <TopicBar topic="TRÓPICO" sub={BASIN_NAME[basin].toUpperCase()} opacity={op} />

      {/* Caja inferior (deja ver el polígono encuadrado arriba) */}
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
              background: accent,
              margin: "0 auto 22px",
            }}
          />
          <div style={{ fontSize: 60, fontWeight: 800, color: "#fff", lineHeight: 1.05 }}>
            {title}
          </div>
          <div style={{ fontSize: 30, color: "rgba(255,255,255,0.85)", marginTop: 14 }}>{sub}</div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
