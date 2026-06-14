import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { TopicBar } from "../components/Overlay";
import { BRAND } from "../lib/theme";
import { NAMES_2026, BASIN_LABEL, nameStatuses } from "../lib/names2026";
import { Basin } from "../types";

const { fontFamily } = loadFont();

// Escena: lista oficial de nombres de la temporada para la cuenca, marcando
// los ya formados, el/los activos y los que quedan por usar.
export const NameList: React.FC<{ basin: Basin; activeNames: string[] }> = ({
  basin,
  activeNames,
}) => {
  const frame = useCurrentFrame();
  const list = NAMES_2026[basin];
  const status = nameStatuses(basin, activeNames);

  const titleOpacity = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const pulse = 0.5 + 0.5 * Math.sin(frame / 6); // brillo de los activos

  return (
    <AbsoluteFill style={{ fontFamily, background: BRAND.navyDeep }}>
      <TopicBar
        topic="NOMBRES 2026"
        sub={BASIN_LABEL[basin]}
        topicColor={BRAND.blue}
        opacity={titleOpacity}
      />

      {/* Rejilla de nombres */}
      <div
        style={{
          position: "absolute",
          top: 170,
          left: 56,
          right: 56,
          bottom: 120,
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 16,
          alignContent: "center",
        }}
      >
        {list.map((nm, i) => {
          const st = status[i];
          const appear = 8 + i * 1.2;
          const a = interpolate(frame, [appear, appear + 8], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });

          let bg = "rgba(255,255,255,0.05)";
          let color = "rgba(255,255,255,0.82)";
          let border = "1px solid rgba(255,255,255,0.12)";
          let weight = 600;
          let glow = "none";
          if (st === "past") {
            bg = "rgba(69,122,153,0.28)"; // azul Canal Meteo apagado = ya formada
            color = "rgba(255,255,255,0.55)";
            border = "1px solid rgba(69,122,153,0.5)";
          } else if (st === "active") {
            bg = BRAND.orange;
            color = "#1a2530";
            border = "2px solid #fff";
            weight = 800;
            glow = `0 0 ${10 + 16 * pulse}px rgba(243,156,18,${0.5 + 0.4 * pulse})`;
          }

          return (
            <div
              key={nm}
              style={{
                opacity: a,
                transform: `translateY(${(1 - a) * 14}px)`,
                background: bg,
                color,
                border,
                boxShadow: glow,
                borderRadius: 12,
                padding: "16px 18px",
                fontSize: 30,
                fontWeight: weight,
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <span>{nm}</span>
              {st === "active" ? (
                <span style={{ fontSize: 20, fontWeight: 800 }}>ACTIVA</span>
              ) : st === "past" ? (
                <span style={{ fontSize: 22, opacity: 0.8 }}>✓</span>
              ) : null}
            </div>
          );
        })}
      </div>

      {/* Leyenda */}
      <div
        style={{
          position: "absolute",
          bottom: 48,
          left: 56,
          display: "flex",
          gap: 34,
          opacity: titleOpacity,
          color: "#fff",
          fontSize: 22,
          fontWeight: 600,
          alignItems: "center",
        }}
      >
        <LegendDot color="rgba(69,122,153,0.6)" label="Ya formada" />
        <LegendDot color={BRAND.orange} label="Activa" />
        <LegendDot color="rgba(255,255,255,0.18)" label="Por usar" />
      </div>
    </AbsoluteFill>
  );
};

const LegendDot: React.FC<{ color: string; label: string }> = ({ color, label }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
    <div style={{ width: 20, height: 20, borderRadius: "50%", background: color }} />
    <span>{label}</span>
  </div>
);
