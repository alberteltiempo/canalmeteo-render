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

// Leyenda de tipos de precipitación: lluvia (verde / reflectividad), nieve (azul),
// hielo (rosa). `reflectivity` usa la escala radar verde→amarillo→rojo para lluvia.
const PrecipLegend: React.FC<{ opacity: number; reflectivity?: boolean }> = ({
  opacity,
  reflectivity = false,
}) => {
  const rain = reflectivity
    ? "linear-gradient(90deg,#78e178,#28b446,#f0e646,#f5963c,#e12828,#961010)"
    : "linear-gradient(90deg,#b2eba0,#6ec878,#2da54b,#147838)";
  const bars: { label: string; grad: string }[] = [
    { label: "Lluvia", grad: rain },
    { label: "Nieve", grad: "linear-gradient(90deg,#cde6ff,#78b0f0,#4678e1,#5f3cb9,#872396)" },
    { label: "Hielo", grad: "linear-gradient(90deg,#ffcde4,#ee82b4,#cd3282,#96145f)" },
  ];
  return (
    <div
      style={{
        position: "absolute",
        right: 48,
        bottom: 36,
        display: "flex",
        gap: 22,
        opacity,
      }}
    >
      {bars.map((b) => (
        <div key={b.label} style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          <div style={{ color: "#fff", fontSize: 17, fontWeight: 700, opacity: 0.92 }}>{b.label}</div>
          <div
            style={{
              width: 150,
              height: 13,
              borderRadius: 7,
              border: "1px solid rgba(255,255,255,0.3)",
              background: b.grad,
            }}
          />
        </div>
      ))}
    </div>
  );
};

// "RADAR A FUTURO": bucle horario de la precipitación NBM próximas 24 h,
// coloreada por tipo (lluvia/nieve/hielo). Una pasada lenta a lo largo de la escena.
export const PrecipForecast: React.FC<{ precip?: SatView; mode?: ThemeMode }> = ({
  precip,
  mode = "normal",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pal = palette(mode);
  const view: SatView =
    precip || { view: "nbm_precip_fcst", band: "precip", bounds: null, frames: [] };
  const n = view.frames.length;
  const SECONDS_PER_LOOP = 7; // una pasada por las 24 h ≈ duración de escena
  const idx = loopFrameIndex(frame, fps, n, SECONDS_PER_LOOP);
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ fontFamily, background: "#000" }}>
      <SatMap
        sat={view}
        center={[-96, 38]}
        zoom={3.4}
        fitBounds={CONUS_VIEW}
        fitPadding={CONUS_PAD}
        cityMarkers={MAJOR_CITIES}
        showSatellite={true}
        opacity={0.92}
        secondsPerLoop={SECONDS_PER_LOOP}
      />
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          background:
            "linear-gradient(180deg, rgba(0,0,0,0.5) 0%, rgba(0,0,0,0) 20%, rgba(0,0,0,0) 80%, rgba(0,0,0,0.5) 100%)",
        }}
      />
      <TopicBar topic="RADAR A FUTURO" sub="REFLECTIVIDAD SIMULADA · HRRR" topicColor={pal.topicColor} opacity={op} />
      {n > 1 ? (
        <TimeBar
          startUnix={view.frames[0].time}
          endUnix={view.frames[n - 1].time}
          curUnix={view.frames[idx].time}
          centerLabel="pronóstico"
          accent={pal.accent}
          opacity={op}
        />
      ) : null}
      <PrecipLegend opacity={op} reflectivity />
    </AbsoluteFill>
  );
};

// "PRECIPITACIÓN 24 H": total acumulado de las próximas 24 h por tipo.
export const PrecipAccum: React.FC<{ precip?: SatView; mode?: ThemeMode }> = ({
  precip,
  mode = "normal",
}) => {
  const frame = useCurrentFrame();
  const pal = palette(mode);
  const view: SatView =
    precip || { view: "nbm_precip_accum", band: "precip", bounds: null, frames: [] };
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ fontFamily, background: "#000" }}>
      <SatMap
        sat={view}
        center={[-96, 38]}
        zoom={3.4}
        fitBounds={CONUS_VIEW}
        fitPadding={CONUS_PAD}
        cityMarkers={MAJOR_CITIES}
        showSatellite={true}
        opacity={0.95}
      />
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          background:
            "linear-gradient(180deg, rgba(0,0,0,0.5) 0%, rgba(0,0,0,0) 20%, rgba(0,0,0,0) 80%, rgba(0,0,0,0.5) 100%)",
        }}
      />
      <TopicBar topic="PRECIPITACIÓN" sub="PRÓXIMAS 24 HORAS" topicColor={pal.topicColor} opacity={op} />
      <PrecipLegend opacity={op} />
    </AbsoluteFill>
  );
};
