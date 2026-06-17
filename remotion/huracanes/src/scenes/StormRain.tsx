import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { SatMap } from "../components/SatMap";
import { TopicBar } from "../components/Overlay";
import { catKeyFor, tropCat, stormName } from "../lib/tropical";
import { FRAME_PADDING } from "../lib/cdn";
import { SatView, Storm } from "../types";

const { fontFamily } = loadFont();

// Leyenda horizontal de precipitación (in)
const PrecipLegend: React.FC<{
  colors: string[];
  vmax: number;
  accumulated: boolean;
  horizonH: number;
  opacity: number;
}> = ({ colors, vmax, accumulated, horizonH, opacity }) => {
  const days = Math.round(horizonH / 24);
  const horizon = days >= 2 ? `próximos ${days} días` : `próximas ${horizonH} h`;
  // 5 marcas de cantidad: 0 .. vmax
  const fmt = (v: number) => (vmax >= 4 ? Math.round(v).toString() : v.toFixed(1));
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * vmax);
  return (
    <div
      style={{
        position: "absolute",
        left: 56,
        bottom: 56,
        opacity,
        fontFamily,
        background: "rgba(13,26,38,0.85)",
        borderRadius: 14,
        padding: "14px 18px",
        border: "1px solid rgba(255,255,255,0.1)",
      }}
    >
      <div style={{ color: "#fff", fontSize: 20, fontWeight: 700, marginBottom: 8 }}>
        {accumulated ? `Lluvia acumulada · ${horizon}` : `Lluvia · ${horizon}`}
      </div>
      <div
        style={{
          width: 420,
          height: 16,
          borderRadius: 8,
          background: `linear-gradient(90deg, ${colors.join(", ")})`,
        }}
      />
      <div
        style={{
          position: "relative",
          width: 420,
          height: 22,
          marginTop: 6,
          color: "rgba(255,255,255,0.85)",
          fontSize: 16,
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        {ticks.map((v, i) => (
          <span
            key={i}
            style={{
              position: "absolute",
              left: `${(i / (ticks.length - 1)) * 100}%`,
              transform:
                i === 0
                  ? "translateX(0)"
                  : i === ticks.length - 1
                  ? "translateX(-100%)"
                  : "translateX(-50%)",
              whiteSpace: "nowrap",
            }}
          >
            {i === ticks.length - 1 ? `${fmt(v)}+ in` : fmt(v)}
          </span>
        ))}
      </div>
    </div>
  );
};

// Escena 3 por tormenta: precipitación acumulándose (animada) con zoom a la
// tormenta. NBM si está en EEUU, GFS global en caso contrario.
export const StormRain: React.FC<{ storm: Storm }> = ({ storm }) => {
  const frame = useCurrentFrame();
  const precip = storm._precip;
  const ck = catKeyFor(storm);
  const titleOpacity = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });

  // Sin datos de lluvia: fallback informativo.
  if (!precip || !precip.frames.length || !precip.bounds) {
    return (
      <AbsoluteFill
        style={{
          fontFamily,
          background: "#0d1a26",
          alignItems: "center",
          justifyContent: "center",
          color: "rgba(255,255,255,0.7)",
          fontSize: 34,
        }}
      >
        <TopicBar topic="LLUVIA" sub={stormName(storm).toUpperCase()} catKey={ck} opacity={1} />
        Datos de lluvia no disponibles
      </AbsoluteFill>
    );
  }

  const lon = storm.lon ?? -90;
  const lat = storm.lat ?? 15;
  const hasPos = storm.lon != null && storm.lat != null;
  const view: SatView = {
    view: "precip",
    band: "precip",
    bounds: precip.bounds,
    frames: precip.frames,
  };
  const cat = tropCat(ck);
  const txt = ck === "H1" ? "#1a2530" : "#fff";
  const badgeHTML = `<div style="width:50px;height:50px;border-radius:50%;background:${cat.color};border:3.5px solid #fff;color:${txt};display:flex;align-items:center;justify-content:center;font-weight:800;font-size:28px;line-height:1;box-shadow:0 6px 20px rgba(0,0,0,0.6);font-family:Outfit,system-ui,sans-serif;pointer-events:none">${cat.letter}</div>`;

  return (
    <AbsoluteFill style={{ fontFamily, background: "#000" }}>
      <SatMap
        sat={view}
        center={[lon, lat]}
        zoom={5}
        opacity={0.82}
        fitPoints={hasPos ? [{ lon: lon, lat: lat }] : []}
        marginDeg={3.5}
        minSpan={10}
        fitBounds={precip ? storm._coneBounds ?? storm._genesisBounds ?? null : null}
        fitPadding={FRAME_PADDING}
        dimWater={0.3}
        centerBadge={hasPos ? { lon: lon, lat: lat, html: badgeHTML } : undefined}
        coneStorm={storm}
      />

      <TopicBar
        topic="LLUVIA"
        sub={`${precip.model.toUpperCase()} · ${stormName(storm).toUpperCase()}`}
        catKey={ck}
        opacity={titleOpacity}
      />

      {precip.colors?.length ? (
        <PrecipLegend
          colors={precip.colors}
          vmax={precip.vmax ?? 2}
          accumulated={!!precip.accumulated}
          horizonH={precip.horizonH ?? 120}
          opacity={titleOpacity}
        />
      ) : null}
    </AbsoluteFill>
  );
};
