import React from "react";
import { Composition, Still } from "remotion";
import { ConusSegment, TRANSITION_FRAMES } from "./ConusSegment";
import { MapMockup } from "./scenes/MapMockup";
import { CondicionesMockup } from "./scenes/CondicionesMockup";
import { MOCKUPS, RELIEF_MOCKUPS, SYSTEM_MOCKUPS } from "./lib/mockups";
import {
  fetchGoesIr,
  fetchRadarOverlay,
  fetchNbmTemp,
  fetchCityConditions,
  fetchHrrrRadarForecast,
  fetchNbmPrecipAccum,
  fetchAlerts,
  computeMode,
  buildScenePlan,
  planDurationInFrames,
} from "./lib/cdn";
import type { ConusProps, ScenePlanItem, SatView, AlertsData, ThemeMode } from "./types";
import type { CityCond } from "./lib/conditions";

const FPS = 30;

type MetaProps = {
  plan: ScenePlanItem[];
  mode: ThemeMode;
  ir?: SatView;
  radar?: SatView;
  temp?: SatView;
  cityConds?: CityCond[];
  precipFcst?: SatView;
  precipAccum?: SatView;
  alerts?: AlertsData;
  alertCategories?: string[];
  // Si se fija ("normal"/"alert"), ignora el cálculo automático del Modo Rojo.
  forceMode?: ThemeMode | null;
};

async function computeMeta(
  props: MetaProps,
  abortSignal: AbortSignal,
  opts: { width: number; height: number }
) {
  const [ir, radar, temp, cityConds, precipFcst, precipAccum, alerts] = await Promise.all([
    // IR banda 13 con paleta propia + transparencia (sector CONUS).
    fetchGoesIr("conus", abortSignal),
    fetchRadarOverlay(abortSignal),
    // Temperatura NBM "ahora" + condiciones por ciudad (escena Condiciones ahora).
    fetchNbmTemp(abortSignal),
    fetchCityConditions(abortSignal),
    // "Radar a futuro" = reflectividad HRRR; acumulado 24 h = NBM.
    fetchHrrrRadarForecast(abortSignal),
    fetchNbmPrecipAccum(abortSignal),
    fetchAlerts(abortSignal),
  ]);
  const mode: ThemeMode = props.forceMode ?? computeMode(alerts);
  const plan = buildScenePlan();
  // TransitionSeries solapa las escenas: la duración total = suma − solapes.
  const durationInFrames =
    planDurationInFrames(plan, FPS) - Math.max(0, plan.length - 1) * TRANSITION_FRAMES;

  // eslint-disable-next-line no-console
  console.log(
    `[conus] ${opts.width}x${opts.height} · modo ${mode} · ${ir?.frames.length ?? 0} frames IR · ` +
      `${radar?.frames.length ?? 0} frames radar · ${temp?.frames.length ?? 0} frame temp · ` +
      `${cityConds?.length ?? 0} ciudades · ${precipFcst?.frames.length ?? 0} precip-fcst · ` +
      `${alerts?.watches.length ?? 0} alerta(s) · ${(durationInFrames / FPS).toFixed(1)}s`
  );

  return {
    durationInFrames,
    fps: FPS,
    width: opts.width,
    height: opts.height,
    props: { ...props, plan, mode, ir, radar, temp, cityConds, precipFcst, precipAccum, alerts },
  };
}

const DEFAULTS = {
  plan: [] as ScenePlanItem[],
  mode: "normal" as ThemeMode,
  ir: undefined as SatView | undefined,
  radar: undefined as SatView | undefined,
  temp: undefined as SatView | undefined,
  cityConds: [] as CityCond[],
  precipFcst: undefined as SatView | undefined,
  precipAccum: undefined as SatView | undefined,
  alerts: undefined as AlertsData | undefined,
  // Vacío → muestra todas las categorías de vigilancia presentes.
  alertCategories: [] as string[],
  forceMode: null as ThemeMode | null,
};

export const Root: React.FC = () => {
  return (
    <>
      <Composition
        id="ConusSegment"
        component={ConusSegment as any}
        durationInFrames={FPS * 30}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={DEFAULTS}
        calculateMetadata={async ({
          props,
          abortSignal,
        }: {
          props: MetaProps;
          abortSignal: AbortSignal;
        }) => computeMeta(props, abortSignal, { width: 1920, height: 1080 })}
      />

      {/* Mockup "Condiciones ahora" (capa de temperatura faux + cajas de ciudad).
          Still para pulir el look antes de cablear la capa NBM real. */}
      <Still
        id="Mockup-condiciones"
        component={CondicionesMockup as any}
        width={1920}
        height={1080}
        defaultProps={{}}
      />

      {/* Mockups de base cartográfica (Mockup-navy, Mockup-white-land, …). Stills
          estáticos para comparar looks de broadcast en Studio y exportar PNG. */}
      {[...MOCKUPS, ...RELIEF_MOCKUPS, ...SYSTEM_MOCKUPS].map((m) => (
        <Still
          key={m.id}
          id={`Mockup-${m.id}`}
          component={MapMockup as any}
          width={1920}
          height={1080}
          defaultProps={{ variant: m.id }}
        />
      ))}
    </>
  );
};
