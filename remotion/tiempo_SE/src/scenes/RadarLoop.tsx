import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { SatMap } from "../components/SatMap";
import { TopicBar, TimeBar } from "../components/Overlay";
import { CONUS_VIEW, CONUS_PAD, loopFrameIndex } from "../lib/cdn";
import { MAJOR_CITIES } from "../lib/cities";
import { SatView, ThemeMode } from "../types";
import { palette } from "../lib/theme";

const { fontFamily } = loadFont();

// Radar MRMS de CONUS: PNG de reflectividad TRANSPARENTES drapeados sobre el mapa
// base "sistema" (igual que el satélite), para que todos los mapas se vean igual.
export const RadarLoop: React.FC<{ radar?: SatView; mode?: ThemeMode }> = ({
  radar,
  mode = "normal",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pal = palette(mode);

  const view: SatView = radar || { view: "mrms", band: "refl", bounds: null, frames: [] };
  const n = view.frames.length;
  // Mismo índice de bucle que SatMap, para que la barra de tiempo vaya sincronizada.
  const idx = loopFrameIndex(frame, fps, n);

  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ fontFamily, background: "#000" }}>
      <SatMap
        sat={view}
        center={[-96, 38]}
        zoom={3.4}
        opacity={1}
        fitBounds={CONUS_VIEW}
        fitPadding={CONUS_PAD}
        cityMarkers={MAJOR_CITIES}
        showSatellite={true}
      />

      <AbsoluteFill
        style={{
          background:
            "linear-gradient(180deg, rgba(0,0,0,0.5) 0%, rgba(0,0,0,0) 20%, rgba(0,0,0,0) 80%, rgba(0,0,0,0.45) 100%)",
          pointerEvents: "none",
        }}
      />

      <TopicBar topic="RADAR" sub="REFLECTIVIDAD" topicColor={pal.topicColor} opacity={op} />
      {n > 1 ? (
        <TimeBar
          startUnix={view.frames[0].time}
          endUnix={view.frames[n - 1].time}
          curUnix={view.frames[idx].time}
          centerLabel="radar reciente"
          accent={pal.accent}
          opacity={op}
        />
      ) : null}
    </AbsoluteFill>
  );
};
