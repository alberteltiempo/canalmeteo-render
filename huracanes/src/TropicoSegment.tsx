import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  interpolate,
  Sequence,
  Series,
  staticFile,
  useVideoConfig,
} from "remotion";
import { TropicoProps, ActiveStorms, Storm, SatData, ScenePlanItem } from "./types";
import { LOGO_URL } from "./lib/theme";
import { Open } from "./components/Open";
import { Outro } from "./components/Outro";
import { SatelliteGlobal } from "./scenes/SatelliteGlobal";
import { StormSatellite } from "./scenes/StormSatellite";
import { StormTrack } from "./scenes/StormTrack";
import { StormRain } from "./scenes/StormRain";
import { NameList } from "./scenes/NameList";
import { BasinIntro } from "./scenes/BasinIntro";
import { CountIntro } from "./scenes/CountIntro";
import { BasinStatus } from "./scenes/BasinStatus";
import { stormBasin } from "./lib/names2026";

// ── Música de fondo ──────────────────────────────────────────
// Pon tu pista en  public/musica/tropico.mp3  y cambia HAS_MUSIC a true.
const HAS_MUSIC = true;
const MUSIC_FILE = "musica/tropico.mp3";

const BackgroundMusic: React.FC = () => {
  const { durationInFrames, fps } = useVideoConfig();
  return (
    <Audio
      src={staticFile(MUSIC_FILE)}
      volume={(f: number) =>
        interpolate(
          f,
          [0, fps, durationInFrames - fps * 1.5, durationInFrames],
          [0, 0.55, 0.55, 0],
          { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
        )
      }
    />
  );
};

// Corte seco entre escenas (sin cross-dissolve): nunca monta dos mapas WebGL a
// la vez → render mucho más rápido en CPU. El cono y la lluvia comparten encuadre
// exacto, así que el cambio entre ellos es casi imperceptible.
export const TropicoSegment: React.FC<TropicoProps> = ({ data, plan, sat }) => {
  const { fps } = useVideoConfig();
  const storms = data?.storms || [];
  // Frames de los slides de intro (portada + conteo): la marca de agua no se pinta
  // sobre ellos (ya son carteles de marca, sería repetitivo).
  let introFrames = 0;
  for (const it of plan || []) {
    if (it.type === "open" || it.type === "countIntro") {
      introFrames += Math.max(1, Math.round(it.seconds * fps));
    } else {
      break;
    }
  }
  const openFrames = introFrames;

  return (
    <AbsoluteFill style={{ backgroundColor: "#0d1a26" }}>
      {HAS_MUSIC ? <BackgroundMusic /> : null}
      <Series>
        {(plan || []).map((s) => {
          const dur = Math.max(1, Math.round(s.seconds * fps));
          const storm = s.stormIndex != null ? storms[s.stormIndex] : undefined;
          return (
            <Series.Sequence key={s.id} durationInFrames={dur}>
              {renderScene(s, storm, data, sat)}
            </Series.Sequence>
          );
        })}
      </Series>
      {/* Logo permanente (marca de agua) — NO en la portada (ya lleva el logo
          central, sería repetitivo). Arranca cuando termina la apertura. */}
      <Sequence from={openFrames} layout="none">
        <Img
          src={LOGO_URL}
          style={{
            position: "absolute",
            bottom: 40,
            right: 48,
            width: 132,
            opacity: 0.92,
            filter: "drop-shadow(0 2px 8px rgba(0,0,0,0.6))",
            pointerEvents: "none",
          }}
        />
      </Sequence>
    </AbsoluteFill>
  );
};

function renderScene(
  s: ScenePlanItem,
  storm: Storm | undefined,
  data: ActiveStorms,
  sat?: SatData
): React.ReactNode {
  switch (s.type) {
    case "open":
      return <Open />;
    case "countIntro":
      return <CountIntro data={data} />;
    case "satGlobal":
      return <SatelliteGlobal sat={sat} storms={data?.storms} />;
    case "basinIntro":
      return <BasinIntro basin={s.basin ?? "atlantic"} />;
    case "stormSat":
      return storm ? <StormSatellite storm={storm} sat={sat} /> : null;
    case "stormTrack":
      return storm ? <StormTrack storm={storm} /> : null;
    case "stormRain":
      return storm ? <StormRain storm={storm} /> : null;
    case "nameList": {
      const basin = s.basin ?? "atlantic";
      const activeNames = (data?.storms || [])
        .filter((st) => stormBasin(st) === basin)
        .map((st) => st.name)
        .filter((nm): nm is string => !!nm);
      return <NameList basin={basin} activeNames={activeNames} />;
    }
    case "basinStatus":
      return (
        <BasinStatus basin={s.basin ?? "atlantic"} sat={sat} mode={s.mode ?? "none"} data={data} />
      );
    case "outro":
      return <Outro />;
    default:
      return null;
  }
}
