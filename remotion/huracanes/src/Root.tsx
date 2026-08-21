import React from "react";
import { AbsoluteFill, Composition, Sequence } from "remotion";
import { TropicoSegment } from "./TropicoSegment";
import {
  fetchActiveStorms,
  enrichStorms,
  fetchSatelliteData,
  fetchGoesIr,
  fetchPrecipManifests,
  attachPrecip,
  dedupeInvests,
  buildScenePlan,
  fetchEscaleta,
  planDurationInFrames,
} from "./lib/cdn";
import type { ActiveStorms, ScenePlanItem, SatData, SatView } from "./types";

const FPS = 30;

type MetaProps = {
  data: ActiveStorms;
  plan: ScenePlanItem[];
  sat?: SatData;
  satWest?: SatData;
  irConus?: SatView;
  irEast?: SatView;
  irWest?: SatView;
};

// Carga de datos + plan, compartida por la versión horizontal y la vertical.
// dropOpen: en vertical (Instagram) se omite la portada y se arranca con el GeoColor.
async function computeMeta(
  props: MetaProps,
  abortSignal: AbortSignal,
  opts: { width: number; height: number; dropOpen?: boolean }
) {
  const [rawData, sat, satWest, irConus, irEast, irWest, precipManifests] = await Promise.all([
    fetchActiveStorms(abortSignal),
    // GOES-East (Atlántico) y GOES-West (Pacífico Oriental). disco-este solo llega
    // hasta -130°O: los sistemas del Pacífico al oeste de ahí salían como banda
    // negra. disco-oeste (GOES-18) cubre el Pacífico hasta -179°O.
    fetchSatelliteData("disco-este", ["geocolor", "ir"], 36, abortSignal),
    fetchSatelliteData("disco-oeste", ["geocolor", "ir"], 36, abortSignal),
    // IR windy (colorido + transparente) para el zoom del invest. "conus" es de
    // alta resolución pero solo EEUU/Golfo/Caribe; "este"/"oeste" son full-disk
    // (más blandos al zoom) y cubren todo el Atlántico / Pacífico Oriental. El
    // frontend elige conus si el invest cae dentro, si no la vista de su cuenca.
    fetchGoesIr("conus", abortSignal),
    fetchGoesIr("este", abortSignal),
    fetchGoesIr("oeste", abortSignal),
    fetchPrecipManifests(abortSignal),
  ]);
  const enriched = await enrichStorms(rawData, abortSignal);
  // Escaleta editable (intranet): null → defaults de código.
  const escaleta = await fetchEscaleta(abortSignal);
  // Quita invests ya reemplazados por un sistema con nombre (no repetir escenas).
  const data = dedupeInvests(attachPrecip(enriched, precipManifests));
  let plan = buildScenePlan(data, escaleta);
  if (opts.dropOpen) plan = plan.filter((p) => p.type !== "open");
  const durationInFrames = planDurationInFrames(plan, FPS);
  const satN = sat.bands?.geocolor?.length ?? sat.bands?.ir?.length ?? 0;
  const rainModels = data.storms
    .map((s) => s._precip?.model)
    .filter(Boolean)
    .join(", ");
  // eslint-disable-next-line no-console
  console.log(
    `[huracanes] ${opts.width}x${opts.height} · ${data.storms.length} tormenta(s) · ` +
      `${plan.length} escenas · ${satN} frames satélite · lluvia: ${rainModels || "—"} · ` +
      `${(durationInFrames / FPS).toFixed(1)}s`
  );
  return {
    durationInFrames,
    fps: FPS,
    width: opts.width,
    height: opts.height,
    props: { ...props, data, plan, sat, satWest, irConus, irEast, irWest, escaleta },
  };
}

const DEFAULTS = {
  data: { storms: [] } as ActiveStorms,
  plan: [] as ScenePlanItem[],
  sat: undefined as SatData | undefined,
  satWest: undefined as SatData | undefined,
  irConus: undefined as SatView | undefined,
  irEast: undefined as SatView | undefined,
  irWest: undefined as SatView | undefined,
};

