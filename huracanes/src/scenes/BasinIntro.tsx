import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { BRAND } from "../lib/theme";
import { Basin } from "../types";

const { fontFamily } = loadFont();

const TITLE: Record<Basin, string> = {
  atlantic: "Cuenca Atlántica",
  epac: "Cuenca del Pacífico Oriental",
};

// Slide de transición entre cuencas (marca Canal Meteo).
export const BasinIntro: React.FC<{ basin: Basin }> = ({ basin }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inAnim = spring({ frame, fps, config: { damping: 18 } });
  const x = interpolate(inAnim, [0, 1], [-60, 0]);
  const op = interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{
        fontFamily,
        background: `linear-gradient(135deg, ${BRAND.navyDeep} 0%, ${BRAND.navy} 60%, ${BRAND.blue} 130%)`,
        alignItems: "flex-start",
        justifyContent: "center",
        padding: "0 140px",
      }}
    >
      <div style={{ opacity: op, transform: `translateX(${x}px)` }}>
        <div
          style={{
            fontSize: 32,
            letterSpacing: 8,
            fontWeight: 700,
            color: BRAND.orange,
            textTransform: "uppercase",
            marginBottom: 18,
          }}
        >
          Temporada 2026
        </div>
        <div style={{ fontSize: 104, fontWeight: 800, color: "#fff", lineHeight: 1 }}>
          {TITLE[basin]}
        </div>
        <div
          style={{
            marginTop: 26,
            width: 220,
            height: 8,
            borderRadius: 4,
            background: BRAND.orange,
          }}
        />
      </div>
    </AbsoluteFill>
  );
};
