import type {RadarFrame} from '../types';

const RAINVIEWER_API = 'https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/radar/weather-maps.json';

/**
 * Devuelve los últimos N frames de NUESTRO radar mundial (radar_mundial_pipeline, 16/10/2026;
 * mismo formato que RainViewer, que ya no se usa: su API pública es solo para uso personal).
 * Por defecto 6 (= 1.5 horas, ya que cada frame son 15 min).
 */
export async function fetchRadarFrames(count = 6): Promise<RadarFrame[]> {
    try {
        const r = await fetch(RAINVIEWER_API);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);

        const data = await r.json();
        const host = data.host || 'https://canalmeteo-public.sfo3.cdn.digitaloceanspaces.com';
        const past = (data.radar?.past || []) as Array<{time: number; path: string}>;

        if (past.length === 0) {
            console.warn('[fetchRadarFrames] No past radar frames available');
            return [];
        }

        // Tomar los últimos N (el último es el más reciente)
        const lastN = past.slice(-count);

        return lastN.map((f) => ({
            time: f.time,
            path: f.path,
            host,
        }));
    } catch (e) {
        console.warn('[fetchRadarFrames] error:', e);
        return [];
    }
}
