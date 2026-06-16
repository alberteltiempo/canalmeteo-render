import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { Storm } from "../types";
import {
  catKeyFor,
  ktToMph,
  tropCat,
  tropShortLabel,
  fmtBulletinTime,
  formatMovement,
  stormName,
} from "../lib/tropical";

const { fontFamily } = loadFont();
const mono = "'JetBrains Mono', monospace";

export const DataCard: React.FC<{ storm: Storm }> = ({ storm }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const inAnim = spring({ frame, fps, config: { damping: 16 } });
  const x = interpolate(inAnim, [0, 1], [-90, 0]);
  const opacity = interpolate(inAnim, [0, 1], [0, 1]);

  const ck = catKeyFor(storm);
  const cat = tropCat(ck);
  const textOnChip = ck === "H1" ? "#1a2530" : "#fff";

  const windMph = ktToMph(storm.intensity_kt);
  const gustMph = ktToMph(storm._cur?.gust ?? null);
  const mslp = storm._cur?.mslp ?? null;
  const movStr = formatMovement(storm.movement_dir, storm.movement_mph);

  return (
    <div
      style={{
        position: "absolute",
        left: 56,
        bottom: 56,
        transform: `translateX(${x}px)`,
        opacity,
        fontFamily,
        width: 600,
        background: "rgba(13,26,38,0.9)",
        backdropFilter: "blur(8px)",
        borderRadius: 24,
        overflow: "hidden",
        boxShadow: "0 18px 56px rgba(0,0,0,0.55)",
        border: "1px solid rgba(255,255,255,0.1)",
      }}
    >
      {/* Cabecera con color de categoría */}
      <div
        style={{
          background: cat.color,
          color: textOnChip,
          padding: "22px 30px",
          display: "flex",
          alignItems: "center",
          gap: 18,
        }}
      >
        <div
          style={{
            width: 62,
            height: 62,
            borderRadius: "50%",
            border: `3.5px solid ${textOnChip}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 800,
            fontSize: 34,
            flexShrink: 0,
          }}
        >
          {cat.letter}
        </div>
        <div>
          <div style={{ fontSize: 46, fontWeight: 800, lineHeight: 1 }}>{stormName(storm)}</div>
          <div style={{ fontSize: 22, fontWeight: 600, opacity: 0.88, marginTop: 3 }}>
            {tropShortLabel(ck)}
          </div>
        </div>
      </div>

      {/* Cuerpo */}
      <div style={{ padding: "24px 30px 26px", color: "#fff" }}>
        {/* Viento sostenido — destacado */}
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
          <span style={{ fontSize: 22, color: "rgba(255,255,255,0.72)" }}>
            Viento máx. sostenido
          </span>
          <span style={{ fontSize: 64, fontWeight: 800, fontFamily: mono, lineHeight: 1 }}>
            {windMph != null ? windMph : "—"}
            <span style={{ fontSize: 28, fontWeight: 600, marginLeft: 8 }}>mph</span>
          </span>
        </div>

        {/* Grid: ráfagas, presión, movimiento */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: "16px 30px",
            marginTop: 22,
          }}
        >
          <Stat label="Ráfagas" value={gustMph != null ? `${gustMph} mph` : "—"} />
          <Stat label="Presión" value={mslp != null ? `${mslp} mb` : "—"} />
          {movStr ? <Stat label="Movimiento" value={movStr} /> : null}
        </div>

        {/* Hora del boletín */}
        {storm.last_update ? (
          <div
            style={{
              marginTop: 22,
              paddingTop: 16,
              borderTop: "1px solid rgba(255,255,255,0.12)",
              fontSize: 18,
              color: "rgba(255,255,255,0.6)",
            }}
          >
            Boletín: {fmtBulletinTime(storm.last_update)}
          </div>
        ) : null}
      </div>
    </div>
  );
};

const Stat: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div>
    <div style={{ fontSize: 18, color: "rgba(255,255,255,0.6)" }}>{label}</div>
    <div style={{ fontSize: 34, fontWeight: 800, fontFamily: mono, marginTop: 2 }}>{value}</div>
  </div>
);
