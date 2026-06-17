import React from "react";
import { AbsoluteFill } from "remotion";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { ConusProps, ScenePlanItem } from "./types";
import { Open } from "./components/Open";
import { Outro } from "./components/Outro";
import { GeocolorConus } from "./scenes/GeocolorConus";
import { CondicionesNow } from "./scenes/CondicionesNow";
import { PrecipForecast, PrecipAccum } from "./scenes/PrecipScenes";
import { RadarLoop } from "./scenes/RadarLoop";
import { Alerts } from "./scenes/Alerts";
import { AirportsScene, UvScene, AqiScene } from "./scenes/ServicesMockups";

const { fontFamily } = loadFont();
const FPS = 30;
// Disolvencia entre escenas. Todas comparten cámara, así que el fondo no salta y
// la disolvencia funde solo el contenido. Mantener corto: durante el solape se
// montan DOS mapas WebGL → coste de GPU.
export const TRANSITION_FRAMES = 12;

// Corte seco entre escenas (sin cross-dissolve): nunca monta dos mapas WebGL a la
// vez → render mucho más rápido en CPU.
export const ConusSegment: React.FC<ConusProps> = ({
  plan,
  mode,
  ir,
  radar,
  temp,
  cityConds,
  precipFcst,
  precipAccum,
  alerts,
  alertCategories,
  airports,
  uv,
  aqi,
}) => {
  return (
    <AbsoluteFill style={{ fontFamily, background: "#000" }}>
      <TransitionSeries>
        {plan.flatMap((s, i) => {
          const seq = (
            <TransitionSeries.Sequence
              key={s.id}
              durationInFrames={Math.round(s.seconds * FPS)}
            >
              {renderScene(s, { mode, ir, radar, temp, cityConds, precipFcst, precipAccum, alerts, alertCategories, airports, uv, aqi })}
            </TransitionSeries.Sequence>
          );
          if (i === 0) return [seq];
          return [
            <TransitionSeries.Transition
              key={`t-${s.id}`}
              timing={linearTiming({ durationInFrames: TRANSITION_FRAMES })}
              presentation={fade()}
            />,
            seq,
          ];
        })}
      </TransitionSeries>
    </AbsoluteFill>
  );
};

function renderScene(
  s: ScenePlanItem,
  ctx: Omit<ConusProps, "plan">
): React.ReactNode {
  switch (s.type) {
    case "open":
      return <Open mode={ctx.mode} />;
    case "geocolor":
      return <GeocolorConus ir={ctx.ir} mode={ctx.mode} />;
    case "condiciones":
      return <CondicionesNow temp={ctx.temp} cityConds={ctx.cityConds} mode={ctx.mode} />;
    case "precip_fcst":
      return <PrecipForecast precip={ctx.precipFcst} mode={ctx.mode} />;
    case "precip_accum":
      return <PrecipAccum precip={ctx.precipAccum} mode={ctx.mode} />;
    case "radar":
      return <RadarLoop radar={ctx.radar} mode={ctx.mode} />;
    case "alerts":
      return <Alerts alerts={ctx.alerts} mode={ctx.mode} categories={ctx.alertCategories} />;
    case "aeropuertos":
      return <AirportsScene airports={ctx.airports} mode={ctx.mode} />;
    case "uv":
      return <UvScene uv={ctx.uv} mode={ctx.mode} />;
    case "aqi":
      return <AqiScene aqi={ctx.aqi} mode={ctx.mode} />;
    case "outro":
      return <Outro />;
    default:
      return null;
  }
}
