import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { SatMap } from "../components/SatMap";
import { DataCard } from "../components/DataCard";
import { TopicBar } from "../components/Overlay";
import { LocatorMap } from "../components/LocatorMap";
import { satViewFromBand } from "../lib/cdn";
import { catKeyFor, tropCat, stormName } from "../lib/tropical";
import { SatData, Storm } from "../types";

const { fontFamily } = loadFont();

// Icono del sistema (HTML) para colocar como marcador en el centro de la tormenta.
function systemBadgeHTML(catKey: string): string {
  const cat = tropCat(catKey);
  const txt = catKey === "H1" ? "#1a2530" : "#fff";
  return `<div style="width:84px;height:84px;border-radius:50%;background:${cat.color};border:4px solid #fff;color:${txt};display:flex;align-items:center;justify-content:center;font-weight:800;font-size:48px;line-height:1;box-shadow:0 8px 28px rgba(0,0,0,0.55);font-family:Outfit,system-ui,sans-serif;pointer-events:none">${cat.letter}</div>`;
}

// Escena 1 por tormenta: satélite INFRARROJO con zoom + tarjeta + icono del
// sistema sobre el centro de la tormenta (su lon/lat del boletín).
export const StormSatellite: React.FC<{ storm: Storm; sat?: SatData }> = ({
  storm,
  sat,
}) => {
  const frame = useCurrentFrame();

  const lon = storm.lon ?? -90;
  const lat = storm.lat ?? 15;
  const view = satViewFromBand(sat, "geocolor");
  const ck = catKeyFor(storm);

  const titleOpacity = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const hasPos = storm.lon != null && storm.lat != null;
  const fitPoints = hasPos ? [{ lon: storm.lon as number, lat: storm.lat as number }] : [];

  return (
    <AbsoluteFill style={{ fontFamily, background: "#000" }}>
      <SatMap
        sat={view}
        center={[lon, lat]}
        zoom={5}
        opacity={0.95}
        fitPoints={fitPoints}
        marginDeg={4.5}
        minSpan={14}
        centerBadge={
          hasPos
            ? { lon: lon, lat: lat, html: systemBadgeHTML(ck) }
            : undefined
        }
      />

      <AbsoluteFill
        style={{
          background:
            "linear-gradient(180deg, rgba(0,0,0,0.5) 0%, rgba(0,0,0,0) 22%, rgba(0,0,0,0) 60%, rgba(0,0,0,0.5) 100%)",
          pointerEvents: "none",
        }}
      />

      <TopicBar
        topic="SATÉLITE"
        sub={`GEOCOLOR · ${stormName(storm).toUpperCase()}`}
        catKey={ck}
        opacity={titleOpacity}
      />

      <DataCard storm={storm} />

      {hasPos ? (
        <LocatorMap
          lon={lon}
          lat={lat}
          color={tropCat(ck).color}
          textColor={ck === "H1" ? "#1a2530" : "#fff"}
          opacity={titleOpacity}
        />
      ) : null}
    </AbsoluteFill>
  );
};
