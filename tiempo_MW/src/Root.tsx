import React from "react";
import { Composition, Sequence, Still } from "remotion";
import { ConusSegment, TRANSITION_FRAMES } from "./ConusSegment";
import { MapMockup } from "./scenes/MapMockup";
import { CondicionesMockup } from "./scenes/CondicionesMockup";
import { CondicionesNow } from "./scenes/CondicionesNow";
import { AirportsMockup, UvMockup, AqiMockup } from "./scenes/ServicesMockups";
import {
  SpcOutlookMockup,
  TmaxTodayMockup,
  TmaxTomorrowMockup,
  TvarMockup,
} from "./scenes/ForecastMockups";
import { FrontsScene, ReportsScene, DroughtScene } from "./scenes/SurfaceScenes";
import { QuakeIntroMockup, QuakeMockup } from "./scenes/QuakeScene";
import { MOCKUPS, RELIEF_MOCKUPS, SYSTEM_MOCKUPS } from "./lib/mockups";
import {
  fetchQuake,
  fetchEscaleta,
  escForStill,
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
  fetchFronts,
  fetchStormReports,
  fetchDrought,
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
  FrontsData,
  StormReportsData,
  DroughtData,
  SpcOutlook,
  TmaxCity,
  TmaxPop,
  Quake,
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
  fronts?: FrontsData | null;
  reports?: StormReportsData | null;
  drought?: DroughtData | null;
  spc?: SpcOutlook | null;
  tmaxTodayRaster?: SatView;
  tmaxTomorrowRaster?: SatView;
  tdeltaRaster?: SatView;
  tmaxToday?: TmaxCity[];
  tmaxTomorrow?: TmaxCity[];
  tmaxPopToday?: TmaxPop;
  tmaxPopTomorrow?: TmaxPop;
  quake?: Quake | null;
  // Si se fija ("normal"/"alert"), ignora el cálculo automático del Modo Rojo.
  forceMode?: ThemeMode | null;
};

async function computeMeta(
  props: MetaProps,
  abortSignal: AbortSignal,
  opts: { width: number; height: number }
) {
  // Escaleta editable (intranet): null → defaults de código. Va ANTES del
  // Promise.all: sus listas de ciudades condicionan los feeds por ciudad.
  const escaleta = await fetchEscaleta(abortSignal);
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
    fronts,
    reports,
    drought,
    spc,
    tmaxCities,
    tmaxTodayRaster,
    tmaxTomorrowRaster,
    tdeltaRaster,
    quake,
  ] = await Promise.all([
    // IR banda 13 con paleta propia + transparencia (sector CONUS).
    fetchGoesIr("conus", abortSignal),
    fetchRadarOverlay(abortSignal),
    // Temperatura NBM "ahora" + condiciones por ciudad (escena Condiciones ahora).
    fetchNbmTemp(abortSignal),
    fetchCityConditions(abortSignal, escaleta),
    // "Radar a futuro" = reflectividad HRRR; acumulado 24 h = NBM.
    fetchHrrrRadarForecast(abortSignal),
    fetchNbmPrecipAccum(abortSignal),
    fetchAlerts(abortSignal),
    // Servicios CONUS: demoras FAA, índice UV (EPA), calidad del aire (AirNow).
    fetchAirports(abortSignal, escaleta),
    fetchUv(abortSignal, escaleta),
    fetchAqi(abortSignal, escaleta),
    // Mapa de superficie (frentes/presión), reportes de tormenta 24 h y sequía.
    fetchFronts(abortSignal),
    fetchStormReports(abortSignal),
    fetchDrought(abortSignal),
    // Cierre nacional: riesgo severo SPC + temperatura máxima (ráster + ciudades).
    fetchSpcOutlook(abortSignal),
    fetchTmaxCities(abortSignal, escaleta),
    fetchTmaxTodayRaster(abortSignal),
    fetchTmaxTomorrowRaster(abortSignal),
    fetchTdeltaRaster(abortSignal),
    // Última hora: terremoto fuerte (M≥5.5) sobre EEUU (USGS). null si no hay.
    fetchQuake(abortSignal),
  ]);
  const mode: ThemeMode = props.forceMode ?? computeMode(alerts);
  const tmaxToday = tmaxCities.today;
  const tmaxTomorrow = tmaxCities.tomorrow;
  const tmaxPopToday = tmaxCities.popToday;
  const tmaxPopTomorrow = tmaxCities.popTomorrow;
  // Escenas del cierre que solo se incluyen si hay datos (p. ej. la máxima de HOY
  // falta en runs de tarde → se omite esa escena y la de variación).
  const plan = buildScenePlan({
    quake: quake != null,
    fronts: fronts != null && (fronts.points.length > 0 || fronts.lines.length > 0),
    reports: reports != null && reports.reports.length > 0,
    drought: drought != null && drought.levels.length > 0,
    spc: spc != null,
    tmaxToday: tmaxToday.length > 0,
    tvar: tmaxToday.length > 0 && tmaxTomorrow.length > 0,
    tmaxTomorrow: tmaxTomorrow.length > 0,
  }, escaleta);
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
      `${uv?.length ?? 0} uv · ${aqi?.length ?? 0} aqi · ` +
      `frentes ${fronts ? fronts.lines.length + "L/" + fronts.points.length + "P" : "—"} · ` +
      `reportes ${reports ? reports.total : "—"} · sequía ${drought ? drought.levels.length + "niv" : "—"} · ` +
      `spc ${spc ? spc.categorical.length : "—"} · ` +
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
      escaleta,
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
      fronts,
      reports,
      drought,
      spc,
      tmaxToday,
      tmaxTomorrow,
      tmaxPopToday,
      tmaxPopTomorrow,
      tmaxTodayRaster,
      tmaxTomorrowRaster,
      tdeltaRaster,
      quake,
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
  fronts: null as FrontsData | null,
  reports: null as StormReportsData | null,
  drought: null as DroughtData | null,
  spc: null as SpcOutlook | null,
  tmaxTodayRaster: undefined as SatView | undefined,
  tmaxTomorrowRaster: undefined as SatView | undefined,
  tdeltaRaster: undefined as SatView | undefined,
  tmaxToday: [] as TmaxCity[],
  tmaxTomorrow: [] as TmaxCity[],
  tmaxPopToday: undefined as TmaxPop | undefined,
  tmaxPopTomorrow: undefined as TmaxPop | undefined,
  quake: null as Quake | null,
  forceMode: null as ThemeMode | null,
};

