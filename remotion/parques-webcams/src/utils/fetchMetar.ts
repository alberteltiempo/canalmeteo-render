// Lee METAR del feed surface_obs.geojson en CDN.
// El pipeline metar_pipeline.py de sfo3-a actualiza este archivo cada 10 min.
//
// Formato confirmado (KBWG sample):
//   { id, name, obsTime, obsAge,
//     tempF, dewpF, feelsF, rh, wdir, wspdMph, wgstMph, visMi,
//     skyCover, skyEs, wxString, wxEs, ... }

const METAR_URL = 'https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/metar/surface_obs.geojson';

let metarCache: any = null;
let metarCacheTime = 0;
const METAR_CACHE_MS = 60 * 1000; // 60s

interface MetarFields {
    temp_f?: number;
    feels_f?: number;
    conditions?: string;
    conditions_en?: string;   // derivado de skyCover/wxString (el feed solo trae ES)
    wind?: string;
    wind_en?: string;         // rosa inglesa: SW/WSW/NW en vez de SO/OSO/NO
    humidity?: number;
    dewpoint_f?: number;
    visibility_mi?: number;
}

/**
 * Carga el METAR de una estación específica desde el GeoJSON del CDN.
 */
export async function fetchMetarForStation(stationId: string): Promise<MetarFields> {
    try {
        const now = Date.now();
        if (!metarCache || now - metarCacheTime > METAR_CACHE_MS) {
            const r = await fetch(METAR_URL);
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            metarCache = await r.json();
            metarCacheTime = now;
            console.log(`[fetchMetar] loaded ${metarCache?.features?.length || 0} stations from CDN`);
        }

        const features = metarCache?.features || [];
        const feature = features.find((f: any) => f.properties?.id === stationId);

        if (!feature) {
            console.warn(`[fetchMetar] station ${stationId} not found in feed`);
            return {};
        }

        const out = parseCanalMeteoMetar(feature.properties);
        console.log(`[fetchMetar] ${stationId}: ${out.temp_f}°F · ${out.conditions} · ${out.wind} · RH ${out.humidity}%`);
        return out;
    } catch (e) {
        console.warn(`[fetchMetar] error for ${stationId}:`, e);
        return {};
    }
}

/**
 * Parser para el formato Canal Meteo metar_pipeline (camelCase + Spanish).
 */
function parseCanalMeteoMetar(p: any): MetarFields {
    const out: MetarFields = {};

    // Temperatura (ya en °F)
    if (typeof p.tempF === 'number') {
        out.temp_f = Math.round(p.tempF);
    }

    // Sensación (ya en °F)
    if (typeof p.feelsF === 'number') {
        out.feels_f = Math.round(p.feelsF);
    } else if (out.temp_f !== undefined) {
        out.feels_f = out.temp_f;
    }

    // Punto de rocío (ya en °F)
    if (typeof p.dewpF === 'number') {
        out.dewpoint_f = Math.round(p.dewpF);
    }

    // Humedad relativa (entero 0-100)
    if (typeof p.rh === 'number') {
        out.humidity = Math.round(p.rh);
    }

    // Visibilidad (ya en millas)
    if (typeof p.visMi === 'number') {
        out.visibility_mi = Math.round(p.visMi);
    }

    // Condiciones - prefiere wxEs (lluvia/nieve traducido) sobre skyEs (sky cover)
    if (p.wxEs && p.wxEs.toString().trim()) {
        out.conditions = p.wxEs.toString().trim();
    } else if (p.skyEs && p.skyEs.toString().trim()) {
        out.conditions = p.skyEs.toString().trim();
    } else {
        out.conditions = '—';
    }

    // Ingles: el feed NO trae condiciones en ingles (wxEs/skyEs son espanol),
    // asi que se derivan de los codigos crudos skyCover/wxString.
    out.conditions_en = conditionsEn(p);

    // Viento: combinar wspdMph + wdir (rosa espanola e inglesa)
    out.wind = parseWind(p);
    out.wind_en = parseWind(p, true);

    return out;
}

const SKY_EN: Record<string, string> = {
    CLR: "Clear",
    SKC: "Clear",
    CAVOK: "Clear",
    FEW: "Few clouds",
    SCT: "Partly cloudy",
    BKN: "Mostly cloudy",
    OVC: "Overcast",
    OVX: "Overcast",
};

function conditionsEn(p: any): string {
    const wx = (p.wxString || "").toString().trim();
    if (wx) return wx;
    const sky = (p.skyCover || "").toString().trim().toUpperCase();
    return SKY_EN[sky] || "—";
}

function parseWind(p: any, en = false): string {
    const mph = p.wspdMph;
    const dir = p.wdir;

    if (mph == null || (typeof mph !== 'number')) {
        return '— mph';
    }

    const mphRounded = Math.round(mph);

    if (mphRounded === 0) {
        return 'Calma';
    }

    const dirStr = (dir != null && typeof dir === 'number')
        ? degToCompass(dir)
        : '';

    return `${mphRounded} mph ${dirStr}`.trim();
}

function degToCompass(deg: number): string {
    if (isNaN(deg)) return '';
    const dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                  'S', 'SSO', 'SO', 'OSO', 'O', 'ONO', 'NO', 'NNO'];
    return dirs[Math.round(deg / 22.5) % 16];
}
