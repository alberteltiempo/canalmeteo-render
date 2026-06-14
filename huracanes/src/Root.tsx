import React from "react";
import { Composition } from "remotion";
import { TropicoSegment } from "./TropicoSegment";
import {
  fetchActiveStorms,
  enrichStorms,
  fetchSatelliteData,
  fetchPrecipManifests,
  attachPrecip,
  buildScenePlan,
  planDurationInFrames,
} from "./lib/cdn";
import type { ActiveStorms, ScenePlanItem, SatData } from "./types";

const FPS = 30;

type MetaProps = { data: ActiveStorms; plan: ScenePlanItem[]; sat?: SatData };

// Carga de datos + plan, compartida por la versión horizontal y la vertical.
// dropOpen: en vertical (Instagram) se omite la portada y se arranca con el GeoColor.
async function computeMeta(
  props: MetaProps,
  abortSignal: AbortSignal,
  opts: { width: number; height: number; dropOpen?: boolean }
) {
  const [rawData, sat, precipManifests] = await Promise.all([
    fetchActiveStorms(abortSignal),
    fetchSatelliteData("disco-este", ["geocolor"], 36, abortSignal),
    fetchPrecipManifests(abortSignal),
  ]);
  const enriched = await enrichStorms(rawData, abortSignal);
  const data = attachPrecip(enriched, precipManifests);
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
    props: { ...props, data, plan, sat },
  };
}

const DEFAULTS = {
  data: { storms: [] } as ActiveStorms,
  plan: [] as ScenePlanItem[],
  sat: undefined as SatData | undefined,
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