// Escenas de mapa/animación SIN still propio (portada, geocolor, radar, alertas,
// precipitación y cierre): su preview renderiza el Segment REAL (mismos datos y
// escaleta que la antena) con el plan reducido a esa escena. El Sequence con
// `from` negativo desplaza el tiempo a mitad de escena para verla ya
// desarrollada (Freeze NO vale: recorta el frame a la duración, 1). Son
// <Composition> de 1 frame y NO <Still>: el Still fuerza fps=1 y las
// ventanas del plan (segundos × fps) se quedarían cortas.
const PREV_SCENES = ["open", "geocolor", "radar", "alerts", "precip_fcst", "precip_accum", "outro"];

const PrevScene: React.FC<any> = ({ offsetFrames = 0, ...rest }) => (
  <Sequence from={-offsetFrames} durationInFrames={offsetFrames + 1}>
    <ConusSegment {...rest} />
  </Sequence>
);

export const Root: React.FC = () => {
  return (
    <>
      <Composition
        id="MwSegment"
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

      {/* Preview REAL de "Condiciones ahora" para el editor de escaletas: datos
          vivos (NBM + weather.json) + escaleta aplicada (cámara, escala y
          posiciones fijadas), congelada en el frame 0 (animate=false). */}
      <Still
        id="Prev-condiciones"
        component={CondicionesNow as any}
        width={1920}
        height={1080}
        defaultProps={{ animate: false }}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          const escaleta = await fetchEscaleta(abortSignal);
          const [temp, cityConds] = await Promise.all([
            fetchNbmTemp(abortSignal),
            fetchCityConditions(abortSignal, escaleta),
          ]);
          return { props: { ...props, temp, cityConds, escaleta: escForStill(props, escaleta), animate: false } };
        }}
      />

      {/* Mockups de servicios CONUS (datos puntuales por ciudad/aeropuerto):
          demoras FAA, índice UV (EPA) y calidad del aire AQI (AirNow). */}
      <Still id="Mockup-aeropuertos" component={AirportsMockup as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          const escaleta = await fetchEscaleta(abortSignal);
          const airports = await fetchAirports(abortSignal, escaleta);
          return { props: { ...props, airports, escaleta: escForStill(props, escaleta) } };
        }} />
      <Still id="Mockup-uv" component={UvMockup as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          const escaleta = await fetchEscaleta(abortSignal);
          const uv = await fetchUv(abortSignal, escaleta);
          return { props: { ...props, uv, escaleta: escForStill(props, escaleta) } };
        }} />
      <Still id="Mockup-aqi" component={AqiMockup as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          const escaleta = await fetchEscaleta(abortSignal);
          const aqi = await fetchAqi(abortSignal, escaleta);
          return { props: { ...props, aqi, escaleta: escForStill(props, escaleta) } };
        }} />

      {/* Mockups de mapa nacional con DATOS REALES (Still + calculateMetadata):
          mapa de superficie (frentes/presión), reportes de tormenta y sequía.
          animate=false para que las capas se vean en el frame 0. */}
      <Still
        id="Mockup-frentes"
        component={FrontsScene as any}
        width={1920}
        height={1080}
        defaultProps={{ animate: false }}
        calculateMetadata={async ({ props, abortSignal }: any) => ({
          props: { ...props, fronts: await fetchFronts(abortSignal), animate: false },
        })}
      />
      <Still
        id="Mockup-reportes"
        component={ReportsScene as any}
        width={1920}
        height={1080}
        defaultProps={{ animate: false }}
        calculateMetadata={async ({ props, abortSignal }: any) => ({
          props: { ...props, reports: await fetchStormReports(abortSignal), animate: false },
        })}
      />
      <Still
        id="Mockup-sequia"
        component={DroughtScene as any}
        width={1920}
        height={1080}
        defaultProps={{ animate: false }}
        calculateMetadata={async ({ props, abortSignal }: any) => ({
          props: { ...props, drought: await fetchDrought(abortSignal), animate: false },
        })}
      />

      {/* Última hora · Terremoto: cartel previo + mapa del epicentro. Con quake
          real (feed USGS) si lo hay; sin él, la muestra de diseño. */}
      <Still id="Mockup-quake-intro" component={QuakeIntroMockup as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => ({ props: { ...props, quake: await fetchQuake(abortSignal) } })} />
      <Still id="Mockup-quake" component={QuakeMockup as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => ({ props: { ...props, quake: await fetchQuake(abortSignal) } })} />

      {/* Previews del cierre: riesgo severo SPC + bloque de temperatura (máx hoy,
          variación mañana, máx mañana) con los feeds REALES + escaleta. */}
      <Still id="Mockup-spc" component={SpcOutlookMockup as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          const [spc, escaleta] = await Promise.all([fetchSpcOutlook(abortSignal), fetchEscaleta(abortSignal)]);
          return { props: { ...props, spc, escaleta: escForStill(props, escaleta) } };
        }} />
      <Still id="Mockup-tmax-hoy" component={TmaxTodayMockup as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          const escaleta = await fetchEscaleta(abortSignal);
          const [t, raster] = await Promise.all([fetchTmaxCities(abortSignal, escaleta), fetchTmaxTodayRaster(abortSignal)]);
          return { props: { ...props, cities: t.today, pop: t.popToday, raster, escaleta: escForStill(props, escaleta) } };
        }} />
      <Still id="Mockup-tvar-manana" component={TvarMockup as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          const escaleta = await fetchEscaleta(abortSignal);
          const [t, raster] = await Promise.all([fetchTmaxCities(abortSignal, escaleta), fetchTdeltaRaster(abortSignal)]);
          return { props: { ...props, today: t.today, tomorrow: t.tomorrow, raster, escaleta: escForStill(props, escaleta) } };
        }} />
      <Still id="Mockup-tmax-manana" component={TmaxTomorrowMockup as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          const escaleta = await fetchEscaleta(abortSignal);
          const [t, raster] = await Promise.all([fetchTmaxCities(abortSignal, escaleta), fetchTmaxTomorrowRaster(abortSignal)]);
          return { props: { ...props, cities: t.tomorrow, pop: t.popTomorrow, raster, escaleta: escForStill(props, escaleta) } };
        }} />

      {/* Previews Prev-<escena> del Segment real (ver PREV_SCENES arriba). Si la
          escena no está hoy en el plan (apagada o sin datos) se renderiza igual
          con una duración por defecto: se ve cómo saldría si entrara. */}
      {PREV_SCENES.map((sc) => (
        <Composition
          key={sc}
          id={`Prev-${sc.replace(/_/g, "-")}`}
          component={PrevScene as any}
          fps={FPS}
          durationInFrames={1}
          width={1920}
          height={1080}
          defaultProps={{ ...DEFAULTS, offsetFrames: 0 }}
          calculateMetadata={async ({ props, abortSignal }: any) => {
            const meta = await computeMeta(props, abortSignal, { width: 1920, height: 1080 });
            const mp = meta.props as any;
            const item = mp.plan.find((it: ScenePlanItem) => it.type === sc) ??
              ({ id: `prev-${sc}`, type: sc, seconds: 8 } as any);
            const frames = Math.max(1, Math.round(item.seconds * FPS));
            return {
              props: { ...mp, plan: [item], offsetFrames: Math.min(frames - 1, Math.round(frames * 0.6)) },
            };
          }}
        />
      ))}

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
