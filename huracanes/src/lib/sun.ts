// Cálculo solar mínimo (NOAA, sin dependencias) para decidir día/noche
// en el centro de la tormenta y elegir capa de satélite:
//   día   -> GeoColor
//   noche -> Infrarrojo realzado
export function solarElevation(date: Date, lat: number, lon: number): number {
  const rad = Math.PI / 180;
  const jd = date.getTime() / 86400000 + 2440587.5;
  const n = jd - 2451545.0;
  const L = (280.46 + 0.9856474 * n) % 360;
  const g = ((357.528 + 0.9856003 * n) % 360) * rad;
  const lambda =
    (L + 1.915 * Math.sin(g) + 0.02 * Math.sin(2 * g)) * rad;
  const epsilon = 23.439 * rad;
  const decl = Math.asin(Math.sin(epsilon) * Math.sin(lambda));
  const gmst = (18.697374558 + 24.06570982441908 * n) % 24;
  const lst = (gmst + lon / 15) % 24;
  const ra = Math.atan2(
    Math.cos(epsilon) * Math.sin(lambda),
    Math.cos(lambda)
  );
  const ha = (lst * 15 * rad) - ra;
  const latR = lat * rad;
  const elev = Math.asin(
    Math.sin(latR) * Math.sin(decl) +
      Math.cos(latR) * Math.cos(decl) * Math.cos(ha)
  );
  return elev / rad; // grados sobre el horizonte
}

export function isDaytime(date: Date, lat: number, lon: number): boolean {
  // umbral suave: por encima de -6° (crepúsculo civil) usamos GeoColor
  return solarElevation(date, lat, lon) > -6;
}
