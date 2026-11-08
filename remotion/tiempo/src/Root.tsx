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
  TminTodayMockup,
  TmaxTomorrowMockup,
  TvarMockup,
} from "./scenes/ForecastMockups";
import { OutlookLayerMockup } from "./scenes/OutlookLayer";
import { SmokeMockup } from "./scenes/SmokeScene";
import { FrontsScene, ReportsScene, DroughtScene } from "./scenes/SurfaceScenes";
import { LightningScene, WatchesScene, HailScene } from "./scenes/SevereScenes";
import { QuakeIntroMockup, QuakeMockup } from "./scenes/QuakeScene";
import { MOCKUPS, RELIEF_MOCKUPS, SYSTEM_MOCKUPS } from "./lib/mockups";
import {
  fetchQuake,
  fetchEscaleta,
  escForStill,
  fetchGlm,
  fetchSpcWatches,
  fetchMrmsMesh,
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
  fetchOutlookRaster,
  fetchOutlookMeta,
  fetchSmoke,
  fetchTmaxTomorrowRaster,
  fetchTdeltaRaster,
  computeMode,
  buildScenePlan,
  planDurationInFrames,
  resolveMusic,
  applyRegionRuntime,
  REGION,
} from "./lib/cdn";
import { REGIONS, REGION_IDS } from "./regions";
import type { RegionConfig } from "./regions";
import type { MusicResolved } from "./lib/cdn";
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
  music?: MusicResolved | null;
  // Si se fija ("normal"/"alert"), ignora el cálculo automático del Modo Rojo.
  forceMode?: ThemeMode | null;
};

