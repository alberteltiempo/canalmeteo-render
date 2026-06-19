import React from "react";
import { Composition, Still } from "remotion";
import { ConusSegment, TRANSITION_FRAMES } from "./ConusSegment";
import { MapMockup } from "./scenes/MapMockup";
import { CondicionesMockup } from "./scenes/CondicionesMockup";
import { AirportsMockup, UvMockup, AqiMockup } from "./scenes/ServicesMockups";
import {
  SpcOutlookMockup,
  TmaxTodayMockup,
  TmaxTomorrowMockup,
  TvarMockup,
} from "./scenes/ForecastMockups";
import { MOCKUPS, RELIEF_MOCKUPS, SYSTEM_MOCKUPS } from "./lib/mockups";
import {
  fetchGoesIr,
  fetchRadarOverlay,
  fetchNbmTemp,
  fetchCityConditions,
  fetchHrrrRadarForecast,
  fetchNbmPrecipAccum,
  fetchAlerts,
  fetchAirports,
  fetchUv,
  fetchAqi,
  fetchSpcOutlook,
  fetchTmaxCities,
  fetchTmaxTodayRaster,
  fetchTmaxTomorrowRaster,
  fetchTdeltaRaster,
  computeMode,
  buildScenePlan,
  planDurationInFrames,
} from "./lib/cdn";
import type {
  ConusProps,
  ScenePlanItem,
  SatView,
  AlertsData,
  ThemeMode,
  Airport,
  UvCity,
  AqiCity,
  SpcOutlook,
  TmaxCity,
} from "./types";
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
  airports?: Airport[];
  uv?: UvCity[];
  aqi?: AqiCity[];
  spc?: SpcOutlook | null;
  tmaxTodayRaster?: SatView;
  tmaxTomorrowRaster?: SatView;
  tdeltaRaster?: SatView;
  tmaxToday?: TmaxCity[];
  tmaxTomorrow?: TmaxCity[];
  // Si se fija ("normal"/"alert"), ignora el cálculo automático del Modo Rojo.
  forceMode?: ThemeMode | null;
};

async function computeMeta(
  props: MetaProps,
  abortSignal: AbortSignal,
  opts: { width: number; height: number }
) {
  const [
    ir,
    radar,
    temp,
    cityConds,
    precipFcst,
    precipAccum,
    alerts,
    airports,
    uv,
    aqi,
    spc,
    tmaxCities,
    tmaxTodayRaster,
    tmaxTomorrowRaster,
    tdeltaRaster,
  ] = await Promise.all([
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
    // Servicios CONUS: demoras FAA, índice UV (EPA), calidad del aire (AirNow).
    fetchAirports(abortSignal),
    fetchUv(abortSignal),
    fetchAqi(abortSignal),
    // Cierre nacional: riesgo severo SPC + temperatura máxima (ráster + ciudades).
    fetchSpcOutlook(abortSignal),
    fetchTmaxCities(abortSignal),
    fetchTmaxTodayRaster(abortSignal),
    fetchTmaxTomorrowRaster(abortSignal),
    fetchTdeltaRaster(abortSignal),
  ]);
  const mode: ThemeMode = props.forceMode ?? computeMode(alerts);
  const tmaxToday = tmaxCities.today;
  const tmaxTomorrow = tmaxCities.tomorrow;
  // Escenas del cierre que solo se incluyen si hay datos (p. ej. la máxima de HOY
  // falta en runs de tarde → se omite esa escena y la de variación).
  const plan = buildScenePlan({
    spc: spc != null,
    tmaxToday: tmaxToday.length > 0,
    tvar: tmaxToday.length > 0 && tmaxTomorrow.length > 0,
    tmaxTomorrow: tmaxTomorrow.length > 0,
  });
  // Cortes secos (Series, sin solape): la duración total = suma de escenas.
  // TRANSITION_FRAMES = 0, así que el término de solape se anula.
  const durationInFrames =
    planDurationInFrames(plan, FPS) - Math.max(0, plan.length - 1) * TRANSITION_FRAMES;

  // eslint-disable-next-line no-console
  console.log(
    `[conus] ${opts.width}x${opts.height} · modo ${mode} · ${ir?.frames.length ?? 0} frames IR · ` +
      `${radar?.frames.length ?? 0} frames radar · ${temp?.frames.length ?? 0} frame temp · ` +
      `${cityConds?.length ?? 0} ciudades · ${precipFcst?.frames.length ?? 0} precip-fcst · ` +
      `${alerts?.watches.length ?? 0} alerta(s) · ${airports?.length ?? 0} aerop. · ` +
      `${uv?.length ?? 0} uv · ${aqi?.length ?? 0} aqi · spc ${spc ? spc.categorical.length : "—"} · ` +
      `tmax ${tmaxToday.length}/${tmaxTomorrow.length} · ${(durationInFrames / FPS).toFixed(1)}s`
  );

  return {
    durationInFrames,
    fps: FPS,
    width: opts.width,
    height: opts.height,
    props: {
      ...props,
      plan,
      mode,
      ir,
      radar,
      temp,
      cityConds,
      precipFcst,
      precipAccum,
      alerts,
      airports,
      uv,
      aqi,
      spc,
      tmaxToday,
      tmaxTomorrow,
      tmaxTodayRaster,
      tmaxTomorrowRaster,
      tdeltaRaster,
    },
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
  airports: [] as Airport[],
  uv: [] as UvCity[],
  aqi: [] as AqiCity[],
  spc: null as SpcOutlook | null,
  tmaxTodayRaster: undefined as SatView | undefined,
  tmaxTomorrowRaster: undefined as SatView | undefined,
  tdeltaRaster: undefined as SatView | undefined,
  tmaxToday: [] as TmaxCity[],
  tmaxTomorrow: [] as TmaxCity[],
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

      {/* Mockups de servicios CONUS (datos puntuales por ciudad/aeropuerto):
          demoras FAA, índice UV (EPA) y calidad del aire AQI (AirNow). */}
      <Still id="Mockup-aeropuertos" component={AirportsMockup as any} width={1920} height={1080} defaultProps={{}} />
      <Still id="Mockup-uv" component={UvMockup as any} width={1920} height={1080} defaultProps={{}} />
      <Still id="Mockup-aqi" component={AqiMockup as any} width={1920} height={1080} defaultProps={{}} />

      {/* Mockups del cierre nacional: riesgo severo SPC + bloque de temperatura
          (máx hoy, variación mañana, máx mañana). Datos de muestra. */}
      <Still id="Mockup-spc" component={SpcOutlookMockup as any} width={1920} height={1080} defaultProps={{}} />
      <Still id="Mockup-tmax-hoy" component={TmaxTodayMockup as any} width={1920} height={1080} defaultProps={{}} />
      <Still id="Mockup-tvar-manana" component={TvarMockup as any} width={1920} height={1080} defaultProps={{}} />
      <Still id="Mockup-tmax-manana" component={TmaxTomorrowMockup as any} width={1920} height={1080} defaultProps={{}} />

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
