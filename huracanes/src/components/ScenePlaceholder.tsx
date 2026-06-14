import React from "react";
import { AbsoluteFill } from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { BRAND } from "../lib/theme";

const { fontFamily } = loadFont();

// Marco visual provisional para escenas en construcción.
// Muestra el rótulo de la escena + datos reales para validar el timeline.
export const ScenePlaceholder: React.FC<{
  topic: string;
  topicColor?: string;
  title?: string;
  subtitle?: string;
  children?: React.ReactNode;
}> = ({ topic, topicColor = BRAND.blue, title, subtitle, children }) => {
  return (
    <AbsoluteFill
      style={{
        fontFamily,
        background: `linear-gradient(160deg, ${BRAND.navyDeep} 0%, ${BRAND.navyDark} 100%)`,
        color: "#fff",
      }}
    >
      {/* Barra de tópico estilo Canal Meteo */}
      <div
        style={{
          position: "absolute",
          top: 48,
          left: 48,
          display: "flex",
          alignItems: "stretch",
          borderRadius: 10,
          overflow: "hidden",
          boxShadow: "0 6px 24px rgba(0,0,0,0.4)",
        }}
      >
        <div
          style={{
            background: topicColor,
            padding: "12px 22px",
            fontWeight: 800,
            fontSize: 22,
            letterSpacing: 1,
          }}
        >
          {topic}
        </div>
      </div>

      <AbsoluteFill
        style={{ justifyContent: "center", alignItems: "center", gap: 16, padding: 80 }}
      >
        {title ? (
          <div style={{ fontSize: 64, fontWeight: 800, textAlign: "center" }}>{title}</div>
        ) : null}
        {subtitle ? (
          <div style={{ fontSize: 28, color: "rgba(255,255,255,0.7)", textAlign: "center" }}>
            {subtitle}
          </div>
        ) : null}
        {children}
        <div
          style={{
            marginTop: 24,
            fontSize: 16,
            color: BRAND.orange,
            border: `1px dashed ${BRAND.orange}`,
            borderRadius: 8,
            padding: "6px 14px",
          }}
        >
          escena en construcción
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
