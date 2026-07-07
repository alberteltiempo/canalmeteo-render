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
import { BRAND, LOGO_URL, palette } from "../lib/theme";
import { ThemeMode } from "../types";

const { fontFamily } = loadFont();

// Portada "Vistazo al tiempo EEUU". El degradado depende del modo:
// navy en condiciones normales, crimson en Modo Rojo (tiempo severo/tornado).
export const Open: React.FC<{ mode?: ThemeMode }> = ({ mode = "normal" }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, height } = useVideoConfig();
  const pal = palette(mode);

  const logoIn = spring({ frame, fps, config: { damping: 14, mass: 0.6 } });
  const logoScale = interpolate(logoIn, [0, 1], [0.6, 1]);
  const logoY = interpolate(logoIn, [0, 1], [40, 0]);

  const textIn = spring({ frame: frame - 10, fps, config: { damping: 16, mass: 0.7 } });
  const textY = interpolate(textIn, [0, 1], [50, 0]);
  const textOpacity = interpolate(textIn, [0, 1], [0, 1]);

  // Barrido sutil de fondo
  const spin = (frame / fps) * 12;

  const fadeOut = interpolate(frame, [durationInFrames - 12, durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const exitScale = interpolate(frame, [durationInFrames - 12, durationInFrames], [1, 1.12], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        fontFamily,
        opacity: fadeOut,
        transform: `scale(${exitScale})`,
        background: `radial-gradient(120% 120% at 50% 35%, ${pal.openFrom} 0%, ${pal.openMid} 60%, ${pal.openTo} 100%)`,
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
        <div
          style={{
            width: height * 1.6,
            height: height * 1.6,
            borderRadius: "50%",
            transform: `rotate(${spin}deg)`,
            background:
              "conic-gradient(from 0deg, rgba(255,255,255,0.00) 0deg, rgba(255,255,255,0.06) 60deg, rgba(255,255,255,0.00) 140deg, rgba(255,255,255,0.05) 220deg, rgba(255,255,255,0.00) 320deg)",
            filter: "blur(8px)",
            opacity: 0.9,
          }}
        />
      </AbsoluteFill>

      <AbsoluteFill
        style={{
          background:
            "radial-gradient(80% 80% at 50% 50%, rgba(0,0,0,0) 55%, rgba(0,0,0,0.45) 100%)",
        }}
      />

      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", gap: 28 }}>
        <Img
          src={LOGO_URL}
          style={{
            width: 220,
            height: "auto",
            transform: `translateY(${logoY}px) scale(${logoScale})`,
            filter: "drop-shadow(0 8px 28px rgba(0,0,0,0.45))",
          }}
        />
        <div style={{ transform: `translateY(${textY}px)`, opacity: textOpacity, textAlign: "center" }}>
          <div
            style={{
              fontSize: 92,
              fontWeight: 800,
              color: BRAND.white,
              lineHeight: 1,
              textShadow: "0 6px 30px rgba(0,0,0,0.5)",
            }}
          >
            Vistazo al tiempo
          </div>
          <div
            style={{
              fontSize: 120,
              fontWeight: 800,
              color: BRAND.white,
              lineHeight: 1.05,
              marginTop: 8,
              letterSpacing: 4,
              textShadow: "0 6px 30px rgba(0,0,0,0.5)",
            }}
          >
            NOROESTE
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
