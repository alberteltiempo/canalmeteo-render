import React from "react";
import {
  AbsoluteFill,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { SatMap } from "../components/SatMap";
import { TopicBar, TimeBar } from "../components/Overlay";
import { satViewFromBand } from "../lib/cdn";
import { SatData, Storm } from "../types";

const { fontFamily } = loadFont();

// Vista global del Disco Este en INFRARROJO (look broadcast). Encuadra todas las
// tormentas activas (fitBounds). Animación de los últimos frames (3h).
export const SatelliteGlobal: React.FC<{ sat?: SatData; storms?: Storm[] }> = ({
  sat,
  storms,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const s = satViewFromBand(sat, "geocolor");

  const n = s.frames.length;
  const idx = n
    ? Math.min(n - 1, Math.floor((frame / Math.max(1, durationInFrames - 1)) * (n - 1)))
    : 0;
  const t = n ? new Date(s.frames[idx].time * 1000) : null;
  void t;

  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  // Entrada tipo "push-in" de cámara desde la portada
  const introScale = interpolate(frame, [0, 20], [1.06, 1], {
    extrapolateRight: "clamp",
  });
  const introFade = interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{ fontFamily, background: "#000", transform: `scale(${introScale})`, opacity: introFade }}
    >
      <SatMap
        sat={s}
        center={[-72, 22]}
        zoom={2.4}
        opacity={0.95}
        fitBounds={[
          [-108, 6],
          [-38, 44],
        ]}
        fitPadding={{ top: 60, bottom: 60, left: 40, right: 40 }}
      />

      <AbsoluteFill
        style={{
          background:
            "linear-gradient(180deg, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0) 24%, rgba(0,0,0,0) 80%, rgba(0,0,0,0.4) 100%)",
          pointerEvents: "none",
        }}
      />

      <TopicBar
        topic="SATÉLITE"
        sub={s.band === "ir" ? "INFRARROJO · DISCO ESTE" : "GEOCOLOR · DISCO ESTE"}
        opacity={op}
      />
      {n > 1 ? (
        <TimeBar
          startUnix={s.frames[0].time}
          endUnix={s.frames[n - 1].time}
          curUnix={s.frames[idx].time}
          opacity={op}
        />
      ) : null}
    </AbsoluteFill>
  );
};
