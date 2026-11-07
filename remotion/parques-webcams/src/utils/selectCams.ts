// selectCams.ts — Canal Meteo Parques Webcams
// ════════════════════════════════════════════════════════════════════
// Port de get_cams_for_group_smart() de Python a TypeScript.
// Lee el manifest del CDN y selecciona 4 cámaras operativas de un grupo.
// ════════════════════════════════════════════════════════════════════

const CDN_BASE = 'https://canalmeteo-public.sfo3.digitaloceanspaces.com';
const MANIFEST_URL = `${CDN_BASE}/data/webcams/manifest.json`;

export interface CamStub {
    code: string;
    park_name_es: string;
    park_name_en: string;
    state: string;
    state_abbr: string;
    view_es: string;
    view_en: string;
    lat: number;
    lon: number;
    elevation_ft: number;
    tz: string;
    tz_abbr: string;
    group: string;
    metar: {
        id: string;
        name: string;
        distance_mi: number;
    };
}

// ════════════════════════════════════════════════════════════════════
// CATÁLOGO COMPLETO — 19 cámaras (16 activas + 3 reserva)
// ════════════════════════════════════════════════════════════════════

const ALL_CAMS: CamStub[] = [
    // ─── GRUPO 1: OESTE — Desiertos y Oeste ─────────────────────────
    {code: 'jotr', park_name_es: 'Parque Nacional Joshua Tree', park_name_en: 'Joshua Tree National Park',
     state: 'CALIFORNIA', state_abbr: 'CA',
     view_es: 'Vista del desierto Mojave hacia las Little San Bernardino',
     view_en: 'Mojave Desert view toward the Little San Bernardino Mountains',
     lat: 34.0996, lon: -116.1858, elevation_ft: 4052, tz: 'America/Los_Angeles', tz_abbr: 'PT',
     group: 'oeste', metar: {id: 'KPSP', name: 'Palm Springs Intl', distance_mi: 26.5}},

    {code: 'yose', park_name_es: 'Parque Nacional Yosemite', park_name_en: 'Yosemite National Park',
     state: 'CALIFORNIA', state_abbr: 'CA',
     view_es: 'Half Dome desde Turtleback Dome',
     view_en: 'Half Dome from Turtleback Dome',
     lat: 37.7456, lon: -119.5936, elevation_ft: 6001, tz: 'America/Los_Angeles', tz_abbr: 'PT',
     group: 'oeste', metar: {id: 'KFAT', name: 'Fresno (Yosemite Intl)', distance_mi: 67.1}},

    {code: 'seki', park_name_es: 'Parque Nacional Sequoia', park_name_en: 'Sequoia National Park',
     state: 'CALIFORNIA', state_abbr: 'CA',
     view_es: 'Lower Kaweah desde Ash Mountain',
     view_en: 'Lower Kaweah from Ash Mountain',
     lat: 36.4864, lon: -118.8253, elevation_ft: 1726, tz: 'America/Los_Angeles', tz_abbr: 'PT',
     group: 'oeste', metar: {id: 'KFAT', name: 'Fresno (Yosemite Intl)', distance_mi: 53.6}},

    {code: 'brca', park_name_es: 'Parque Nacional Bryce Canyon', park_name_en: 'Bryce Canyon National Park',
     state: 'UTAH', state_abbr: 'UT',
     view_es: 'Anfiteatro de hoodoos en Bryce Canyon',
     view_en: 'Hoodoo amphitheater at Bryce Canyon',
     lat: 37.6406, lon: -112.169, elevation_ft: 8000, tz: 'America/Denver', tz_abbr: 'MT',
     group: 'oeste', metar: {id: 'KCDC', name: 'Cedar City Municipal', distance_mi: 51.0}},

    // ─── GRUPO 2: MONTAÑAS — Montañas y Bosques ─────────────────────
    {code: 'grte', park_name_es: 'Parque Nacional Grand Teton', park_name_en: 'Grand Teton National Park',
     state: 'WYOMING', state_abbr: 'WY',
     view_es: 'Cordillera Teton desde Jackson Lake',
     view_en: 'Teton Range from Jackson Lake',
     lat: 43.7904, lon: -110.6818, elevation_ft: 6791, tz: 'America/Denver', tz_abbr: 'MT',
     group: 'montanas', metar: {id: 'KJAC', name: 'Jackson Hole', distance_mi: 13.0}},

    {code: 'mora', park_name_es: 'Parque Nacional Mount Rainier', park_name_en: 'Mount Rainier National Park',
     state: 'WASHINGTON', state_abbr: 'WA',
     view_es: 'Mount Rainier desde Tahoma Vista',
     view_en: 'Mount Rainier from Tahoma Vista',
     lat: 46.85, lon: -121.76, elevation_ft: 5400, tz: 'America/Los_Angeles', tz_abbr: 'PT',
     group: 'montanas', metar: {id: 'KSEA', name: 'Seattle-Tacoma Intl', distance_mi: 48.7}},

    {code: 'olym', park_name_es: 'Parque Nacional Olympic', park_name_en: 'Olympic National Park',
     state: 'WASHINGTON', state_abbr: 'WA',
     view_es: 'Hurricane Ridge sobre la cordillera olímpica',
     view_en: 'Hurricane Ridge above the Olympic Mountains',
     lat: 47.97, lon: -123.499, elevation_ft: 5242, tz: 'America/Los_Angeles', tz_abbr: 'PT',
     group: 'montanas', metar: {id: 'KSEA', name: 'Seattle-Tacoma Intl', distance_mi: 66.0}},

    {code: 'noca', park_name_es: 'Parque Nacional North Cascades', park_name_en: 'North Cascades National Park',
     state: 'WASHINGTON', state_abbr: 'WA',
     view_es: 'Vista hacia el Mount Baker',
     view_en: 'View toward Mount Baker',
     lat: 48.78, lon: -121.2, elevation_ft: 1657, tz: 'America/Los_Angeles', tz_abbr: 'PT',
     group: 'montanas', metar: {id: 'KBLI', name: 'Bellingham International', distance_mi: 61.4}},

    // ─── GRUPO 3: APALACHES — Apalaches y Sureste ───────────────────
    {code: 'grsm', park_name_es: 'Great Smoky Mountains', park_name_en: 'Great Smoky Mountains National Park',
     state: 'TENNESSEE', state_abbr: 'TN',
     view_es: 'Vista panorámica de la cordillera Smoky',
     view_en: 'Panoramic view of the Smoky Mountains',
     lat: 35.6532, lon: -83.507, elevation_ft: 4000, tz: 'America/New_York', tz_abbr: 'ET',
     group: 'apalaches', metar: {id: 'KTYS', name: 'Knoxville (McGhee Tyson)', distance_mi: 28.0}},

    {code: 'grcd', park_name_es: 'Great Smoky Mountains — Kuwohi',
     park_name_en: 'Great Smoky Mountains National Park (Kuwohi)',
     state: 'TENNESSEE', state_abbr: 'TN',
     view_es: 'Kuwohi (antes Clingmans Dome)',
     view_en: 'Kuwohi (formerly Clingmans Dome)',
     lat: 35.5628, lon: -83.4985, elevation_ft: 6643, tz: 'America/New_York', tz_abbr: 'ET',
     group: 'apalaches', metar: {id: 'KTYS', name: 'Knoxville (McGhee Tyson)', distance_mi: 36.7}},

    {code: 'maca', park_name_es: 'Parque Nacional Mammoth Cave', park_name_en: 'Mammoth Cave National Park',
     state: 'KENTUCKY', state_abbr: 'KY',
     view_es: 'Bosques de hardwood sobre el sistema cavernario',
     view_en: 'Hardwood forest above the cave system',
     lat: 37.1862, lon: -86.1, elevation_ft: 738, tz: 'America/Chicago', tz_abbr: 'CT',
     group: 'apalaches', metar: {id: 'KBWG', name: 'Bowling Green (Warren County)', distance_mi: 23.5}},

    {code: 'shen', park_name_es: 'Parque Nacional Shenandoah', park_name_en: 'Shenandoah National Park',
     state: 'VIRGINIA', state_abbr: 'VA',
     view_es: 'Big Meadows sobre el valle Shenandoah',
     view_en: 'Big Meadows above the Shenandoah Valley',
     lat: 38.5226, lon: -78.4347, elevation_ft: 3514, tz: 'America/New_York', tz_abbr: 'ET',
     group: 'apalaches', metar: {id: 'KCHO', name: 'Charlottesville-Albemarle', distance_mi: 26.5}},

    // ─── GRUPO 4: ICÓNICOS — Icónicos y Singulares ──────────────────
    {code: 'acad', park_name_es: 'Parque Nacional Acadia', park_name_en: 'Acadia National Park',
     state: 'MAINE', state_abbr: 'ME',
     view_es: 'Cadillac Mountain sobre Bar Harbor',
     view_en: 'Cadillac Mountain above Bar Harbor',
     lat: 44.3386, lon: -68.2733, elevation_ft: 1530, tz: 'America/New_York', tz_abbr: 'ET',
     group: 'iconicos', metar: {id: 'KBGR', name: 'Bangor Intl', distance_mi: 41.6}},

    {code: 'dena', park_name_es: 'Parque Nacional Denali', park_name_en: 'Denali National Park and Preserve',
     state: 'ALASKA', state_abbr: 'AK',
     view_es: 'Denali (Mount McKinley)',
     view_en: 'Denali (Mount McKinley)',
     lat: 63.73, lon: -148.92, elevation_ft: 1735, tz: 'America/Anchorage', tz_abbr: 'AKT',
     group: 'iconicos', metar: {id: 'PATK', name: 'Talkeetna', distance_mi: 60.0}},

    {code: 'havo', park_name_es: 'Parque Nacional Hawaiʻi Volcanoes', park_name_en: 'Hawaiʻi Volcanoes National Park',
     state: 'HAWAIʻI', state_abbr: 'HI',
     view_es: 'Cráter Halemaʻumaʻu en el Kīlauea',
     view_en: 'Halemaʻumaʻu Crater at Kīlauea',
     lat: 19.4194, lon: -155.2885, elevation_ft: 4009, tz: 'Pacific/Honolulu', tz_abbr: 'HST',
     group: 'iconicos', metar: {id: 'PHTO', name: 'Hilo Intl', distance_mi: 30.0}},

    {code: 'wash', park_name_es: 'National Mall', park_name_en: 'National Mall and Memorial Parks',
     state: 'WASHINGTON, D.C.', state_abbr: 'DC',
     view_es: 'Capitolio y Washington Monument desde el Mall',
     view_en: 'The Capitol and Washington Monument from the Mall',
     lat: 38.8895, lon: -77.0353, elevation_ft: 23, tz: 'America/New_York', tz_abbr: 'ET',
     group: 'iconicos', metar: {id: 'KDCA', name: 'Reagan National', distance_mi: 2.6}},

    // ─── RESERVA ────────────────────────────────────────────────────
    {code: 'pore', park_name_es: 'Costa Nacional Point Reyes', park_name_en: 'Point Reyes National Seashore',
     state: 'CALIFORNIA', state_abbr: 'CA',
     view_es: 'Vista costera del Pacífico',
     view_en: 'Pacific coastal view',
     lat: 38.0731, lon: -122.8814, elevation_ft: 423, tz: 'America/Los_Angeles', tz_abbr: 'PT',
     group: 'reserva', metar: {id: 'KSFO', name: 'San Francisco Intl', distance_mi: 42.1}},

    {code: 'bibe', park_name_es: 'Parque Nacional Big Bend', park_name_en: 'Big Bend National Park',
     state: 'TEXAS', state_abbr: 'TX',
     view_es: 'Cordillera Chisos en el desierto chihuahuense',
     view_en: 'Chisos Mountains in the Chihuahuan Desert',
     lat: 29.27, lon: -103.18, elevation_ft: 5400, tz: 'America/Chicago', tz_abbr: 'CT',
     group: 'reserva', metar: {id: 'KMAF', name: 'Midland Intl', distance_mi: 193.8}},

    {code: 'dino', park_name_es: 'Monumento Nacional Dinosaur', park_name_en: 'Dinosaur National Monument',
     state: 'UTAH', state_abbr: 'UT',
     view_es: 'Cañón del Yampa River sobre el desierto rojo',
     view_en: 'Yampa River canyon above the red desert',
     lat: 40.4469, lon: -109.3047, elevation_ft: 4750, tz: 'America/Denver', tz_abbr: 'MT',
     group: 'reserva', metar: {id: 'KRKS', name: 'Rock Springs (SW Wyoming)', distance_mi: 80.4}},

    // ─── Añadidas 12/09/2026 (reserva): salen en lynx/parques pero no
    // estaban en el catálogo; "reserva" = fuera de los grupos del vídeo.
    {code: 'grca', park_name_es: 'Parque Nacional Gran Cañón', park_name_en: 'Grand Canyon National Park',
     state: 'ARIZONA', state_abbr: 'AZ',
     view_es: 'El Gran Cañón desde Yavapai Point',
     view_en: 'The Grand Canyon from Yavapai Point',
     lat: 36.0544, lon: -112.1401, elevation_ft: 7100, tz: 'America/Phoenix', tz_abbr: 'MST',
     group: 'reserva', metar: {id: 'KGCN', name: 'Grand Canyon National Park Airport', distance_mi: 7.6}},

    {code: 'thro', park_name_es: 'Parque Nacional Theodore Roosevelt', park_name_en: 'Theodore Roosevelt National Park',
     state: 'DAKOTA DEL NORTE', state_abbr: 'ND',
     view_es: 'Badlands desde Painted Canyon',
     view_en: 'Badlands from Painted Canyon',
     lat: 46.9790, lon: -103.4397, elevation_ft: 2600, tz: 'America/Denver', tz_abbr: 'MT',
     group: 'reserva', metar: {id: 'K20U', name: 'Beach Municipal', distance_mi: 26.0}},
];