// Previews del editor de escaletas: cada escena del catálogo se renderiza con
// el TropicoSegment REAL (mismos datos NHC/satélite y escaleta que la antena)
// con el plan reducido a esa escena. El Sequence con `from` negativo desplaza
// el tiempo a mitad de escena para verla ya desarrollada (Freeze NO vale:
// recorta el frame a la duración de la composición). Son <Composition> de
// 1 frame y NO <Still>: el Still fuerza fps=1 y las ventanas del plan
// (segundos × fps) se quedarían cortas.
// A diferencia de los segmentos "tiempo", aquí muchas escenas dependen de que
// HAYA tormentas/invests: si la escena no está en el plan de hoy no se puede
// enseñar nada real y sale la tarjeta "no entra hoy".
const PREV_SCENES = [
  "open", "satGlobal", "countIntro", "basinIntro", "stormSat", "stormTrack",
  "investStatus", "stormRain", "basinStatus", "nameList", "outro",
];

const PrevScene: React.FC<any> = ({ offsetFrames = 0, missing, ...rest }) =>
  missing ? (
    <AbsoluteFill style={{ background: "#0a1420", alignItems: "center", justifyContent: "center" }}>
      <div
        style={{
          color: "rgba(255,255,255,0.9)",
          fontSize: 46,
          fontWeight: 800,
          textAlign: "center",
          fontFamily: "Arial, sans-serif",
          lineHeight: 1.6,
        }}
      >
        Esta escena no entra en el vídeo de hoy
        <div style={{ fontSize: 28, fontWeight: 600, color: "rgba(255,255,255,0.6)" }}>
          (sin tormentas o invests que la activen ahora mismo)
        </div>
      </div>
    </AbsoluteFill>
  ) : (
    <Sequence from={-offsetFrames} durationInFrames={offsetFrames + 1}>
      <TropicoSegment {...rest} />
    </Sequence>
  );

export const Root: React.FC = () => {
  return (
    <>
      {/* Horizontal — broadcast / web (16:9) */}
      <Composition
        id="TropicoSegment"
        component={TropicoSegment as any}
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

      {/* Vertical — Instagram Reels/Stories (9:16), sin portada, arranca con GeoColor */}
      <Composition
        id="TropicoVertical"
        component={TropicoSegment as any}
        durationInFrames={FPS * 30}
        fps={FPS}
        width={1080}
        height={1920}
        defaultProps={DEFAULTS}
        calculateMetadata={async ({
          props,
          abortSignal,
        }: {
          props: MetaProps;
          abortSignal: AbortSignal;
        }) =>
          computeMeta(props, abortSignal, {
            width: 1080,
            height: 1920,
            dropOpen: true,
          })
        }
      />

      {/* Previews Prev-<escena> para el editor de escaletas (ver PREV_SCENES). */}
      {PREV_SCENES.map((sc) => (
        <Composition
          key={sc}
          id={`Prev-${sc}`}
          component={PrevScene as any}
          fps={FPS}
          durationInFrames={1}
          width={1920}
          height={1080}
          defaultProps={{ ...DEFAULTS, offsetFrames: 0 }}
          calculateMetadata={async ({ props, abortSignal }: any) => {
            const meta = await computeMeta(props, abortSignal, { width: 1920, height: 1080 });
            const mp = meta.props as any;
            const item = mp.plan.find((it: ScenePlanItem) => it.type === sc);
            if (!item) return { props: { ...mp, missing: true } };
            const frames = Math.max(1, Math.round(item.seconds * FPS));
            return {
              props: { ...mp, plan: [item], offsetFrames: Math.min(frames - 1, Math.round(frames * 0.6)) },
            };
          }}
        />
      ))}
    </>
  );
};
