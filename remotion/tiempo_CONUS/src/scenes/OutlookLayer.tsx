// OutlookLayer.tsx — capa genérica de data/outlooks sobre la base "sistema TV".
// 11/09/2026: sustituye a los mapas de lynx-hub CONUS_SPC_Day_1_{Wind,Tornado,Hail}
// y CONUS_CPC_{Temps,Precip}_6_10_Day. El PNG del manifest es RGBA transparente y
// ya viene georreferenciado por bounds, así que se drapea como cualquier ráster;
// el título sale del propio manifest (el pipeline lo da en español).
import React from "react";
import { AbsoluteFill } from "remotion";
import { SatMap } from "../components/SatMap";
import { TopicBar } from "../components/Overlay";
import { CONUS_VIEW, CONUS_PAD, OutlookMeta, OutlookLegendStop } from "../lib/cdn";
import { MAJOR_CITIES } from "../lib/cities";
import type { SatView } from "../types";

// Leyenda CPC: paradas discretas (33…90 % prob) por encima y por debajo de lo
// normal. Se pinta como barra continua: below invertido + above.
const gradientFromStops = (below: OutlookLegendStop[], above: OutlookLegendStop[]) => {
  const cols = [...[...below].reverse().map((s) => s.color), ...above.map((s) => s.color)];
  if (!cols.length) return "linear-gradient(90deg, #888, #888)";
  const step = 100 / (cols.length - 1 || 1);
  return `linear-gradient(90deg, ${cols.map((c, i) => `${c} ${Math.round(i * step)}%`).join(", ")})`;
};

const LegendBar: React.FC<{ meta: OutlookMeta; kind?: string }> = ({ meta, kind }) => {
  const lg = meta.legend;
  if (!lg?.above?.length && !lg?.below?.length) return null;
  const below = lg?.below || [];
  const above = lg?.above || [];
  const maxBelow = below.length ? Math.max(...below.map((x) => x.value)) : null;
  const maxAbove = above.length ? Math.max(...above.map((x) => x.value)) : null;
  // El CPC da probabilidad de estar por debajo/encima de lo normal: el extremo
  // izquierdo y el derecho llegan los dos al 90 %, así que se etiquetan por lado.
  const seco = kind === "cpc_p";
  const izq = maxBelow != null ? `${maxBelow}% ${seco ? "más seco" : "más frío"}` : "";
  const der = maxAbove != null ? `${maxAbove}% ${seco ? "más lluvioso" : "más cálido"}` : "";
  return (
    <div
      style={{
        position: "absolute",
        right: 44,
        bottom: 44,
        padding: "18px 26px 20px",
        borderRadius: 18,
        background: "rgba(12,26,38,0.82)",
        border: "1px solid rgba(255,255,255,0.18)",
        boxShadow: "0 10px 34px rgba(0,0,0,0.55)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 10,
      }}
    >
      <div style={{ color: "#fff", fontSize: 30, fontWeight: 800, letterSpacing: 0.4 }}>
        Probabilidad ({lg?.units || "% prob"})
      </div>
      <div
        style={{
          width: 620,
          height: 30,
          borderRadius: 15,
          background: gradientFromStops(below, above),
          border: "2px solid rgba(255,255,255,0.45)",
        }}
      />
      <div style={{ display: "flex", justifyContent: "space-between", width: 620 }}>
        <span style={{ color: "#cfe3f5", fontSize: 26, fontWeight: 700 }}>{izq}</span>
        <span style={{ color: "#ffd9b0", fontSize: 26, fontWeight: 700 }}>{der}</span>
      </div>
    </div>
  );
};

export const OutlookLayerMockup: React.FC<{
  raster?: SatView;
  meta?: OutlookMeta;
  topic?: string;
  sub?: string;
  topicColor?: string;
  // Nº de ciudades de referencia: pocas en SPC (que no tapen las bandas).
  cities?: number;
}> = ({ raster, meta, topic, sub, topicColor = "#F39C12", cities = 8 }) => {
  const empty: SatView = { view: "outlook", band: "", bounds: null, frames: [] };
  // El manifest trae "SPC Prob. viento · Día 1": la parte tras "·" va de subtítulo.
  const title = topic ?? (meta?.title || "").split("·")[0].trim().toUpperCase();
  const subtitle = sub ?? (meta?.title || "").split("·").slice(1).join("·").trim().toUpperCase();
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <SatMap
        sat={raster || empty}
        center={[-96, 38]}
        zoom={3.4}
        fitBounds={CONUS_VIEW}
        fitPadding={CONUS_PAD}
        cityMarkers={MAJOR_CITIES.slice(0, cities)}
        showSatellite
        belowBorders
        opacity={0.92}
      />
      <TopicBar topic={title || "OUTLOOK"} sub={subtitle} topicColor={topicColor} opacity={1} />
      {meta ? <LegendBar meta={meta} kind={meta.kind} /> : null}
    </AbsoluteFill>
  );
};
