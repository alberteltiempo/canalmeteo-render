import React from "react";
import { AbsoluteFill, Audio, Series, interpolate, staticFile } from "remotion";
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
import { SpcScene, TmaxScene, TvarScene } from "./scenes/ForecastMockups";
import { FrontsScene, ReportsScene, DroughtScene } from "./scenes/SurfaceScenes";
import { QuakeIntro, QuakeScene } from "./scenes/QuakeScene";

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
  fronts,
  reports,
  drought,
  spc,
  tmaxTodayRaster,
  tmaxTomorrowRaster,
  tdeltaRaster,
  tmaxToday,
  tmaxTomorrow,
  tmaxPopToday,
  tmaxPopTomorrow,
  quake,
}) => {
  // Duración total del segmento (suma de todas las escenas del plan) → para el
  // fundido de salida de la música de fondo.
  const totalFrames = plan.reduce((a, s) => a + Math.round(s.seconds * FPS), 0);
  return (
    <AbsoluteFill style={{ fontFamily, background: "#000" }}>
      {/* Música de fondo (loop, volumen bajo) con fundido de entrada/salida. */}
      <Audio
        src={staticFile("audio/Musica_CONUS_ZOOM_SE.mp3")}
        loop
        volume={(f) =>
          interpolate(
            f,
            [0, FPS * 1, totalFrames - FPS * 1.5, totalFrames],
            [0, 0.22, 0.22, 0],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
          )
        }
      />
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
              fronts,
              reports,
              drought,
              spc,
              tmaxTodayRaster,
              tmaxTomorrowRaster,
              tdeltaRaster,
              tmaxToday,
              tmaxTomorrow,
              tmaxPopToday,
              tmaxPopTomorrow,
              quake,
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
    case "quake_intro":
      return <QuakeIntro quake={ctx.quake} />;
    case "quake":
      return <QuakeScene quake={ctx.quake} />;
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
    case "fronts":
      return <FrontsScene fronts={ctx.fronts} mode={ctx.mode} />;
    case "reports":
      return <ReportsScene reports={ctx.reports} mode={ctx.mode} />;
    case "drought":
      return <DroughtScene drought={ctx.drought} mode={ctx.mode} />;
    case "aeropuertos":
      return <AirportsScene airports={ctx.airports} mode={ctx.mode} />;
    case "uv":
      return <UvScene uv={ctx.uv} mode={ctx.mode} />;
    case "aqi":
      return <AqiScene aqi={ctx.aqi} mode={ctx.mode} />;
    case "spc":
      return <SpcScene spc={ctx.spc} mode={ctx.mode} />;
    case "tmax_today":
      return (
        <TmaxScene
          cities={ctx.tmaxToday}
          raster={ctx.tmaxTodayRaster}
          pop={ctx.tmaxPopToday}
          sub="HOY"
          mode={ctx.mode}
        />
      );
    case "tmax_tomorrow":
      return (
        <TmaxScene
          cities={ctx.tmaxTomorrow}
          raster={ctx.tmaxTomorrowRaster}
          pop={ctx.tmaxPopTomorrow}
          sub="MAÑANA"
          mode={ctx.mode}
        />
      );
    case "tvar":
      return (
        <TvarScene today={ctx.tmaxToday} tomorrow={ctx.tmaxTomorrow} raster={ctx.tdeltaRaster} mode={ctx.mode} />
      );
    case "outro":
      return <Outro />;
    default:
      return null;
  }
}