async function computeMeta(
  props: MetaProps,
  abortSignal: AbortSignal,
  opts: { width: number; height: number },
  regionId: string
) {
  applyRegionRuntime(regionId);
  // Escaleta editable (intranet): null → defaults de código. Va ANTES del
  // Promise.all porque sus umbrales parametrizan el granizo y los rayos.
  const escaleta = await fetchEscaleta(abortSignal);
  // Música: pista de la biblioteca si existe en el bundle; si no, la de código.
  const music = await resolveMusic(escaleta, abortSignal);
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
    glm,
    spcWatches,
    mesh,
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
    // Tiempo severo en vivo (escenas condicionales): rayos GLM, vigilancias/MCD
    // del SPC y granizo MRMS. null → la escena no entra al plan.
    // Tiempo severo en vivo: solo CONUS (las regionales no tienen esas escenas).
    REGION.features.conus ? fetchGlm(abortSignal) : Promise.resolve(null),
    REGION.features.conus ? fetchSpcWatches(abortSignal) : Promise.resolve(null),
    REGION.features.conus ? fetchMrmsMesh(abortSignal, escaleta?.thresholds) : Promise.resolve(null),
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
    // Rayos: con muy pocos destellos la escena queda vacía → umbral mínimo.
    lightning: glm != null && glm.flashes >= (escaleta?.thresholds?.glmMinFlashes ?? 25),
    watches: spcWatches != null,
    hail: mesh != null,
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
      music,
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
      glm,
      spcWatches,
      mesh,
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
  music: null as MusicResolved | null,
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

// Envoltorio por región: fija la región activa ANTES de que el componente lea
// catálogos/encuadre (mismo patrón que applyEscaletaRuntime). Cacheado para que
// Remotion vea siempre el mismo componente.
const regionWrapped = new Map<string, React.FC<any>>();
function withRegion(C: React.FC<any>, cfg: RegionConfig, key: string): React.FC<any> {
  const k = `${cfg.id}:${key}`;
  let w = regionWrapped.get(k);
  if (!w) {
    const Wrapped: React.FC<any> = (p) => {
      applyRegionRuntime(cfg.id);
      return <C {...p} />;
    };
    Wrapped.displayName = `Region(${k})`;
    regionWrapped.set(k, Wrapped);
    w = Wrapped;
  }
  return w;
}

// Composiciones de UNA región: el segmento (id = cfg.compositionId, el de siempre:
// ConusSegment, SpSegment…) y sus stills/previews con el prefijo "<región>-"
// (sp-Prev-condiciones, conus-Mockup-tmax-hoy…).
const RegionRoot: React.FC<{ cfg: RegionConfig }> = ({ cfg }) => {
  const cid = (id: string) => `${cfg.id}-${id}`;
  return (
    <>
      <Composition
        id={cfg.compositionId}
        component={withRegion(ConusSegment, cfg, "ConusSegment") as any}
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
        }) => computeMeta(props, abortSignal, { width: 1920, height: 1080 }, cfg.id)}
      />

      {/* Mockup "Condiciones ahora" (capa de temperatura faux + cajas de ciudad).
          Still para pulir el look antes de cablear la capa NBM real. */}
      <Still
        id={cid("Mockup-condiciones")}
        component={withRegion(CondicionesMockup, cfg, "CondicionesMockup") as any}
        width={1920}
        height={1080}
        defaultProps={{}}
      />

      {/* Preview REAL de "Condiciones ahora" para el editor de escaletas: datos
          vivos (NBM + weather.json) + escaleta aplicada (cámara, escala y
          posiciones fijadas), congelada en el frame 0 (animate=false). */}
      <Still
        id={cid("Prev-condiciones")}
        component={withRegion(CondicionesNow, cfg, "CondicionesNow") as any}
        width={1920}
        height={1080}
        defaultProps={{ animate: false }}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          applyRegionRuntime(cfg.id);
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
      <Still id={cid("Mockup-aeropuertos")} component={withRegion(AirportsMockup, cfg, "AirportsMockup") as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          applyRegionRuntime(cfg.id);
          const escaleta = await fetchEscaleta(abortSignal);
          const airports = await fetchAirports(abortSignal, escaleta);
          return { props: { ...props, airports, escaleta: escForStill(props, escaleta) } };
        }} />
      <Still id={cid("Mockup-uv")} component={withRegion(UvMockup, cfg, "UvMockup") as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          applyRegionRuntime(cfg.id);
          const escaleta = await fetchEscaleta(abortSignal);
          const uv = await fetchUv(abortSignal, escaleta);
          return { props: { ...props, uv, escaleta: escForStill(props, escaleta) } };
        }} />
      <Still id={cid("Mockup-aqi")} component={withRegion(AqiMockup, cfg, "AqiMockup") as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          applyRegionRuntime(cfg.id);
          const escaleta = await fetchEscaleta(abortSignal);
          const aqi = await fetchAqi(abortSignal, escaleta);
          return { props: { ...props, aqi, escaleta: escForStill(props, escaleta) } };
        }} />

      {/* Mockups de mapa nacional con DATOS REALES (Still + calculateMetadata):
          mapa de superficie (frentes/presión), reportes de tormenta y sequía.
          animate=false para que las capas se vean en el frame 0. */}
      <Still
        id={cid("Mockup-frentes")}
        component={withRegion(FrontsScene, cfg, "FrontsScene") as any}
        width={1920}
        height={1080}
        defaultProps={{ animate: false }}
        calculateMetadata={async ({ props, abortSignal }: any) => (applyRegionRuntime(cfg.id), {
          props: { ...props, fronts: await fetchFronts(abortSignal), animate: false },
        })}
      />
      <Still
        id={cid("Mockup-reportes")}
        component={withRegion(ReportsScene, cfg, "ReportsScene") as any}
        width={1920}
        height={1080}
        defaultProps={{ animate: false }}
        calculateMetadata={async ({ props, abortSignal }: any) => (applyRegionRuntime(cfg.id), {
          props: { ...props, reports: await fetchStormReports(abortSignal), animate: false },
        })}
      />

      {/* Tiempo severo en vivo (rayos GLM, vigilancias SPC, granizo MESH) con
          DATOS REALES: sin actividad el still sale casi vacío — es lo esperado;
          en el plan las escenas solo entran cuando hay actividad. */}
      {cfg.features.conus && (<Still
        id={cid("Mockup-rayos")}
        component={withRegion(LightningScene, cfg, "LightningScene") as any}
        width={1920}
        height={1080}
        defaultProps={{ animate: false }}
        calculateMetadata={async ({ props, abortSignal }: any) => (applyRegionRuntime(cfg.id), {
          props: { ...props, glm: await fetchGlm(abortSignal), animate: false },
        })}
      />)}
      {cfg.features.conus && (<Still
        id={cid("Mockup-vigilancias")}
        component={withRegion(WatchesScene, cfg, "WatchesScene") as any}
        width={1920}
        height={1080}
        defaultProps={{ animate: false }}
        calculateMetadata={async ({ props, abortSignal }: any) => (applyRegionRuntime(cfg.id), {
          props: { ...props, spcWatches: await fetchSpcWatches(abortSignal), animate: false },
        })}
      />)}
      {cfg.features.conus && (<Still
        id={cid("Mockup-granizo")}
        component={withRegion(HailScene, cfg, "HailScene") as any}
        width={1920}
        height={1080}
        defaultProps={{ animate: false }}
        calculateMetadata={async ({ props, abortSignal }: any) => (applyRegionRuntime(cfg.id), {
          props: { ...props, mesh: await fetchMrmsMesh(abortSignal), animate: false },
        })}
      />)}
      <Still
        id={cid("Mockup-sequia")}
        component={withRegion(DroughtScene, cfg, "DroughtScene") as any}
        width={1920}
        height={1080}
        defaultProps={{ animate: false }}
        calculateMetadata={async ({ props, abortSignal }: any) => (applyRegionRuntime(cfg.id), {
          props: { ...props, drought: await fetchDrought(abortSignal), animate: false },
        })}
      />

      {/* Última hora · Terremoto: cartel previo + mapa del epicentro. Con quake
          real (feed USGS) si lo hay; sin él, la muestra de diseño. */}
      <Still id={cid("Mockup-quake-intro")} component={withRegion(QuakeIntroMockup, cfg, "QuakeIntroMockup") as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => (applyRegionRuntime(cfg.id), { props: { ...props, quake: await fetchQuake(abortSignal) } })} />
      <Still id={cid("Mockup-quake")} component={withRegion(QuakeMockup, cfg, "QuakeMockup") as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => (applyRegionRuntime(cfg.id), { props: { ...props, quake: await fetchQuake(abortSignal) } })} />

      {/* Previews del cierre: riesgo severo SPC + bloque de temperatura (máx hoy,
          variación mañana, máx mañana) con los feeds REALES + escaleta. */}
      <Still id={cid("Mockup-spc")} component={withRegion(SpcOutlookMockup, cfg, "SpcOutlookMockup") as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          applyRegionRuntime(cfg.id);
          const [spc, escaleta] = await Promise.all([fetchSpcOutlook(abortSignal), fetchEscaleta(abortSignal)]);
          return { props: { ...props, spc, escaleta: escForStill(props, escaleta) } };
        }} />
      <Still id={cid("Mockup-tmax-hoy")} component={withRegion(TmaxTodayMockup, cfg, "TmaxTodayMockup") as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          applyRegionRuntime(cfg.id);
          const escaleta = await fetchEscaleta(abortSignal);
          const [t, raster] = await Promise.all([fetchTmaxCities(abortSignal, escaleta), fetchTmaxTodayRaster(abortSignal)]);
          return { props: { ...props, cities: t.today, pop: t.popToday, raster, escaleta: escForStill(props, escaleta) } };
        }} />
      {/* ── Sustitutos de los mapas de lynx-hub (lynx/conus), 11/09/2026 ──
          Mínimas de hoy + capas de outlooks (SPC día 1 y CPC 6-10 días) + humo
          HMS. Se renderizan como Still 1280×720 y se suben con el nombre de
          siempre (CONUS_*.jpg) desde scripts/conus_lynx.py en nimbus-03. */}
      {cfg.features.conus && (<Still id={cid("Mockup-tmin-hoy")} component={withRegion(TminTodayMockup, cfg, "TminTodayMockup") as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          applyRegionRuntime(cfg.id);
          const escaleta = await fetchEscaleta(abortSignal);
          const t = await fetchTmaxCities(abortSignal, escaleta);
          return { props: { ...props, cities: t.tminToday, escaleta: escForStill(props, escaleta) } };
        }} />)}
      {cfg.features.conus && (<Still id={cid("Mockup-spc-viento")} component={withRegion(OutlookLayerMockup, cfg, "OutlookLayerMockup") as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          applyRegionRuntime(cfg.id);
          const [raster, meta] = await Promise.all([
            fetchOutlookRaster("spc_wind_d1", abortSignal),
            fetchOutlookMeta("spc_wind_d1", abortSignal),
          ]);
          return { props: { ...props, raster, meta, topic: "RIESGO DE VIENTO", sub: "HOY" } };
        }} />)}
      {cfg.features.conus && (<Still id={cid("Mockup-spc-tornado")} component={withRegion(OutlookLayerMockup, cfg, "OutlookLayerMockup") as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          applyRegionRuntime(cfg.id);
          const [raster, meta] = await Promise.all([
            fetchOutlookRaster("spc_torn_d1", abortSignal),
            fetchOutlookMeta("spc_torn_d1", abortSignal),
          ]);
          return { props: { ...props, raster, meta, topic: "RIESGO DE TORNADOS", sub: "HOY" } };
        }} />)}
      {cfg.features.conus && (<Still id={cid("Mockup-spc-granizo")} component={withRegion(OutlookLayerMockup, cfg, "OutlookLayerMockup") as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          applyRegionRuntime(cfg.id);
          const [raster, meta] = await Promise.all([
            fetchOutlookRaster("spc_hail_d1", abortSignal),
            fetchOutlookMeta("spc_hail_d1", abortSignal),
          ]);
          return { props: { ...props, raster, meta, topic: "RIESGO DE GRANIZO", sub: "HOY" } };
        }} />)}
      {cfg.features.conus && (<Still id={cid("Mockup-cpc-temp-610")} component={withRegion(OutlookLayerMockup, cfg, "OutlookLayerMockup") as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          applyRegionRuntime(cfg.id);
          const [raster, meta] = await Promise.all([
            fetchOutlookRaster("cpc_temp_610", abortSignal),
            fetchOutlookMeta("cpc_temp_610", abortSignal),
          ]);
          return { props: { ...props, raster, meta, topic: "PRONÓSTICO DE TEMPERATURA", sub: "6-10 DÍAS" } };
        }} />)}
      {cfg.features.conus && (<Still id={cid("Mockup-cpc-prcp-610")} component={withRegion(OutlookLayerMockup, cfg, "OutlookLayerMockup") as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          applyRegionRuntime(cfg.id);
          const [raster, meta] = await Promise.all([
            fetchOutlookRaster("cpc_prcp_610", abortSignal),
            fetchOutlookMeta("cpc_prcp_610", abortSignal),
          ]);
          return { props: { ...props, raster, meta, topic: "PRONÓSTICO DE PRECIPITACIÓN", sub: "6-10 DÍAS" } };
        }} />)}
      {cfg.features.conus && (<Still id={cid("Mockup-humo")} component={withRegion(SmokeMockup, cfg, "SmokeMockup") as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => (applyRegionRuntime(cfg.id), {
          props: { ...props, smoke: await fetchSmoke(abortSignal) },
        })} />)}
      <Still id={cid("Mockup-tvar-manana")} component={withRegion(TvarMockup, cfg, "TvarMockup") as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          applyRegionRuntime(cfg.id);
          const escaleta = await fetchEscaleta(abortSignal);
          const [t, raster] = await Promise.all([fetchTmaxCities(abortSignal, escaleta), fetchTdeltaRaster(abortSignal)]);
          return { props: { ...props, today: t.today, tomorrow: t.tomorrow, raster, escaleta: escForStill(props, escaleta) } };
        }} />
      <Still id={cid("Mockup-tmax-manana")} component={withRegion(TmaxTomorrowMockup, cfg, "TmaxTomorrowMockup") as any} width={1920} height={1080} defaultProps={{}}
        calculateMetadata={async ({ props, abortSignal }: any) => {
          applyRegionRuntime(cfg.id);
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
          id={cid(`Prev-${sc.replace(/_/g, "-")}`)}
          component={withRegion(PrevScene, cfg, "PrevScene") as any}
          fps={FPS}
          durationInFrames={1}
          width={1920}
          height={1080}
          defaultProps={{ ...DEFAULTS, offsetFrames: 0 }}
          calculateMetadata={async ({ props, abortSignal }: any) => {
          applyRegionRuntime(cfg.id);
            const meta = await computeMeta(props, abortSignal, { width: 1920, height: 1080 }, cfg.id);
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
          id={cid(`Mockup-${m.id}`)}
          component={withRegion(MapMockup, cfg, "MapMockup") as any}
          width={1920}
          height={1080}
          defaultProps={{ variant: m.id }}
        />
      ))}
    </>
  );
};

export const Root: React.FC = () => (
  <>
    {REGION_IDS.map((id) => (
      <RegionRoot key={id} cfg={REGIONS[id]} />
    ))}
  </>
);
