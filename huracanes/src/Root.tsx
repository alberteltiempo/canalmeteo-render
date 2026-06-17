import React from "react";
import { Composition } from "remotion";
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
  // Quita invests ya reemplazados por un sistema con nombre (no repetir escenas).
  const data = dedupeInvests(attachPrecip(enriched, precipManifests));
  let plan = buildScenePlan(data);
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
    props: { ...props, data, plan, sat, satWest, irConus, irEast, irWest },
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
    </>
  );
};
