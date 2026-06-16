import { Basin, Storm } from "../types";

// Listas oficiales WMO/NHC 2026 (verificadas con NOAA/NHC).
export const NAMES_2026: Record<Basin, string[]> = {
  atlantic: [
    "Arthur", "Bertha", "Cristobal", "Dolly", "Edouard", "Fay", "Gonzalo",
    "Hanna", "Isaias", "Josephine", "Kyle", "Leah", "Marco", "Nana", "Omar",
    "Paulette", "Rene", "Sally", "Teddy", "Vicky", "Wilfred",
  ],
  epac: [
    "Amanda", "Boris", "Cristina", "Douglas", "Elida", "Fausto", "Genevieve",
    "Hernan", "Iselle", "Julio", "Karina", "Lowell", "Marie", "Norbert",
    "Odalys", "Polo", "Rachel", "Simon", "Trudy", "Vance", "Winnie", "Xavier",
    "Yolanda", "Zeke",
  ],
};

export const BASIN_LABEL: Record<Basin, string> = {
  atlantic: "ATLÁNTICO",
  epac: "PACÍFICO ORIENTAL",
};

// Cuenca de una tormenta: por prefijo del id NHC (al / ep / cp), con respaldo
// por longitud si el id no lo indica.
export function stormBasin(s: Storm): Basin {
  const id = String(s.id || "").toLowerCase();
  if (/^al/.test(id)) return "atlantic";
  if (/^(ep|cp)/.test(id)) return "epac";
  // Códigos de invest del NHC: "92L" (Atlántico), "18E"/"03C" (Pacífico).
  if (/\d{2}l$/.test(id)) return "atlantic";
  if (/\d{2}[ec]$/.test(id)) return "epac";
  const lon = typeof s.lon === "number" ? s.lon : 0;
  return lon <= -92 ? "epac" : "atlantic";
}

// Estado de cada nombre de la lista para una cuenca, dado los nombres activos.
// Los ciclones se nombran en orden alfabético, así que todo lo anterior al
// último nombre activo ya se ha usado esta temporada.
export type NameStatus = "active" | "past" | "remaining";

export function nameStatuses(basin: Basin, activeNames: string[]): NameStatus[] {
  const list = NAMES_2026[basin];
  const norm = (x: string) => x.trim().toLowerCase();
  const activeSet = new Set(activeNames.map(norm));
  let usedThrough = -1;
  list.forEach((nm, i) => {
    if (activeSet.has(norm(nm))) usedThrough = Math.max(usedThrough, i);
  });
  return list.map((nm, i) => {
    if (activeSet.has(norm(nm))) return "active";
    if (i <= usedThrough) return "past";
    return "remaining";
  });
}
