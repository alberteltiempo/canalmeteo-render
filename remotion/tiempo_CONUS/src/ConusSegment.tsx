import React from "react";
import { AbsoluteFill, Series } from "remotion";
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
// Corte seco entre escenas (sin cross-dissolve). MOTIVO: con disolvencia se montan
// DOS mapas WebGL a la vez y el segundo pierde el contexto GL (mapa en negro, p. ej.
// el radar). Como todas las escenas comparten proyección y base idéntica, el corte
// es imperceptible: el fondo no salta, solo cambia el contenido (cada escena hace
// su propio fade-in). 0 = sin solape (lo usa Root para la duración total).
export const TRANSITION_FRAMES = 0;

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
      <Series>
        {plan.map((s) => (
          <Series.Sequence key={s.id} durationInFrames={Math.round(s.seconds * FPS)}>
            {renderScene(s, {
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
            })}
          </Series.Sequence>
        ))}
      </Series>
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
