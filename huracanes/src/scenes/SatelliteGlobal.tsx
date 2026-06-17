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

// Vista global de la cuenca en IR REALZADO del disco-este (banda IR, JPG opaco).
// Esta toma es muy ancha (~70° de longitud), así que descartamos:
//   · GeoColor → deja SIEMPRE una franja nocturna negra (el terminador cae
//     dentro casi todo el día) → "el primer satélite se va a negro".
//   · windy IR → PNG transparente y pesado (8MB×n): los huecos de cielo despejado
//     muestran el mapa oscuro y algún frame puede no cargar → parpadeos a negro.
// El IR realzado es opaco (llena el cuadro siempre), uniforme día y noche, ligero,
// y colorea los topes fríos (convección) — el "look broadcast" original.
export const SatelliteGlobal: React.FC<{ sat?: SatData; storms?: Storm[] }> = ({
  sat,
  storms,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const s = satViewFromBand(sat, "ir");

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
        sub="INFRARROJO · DISCO ESTE"
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