// ════════════════════════════════════════════════════════════════════
// DEFINICIÓN DE LOS 4 GRUPOS
// ════════════════════════════════════════════════════════════════════

export const GROUPS: Record<string, {name_es: string; name_short_es: string; cams: string[]}> = {
    oeste: {
        name_es: 'Desiertos y Oeste',
        name_short_es: 'Oeste',
        cams: ['jotr', 'yose', 'seki', 'brca'],
    },
    montanas: {
        name_es: 'Montañas y Bosques',
        name_short_es: 'Montañas',
        cams: ['grte', 'mora', 'olym', 'noca'],
    },
    apalaches: {
        name_es: 'Apalaches y Sureste',
        name_short_es: 'Apalaches',
        cams: ['grsm', 'grcd', 'maca', 'shen'],
    },
    iconicos: {
        name_es: 'Icónicos y Singulares',
        name_short_es: 'Icónicos',
        cams: ['acad', 'dena', 'havo', 'wash'],
    },
};

const RESERVE_CAMS = ['pore', 'bibe', 'dino'];

// ════════════════════════════════════════════════════════════════════
// FUNCIONES PÚBLICAS
// ════════════════════════════════════════════════════════════════════

export function getCamByCode(code: string): CamStub | undefined {
    return ALL_CAMS.find((c) => c.code === code);
}

