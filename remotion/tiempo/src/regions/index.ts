// Registro de regiones: una composición de segmento por región en el mismo bundle.
import type { RegionConfig } from "./types";
import { REGION as CONUS } from "./conus";
import { REGION as NE } from "./ne";
import { REGION as FL } from "./fl";
import { REGION as SP } from "./sp";
import { REGION as MW } from "./mw";
import { REGION as NP } from "./np";
import { REGION as NW } from "./nw";
import { REGION as SW } from "./sw";
import { REGION as SE } from "./se";

export const REGIONS: Record<string, RegionConfig> = {
  conus: CONUS, ne: NE, fl: FL, sp: SP, mw: MW, np: NP, nw: NW, sw: SW, se: SE,
};
export const REGION_IDS: string[] = Object.keys(REGIONS);
export type { RegionConfig } from "./types";
