import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { BRAND } from "../lib/theme";
import { catKeyFor, tropCat, stormName } from "../lib/tropical";
import { genesisZoneCount } from "../lib/cdn";
import { ActiveStorms } from "../types";

const { fontFamily } = loadFont();

// Slide inicial: número de tormentas activas + nombres en fila (aparición escalonada).
export const CountIntro: React.FC<{ data?: ActiveStorms }> = ({ data }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const storms = data?.storms || [];
  // Un invest no es una tormenta nombrada → se cuenta aparte para no inflar el
  // titular ("N tormentas activas"). Los chips sí muestran ambos (con badge "I").
  const n = storms.filter((s) => !s.is_invest).length;
  const nInv = storms.filter((s) => s.is_invest).length;
  // Zonas de génesis distintas (deduplica el área-polígono y el/los punto(s)
  // que el NHC publica para la MISMA perturbación). Ver genesisZones en cdn.ts.
  const zones = data ? genesisZoneCount(data) : 0;

  const titleIn = spring({ frame, fps, config: { damping: 16 } });
  const titleY = interpolate(titleIn, [0, 1], [40, 0]);
  const titleOp = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });

  const bigText =
    n > 0
      ? `${n} tormenta${n === 1 ? "" : "s"} activa${n === 1 ? "" : "s"}`
      : nInv > 0
      ? `${nInv} invest${nInv === 1 ? "" : "s"} en seguimiento`
      : "Sin tormentas activas";

  return (
    <AbsoluteFill
      style={{
        fontFamily,
        background: `linear-gradient(135deg, ${BRAND.navyDeep} 0%, ${BRAND.navy} 55%, ${BRAND.blue} 130%)`,
        alignItems: "center",
        justifyContent: "center",
        padding: "0 120px",
      }}
    >
      <div
        style={{
          opacity: titleOp,
          transform: `translateY(${titleY}px)`,
          textAlign: "center",
        }}
      >
        <div
          style={{
            fontSize: 30,
            letterSpacing: 8,
            fontWeight: 700,
            color: BRAND.orange,
            textTransform: "uppercase",
            marginBottom: 16,
          }}
        >
          Vistazo al Trópico
        </div>
        <div style={{ fontSize: n === 0 ? 92 : 116, fontWeight: 800, color: "#fff", lineHeight: 1 }}>
          {bigText}
        </div>
        {n > 0 && nInv > 0 ? (
          <div style={{ fontSize: 34, color: "rgba(255,255,255,0.85)", marginTop: 18 }}>
            + {nInv} invest{nInv === 1 ? "" : "s"} en seguimiento
          </div>
        ) : n === 0 && nInv === 0 && zones > 0 ? (
          <div style={{ fontSize: 34, color: "rgba(255,255,255,0.85)", marginTop: 18 }}>
            {zones} zona{zones === 1 ? "" : "s"} en vigilancia
          </div>
        ) : null}
      </div>

      {/* Nombres en fila, con color de categoría, apareciendo escalonados */}
      {storms.length > 0 ? (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 22,
            justifyContent: "center",
            marginTop: 54,
            maxWidth: 1500,
          }}
        >
          {storms.map((s, i) => {
            const ck = catKeyFor(s);
            const cat = tropCat(ck);
            const txt = ck === "H1" ? "#1a2530" : "#fff";
            const delay = 14 + i * 7;
            const chipIn = spring({ frame: frame - delay, fps, config: { damping: 15 } });
            const op = interpolate(frame - delay, [0, 8], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            const y = interpolate(chipIn, [0, 1], [30, 0]);
            return (
              <div
                key={s.id}
                style={{
                  opacity: op,
                  transform: `translateY(${y}px)`,
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                  background: "rgba(13,26,38,0.55)",
                  border: "1px solid rgba(255,255,255,0.14)",
                  borderRadius: 999,
                  padding: "12px 26px 12px 12px",
                }}
              >
                <div
                  style={{
                    width: 52,
                    height: 52,
                    borderRadius: "50%",
                    background: cat.color,
                    color: txt,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontWeight: 800,
                    fontSize: 26,
                    flexShrink: 0,
                  }}
                >
                  {cat.letter}
                </div>
                <span style={{ color: "#fff", fontSize: 38, fontWeight: 800 }}>{stormName(s)}</span>
              </div>
            );
          })}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
