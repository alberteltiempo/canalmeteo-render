import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { BRAND, LOGO_URL } from "../lib/theme";

const { fontFamily } = loadFont();

export const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inAnim = spring({ frame, fps, config: { damping: 16 } });
  const opacity = interpolate(inAnim, [0, 1], [0, 1]);
  const y = interpolate(inAnim, [0, 1], [30, 0]);

  return (
    <AbsoluteFill
      style={{
        fontFamily,
        background: `radial-gradient(120% 120% at 50% 40%, ${BRAND.navyDark} 0%, ${BRAND.navyDeep} 100%)`,
        justifyContent: "center",
        alignItems: "center",
        gap: 26,
      }}
    >
      <Img src={LOGO_URL} style={{ width: 180, opacity, transform: `translateY(${y}px)` }} />
      <div style={{ opacity, transform: `translateY(${y}px)`, textAlign: "center", color: "#fff" }}>
        <div style={{ fontSize: 40, fontWeight: 800 }}>El tiempo 24/7 en Español</div>
        <div
          style={{
            display: "flex",
            gap: 40,
            justifyContent: "center",
            marginTop: 18,
            fontSize: 30,
            fontWeight: 700,
          }}
        >
          <span style={{ color: BRAND.orange }}>@canalmeteotv</span>
          <span style={{ color: BRAND.orange }}>@alberteltiempo</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};
