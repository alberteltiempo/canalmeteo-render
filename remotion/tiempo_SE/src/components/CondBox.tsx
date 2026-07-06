import React from "react";
import { Sky, CityCond, fmtTemp, tempColor } from "../lib/conditions";

// Iconos de cielo (SVG inline; fiables en headless, sin depender de emoji).
export const SkyIcon: React.FC<{ sky: Sky; size?: number }> = ({ sky, size = 46 }) => {
  const s = size;
  const sun = "#FFC83D";
  const cloud = "#E7EDF2";
  const cloudDark = "#B7C2cc";
  const drop = "#5BA6FF";
  const bolt = "#FFD23D";
  const snow = "#DDE9F5";
  const Cloud = ({ x = 0, y = 0, fill = cloud }: { x?: number; y?: number; fill?: string }) => (
    <path d={`M${x + 7} ${y + 22} a7 7 0 0 1 1 -13 a9 9 0 0 1 17 -2 a6 6 0 0 1 2 15 z`} fill={fill} />
  );
  return (
    <svg width={s} height={s} viewBox="0 0 36 36" style={{ display: "block" }}>
      {sky === "sol" && (
        <>
          {[...Array(8)].map((_, i) => (
            <rect key={i} x={17} y={2} width={2} height={6} rx={1} fill={sun} transform={`rotate(${i * 45} 18 18)`} />
          ))}
          <circle cx={18} cy={18} r={8} fill={sun} />
        </>
      )}
      {sky === "nubes-claros" && (
        <>
          {[...Array(8)].map((_, i) => (
            <rect key={i} x={11} y={1} width={1.6} height={4.5} rx={1} fill={sun} transform={`rotate(${i * 45} 12 12)`} />
          ))}
          <circle cx={12} cy={12} r={6} fill={sun} />
          <Cloud x={6} y={9} />
        </>
      )}
      {sky === "nublado" && (
        <>
          <Cloud x={2} y={4} fill={cloudDark} />
          <Cloud x={8} y={9} />
        </>
      )}
      {sky === "lluvia" && (
        <>
          <Cloud x={5} y={3} />
          {[10, 17, 24].map((x) => (
            <rect key={x} x={x} y={26} width={2.4} height={7} rx={1.2} fill={drop} transform={`rotate(15 ${x} 28)`} />
          ))}
        </>
      )}
      {sky === "tormenta" && (
        <>
          <Cloud x={5} y={3} fill={cloudDark} />
          <polygon points="18,25 13,33 17,33 14,40 24,30 19,30 22,25" fill={bolt} />
        </>
      )}
      {sky === "nieve" && (
        <>
          <Cloud x={5} y={3} />
          {[11, 18, 25].map((x) => (
            <text key={x} x={x} y={33} fontSize="9" fill={snow} textAnchor="middle">
              ❄
            </text>
          ))}
        </>
      )}
    </svg>
  );
};

// Caja de condición por ciudad (símbolo + temperatura + nombre + viento).
export const CondBox: React.FC<{ c: CityCond }> = ({ c }) => {
  const accent = tempColor(c.tempF);
  return (
    <div
      style={{
        background: "rgba(13,24,34,0.86)",
        border: "1px solid rgba(255,255,255,0.16)",
        borderLeft: `5px solid ${accent}`,
        borderRadius: 14,
        padding: "10px 15px 11px 14px",
        boxShadow: "0 10px 26px rgba(0,0,0,0.5)",
        backdropFilter: "blur(2px)",
        minWidth: 165,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
        <SkyIcon sky={c.sky} size={58} />
        <span
          style={{
            fontSize: 52,
            fontWeight: 800,
            color: "#fff",
            lineHeight: 1,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {fmtTemp(c.tempF)}
        </span>
      </div>
      <div style={{ fontSize: 29, fontWeight: 700, color: "#fff", marginTop: 6, whiteSpace: "nowrap" }}>
        {c.name}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
        <span style={{ display: "inline-block", fontSize: 25, color: "#cfe0ee", transform: `rotate(${c.windDeg}deg)` }}>
          ↑
        </span>
        <span style={{ fontSize: 25, color: "rgba(255,255,255,0.85)" }}>{Math.round(c.windMph)} mph</span>
      </div>
    </div>
  );
};
