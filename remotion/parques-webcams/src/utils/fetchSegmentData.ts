import type {SegmentData, CamData, MetarData, RadarFrame} from '../types';
import {selectCamsForCurrentHour} from './selectCams';
import {fetchMetarForStation} from './fetchMetar';
import {fetchRadarFrames} from './fetchRadarFrames';

const CDN_BASE = 'https://canalmeteo-public.sfo3.digitaloceanspaces.com';

/**
 * Master data fetcher.
 * Llamado por calculateMetadata en Root.tsx ANTES de iniciar el render.
 * Devuelve todo lo que el composition necesita para renderizar.
 *
 * @param regionOverride - opcional, fuerza una región específica para test
 */
export async function fetchSegmentData(regionOverride?: string): Promise<SegmentData> {
    const generatedAt = new Date().toISOString();

    // 1. Seleccionar 4 cámaras según la hora UTC actual (o override)
    const selectedCams = await selectCamsForCurrentHour(regionOverride);
    console.log(`[fetchSegmentData] Selected ${selectedCams.length} cams:`, selectedCams.map((c) => c.code));

    // 2. Para cada cámara: enriquecer con METAR
    const camsWithMetar: CamData[] = await Promise.all(
        selectedCams.map(async (camStub) => {
            const metar = await fetchMetarForStation(camStub.metar.id);
            return {
                code: camStub.code,
                park_name_es: camStub.park_name_es,
                park_name_en: camStub.park_name_en,
                state: camStub.state,
                state_abbr: camStub.state_abbr,
                view_es: camStub.view_es,
                view_en: camStub.view_en,
                lat: camStub.lat,
                lon: camStub.lon,
                elevation_ft: camStub.elevation_ft,
                tz: camStub.tz,
                tz_abbr: camStub.tz_abbr,
                region: camStub.group,   // CamStub expone `group` (el error de tipos venia de aqui)
                image_url: `${CDN_BASE}/data/webcams/${camStub.code}/latest.jpg`,
                metar: {
                    id: camStub.metar.id,
                    name: camStub.metar.name,
                    distance_mi: camStub.metar.distance_mi,
                    ...metar,
                } as MetarData,
            };
        })
    );

    // 3. Fetch últimas 6 frames de RainViewer (para anim del radar)
    const radarFrames: RadarFrame[] = await fetchRadarFrames(6);

    return {
        cams: camsWithMetar,
        radarFrames,
        generatedAt,
    };
}
