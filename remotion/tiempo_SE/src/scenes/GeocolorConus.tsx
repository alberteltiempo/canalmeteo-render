import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { SatMap } from "../components/SatMap";
import { TopicBar } from "../components/Overlay";
import { CONUS_VIEW, CONUS_PAD } from "../lib/cdn";
import { MAJOR_CITIES } from "../lib/cities";
import { SatView, ThemeMode } from "../types";
import { palette } from "../lib/theme";

const { fontFamily } = loadFont();

const EMPTY_IR: SatView = { view: "goes_ir_conus", band: "ir", bounds: null, frames: [] };

// Satélite IR (banda 13, paleta propia + transparencia) sobre el mapa base, con
// rótulos grandes de ciudad. Entrada tipo push-in desde la portada.
export const GeocolorConus: React.FC<{ ir?: SatView; mode?: ThemeMode }> = ({
  ir,
  mode = "normal",
}) => {
  const frame = useCurrentFrame();
  const pal = palette(mode);

  const s = ir || EMPTY_IR;

  // La disolvencia entre escenas la hace TransitionSeries (ConusSegment); aquí la
  // escena va opaca. `op` solo funde los rótulos al entrar.
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ fontFamily, background: "#000" }}>
      <SatMap
        sat={s}
        center={[-96, 38]}
        zoom={3.4}
        fitBounds={CONUS_VIEW}
        fitPadding={CONUS_PAD}
        cityMarkers={MAJOR_CITIES}
        opacity={1}
        showSatellite={true}
      />

      <AbsoluteFill
        style={{
          background:
            "linear-gradient(180deg, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0) 22%, rgba(0,0,0,0) 78%, rgba(0,0,0,0.45) 100%)",
          pointerEvents: "none",
        }}
      />

      <TopicBar topic="SATÉLITE" sub="INFRARROJO · EE. UU." topicColor={pal.topicColor} opacity={op} />
    </AbsoluteFill>
  );
};