/**
 * Selecciona 4 cámaras del grupo especificado.
 * Lee el manifest del CDN para saber cuáles están operativas.
 *
 * @param groupName - 'oeste' | 'montanas' | 'apalaches' | 'iconicos'
 *                    Si se pasa otro valor (ej. una región antigua),
 *                    se asume que es el grupo y se devuelven sus cams.
 */
export async function selectCamsForGroup(groupName: string): Promise<CamStub[]> {
    if (!GROUPS[groupName]) {
        console.warn(
            `[selectCamsForGroup] Grupo "${groupName}" no existe. ` +
            `Válidos: ${Object.keys(GROUPS).join(', ')}. Devolviendo "oeste".`,
        );
        groupName = 'oeste';
    }

    console.log(`[selectCamsForGroup] Seleccionando para grupo: ${groupName}`);

    const primaryCodes = GROUPS[groupName].cams;

    // Descargar manifest
    let operationalCodes = new Set<string>();
    try {
        const r = await fetch(MANIFEST_URL);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const manifest = await r.json();
        for (const cam of manifest.cams || []) {
            if (cam.status === 'ok') {
                operationalCodes.add(cam.code);
            }
        }
    } catch (e) {
        console.warn(
            `[selectCamsForGroup] No pude leer manifest, usando primarias: ${e}`,
        );
        return primaryCodes.map((c) => getCamByCode(c)).filter(Boolean) as CamStub[];
    }

    // Filtrar primarias operativas
    const validCodes: string[] = primaryCodes.filter((c) => operationalCodes.has(c));

    // Completar con reserva
    if (validCodes.length < 4) {
        for (const fallback of RESERVE_CAMS) {
            if (validCodes.length >= 4) break;
            if (operationalCodes.has(fallback) && !validCodes.includes(fallback)) {
                validCodes.push(fallback);
            }
        }
    }

    // Si seguimos faltos, completar con cualquier cámara OK de otros grupos
    if (validCodes.length < 4) {
        const allActive = Object.values(GROUPS).flatMap((g) => g.cams);
        for (const code of allActive) {
            if (validCodes.length >= 4) break;
            if (operationalCodes.has(code) && !validCodes.includes(code)) {
                validCodes.push(code);
            }
        }
    }

    // Garantizar 4 (caso extremo: ninguna OK → repetir primarias)
    if (validCodes.length === 0) {
        return primaryCodes.map((c) => getCamByCode(c)).filter(Boolean) as CamStub[];
    }
    while (validCodes.length < 4) {
        validCodes.push(validCodes[validCodes.length % validCodes.length]);
    }

    const result = validCodes
        .slice(0, 4)
        .map((c) => getCamByCode(c))
        .filter(Boolean) as CamStub[];

    console.log(
        `[selectCamsForGroup] ${groupName} → ${result.map((c) => c.code).join(', ')}`,
    );

    return result;
}

/**
 * @deprecated — usar selectCamsForGroup en su lugar.
 * Solo para compatibilidad con código viejo basado en hora UTC.
 */
export async function selectCamsForCurrentHour(
    regionOverride?: string,
): Promise<CamStub[]> {
    console.warn(
        '[selectCamsForCurrentHour] DEPRECATED. Usa selectCamsForGroup(groupName).',
    );
    const group = regionOverride || 'oeste';
    return selectCamsForGroup(group);
}
