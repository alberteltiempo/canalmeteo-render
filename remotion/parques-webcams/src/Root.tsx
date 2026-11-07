import React from 'react';
import {AbsoluteFill, Composition, Sequence, Still} from 'remotion';
import {ParquesComposition, parquesSchema} from './Composition';
import {fetchSegmentData} from './utils/fetchSegmentData';
import {WebcamSlide} from './components/WebcamSlide';
import {SimpleSlide} from './components/SimpleSlide';
import {getCamByCode} from './utils/selectCams';
import {fetchMetarForStation} from './utils/fetchMetar';
import {fetchRadarFrames} from './utils/fetchRadarFrames';
import type {CamData, RadarFrame} from './types';

const CDN_BASE = 'https://canalmeteo-public.sfo3.digitaloceanspaces.com';

// WebcamSlide se desvanece por frame en los DOS extremos:
//   opacity = enterOpacity(0..15) * exitOpacity(dur-12..dur)
// Un <Still> tiene dur=1, asi que la salida ya esta a 0 y el frame sale negro.
// Solucion: Composition con duracion real (12 s, como en el video) y captura
// con --frame=180 (mitad de la diapositiva: ambas rampas valen 1).
const DUR = 360;

const CamaraSimple: React.FC<any> = ({cam, lang}) =>
    cam ? <SimpleSlide cam={cam} lang={lang} /> : <AbsoluteFill style={{background: '#0a1628'}} />;

const CamaraSlide: React.FC<any> = ({cam, radarFrames, lang}) =>
    cam ? (
        <WebcamSlide cam={cam} slideIndex={0} totalSlides={1} radarFrames={radarFrames} lang={lang} />
    ) : (
        <AbsoluteFill style={{background: "#0a1628"}} />
    );

// Total: 3s open + 4×12s slides + 9s outro = 60s @ 30fps
const FPS = 30;
const TOTAL_DURATION_SECONDS = 60;
const TOTAL_FRAMES = TOTAL_DURATION_SECONDS * FPS;

export const Root: React.FC = () => {
    return (
        <>
            <Composition
                id="ParquesWebcams"
                component={ParquesComposition as any}
                durationInFrames={TOTAL_FRAMES}
                fps={FPS}
                width={1920}
                height={1080}
                schema={parquesSchema}
                defaultProps={{
                    cams: [] as any[],
                    radarFrames: [] as any[],
                    generatedAt: new Date().toISOString(),
                    regionOverride: '' as string,
                }}
                calculateMetadata={(async ({props}: any) => {
                    // Si vienen props con regionOverride (vía CLI --props), pasarlo
                    const override = props && props.regionOverride
                        ? String(props.regionOverride).trim()
                        : undefined;
                    const data = await fetchSegmentData(override);
                    return {
                        props: data as any,
                    };
                }) as any}
            />

            {/* ── Captura fija de UNA cámara para lynx/parques (12/09/2026) ──
                La renderiza scripts/parques_lynx.py en nimbus-03, una por parque,
                y la sube con el nombre de siempre (Camera_Parque_*.jpg). */}
            <Composition
                id="Mockup-camara"
                component={CamaraSlide as any}
                durationInFrames={DUR}
                fps={30}
                width={1920}
                height={1080}
                defaultProps={{code: 'yose', lang: 'es'} as any}
                calculateMetadata={(async ({props}: any) => {
                    const code = String(props?.code || 'yose').trim();
                    const stub = getCamByCode(code);
                    if (!stub) {
                        console.warn(`[camara] código desconocido: ${code}`);
                        return {props: {...props, cam: null, radarFrames: []}};
                    }
                    const [metar, radarFrames] = await Promise.all([
                        fetchMetarForStation(stub.metar.id),
                        fetchRadarFrames(6),
                    ]);
                    const lang = String(props?.lang || 'es').trim();
                    const cam: CamData = {
                        code: stub.code,
                        park_name_es: stub.park_name_es,
                        park_name_en: stub.park_name_en,
                        view_en: stub.view_en,
                        state: stub.state,
                        state_abbr: stub.state_abbr,
                        view_es: stub.view_es,
                        lat: stub.lat,
                        lon: stub.lon,
                        elevation_ft: stub.elevation_ft,
                        tz: stub.tz,
                        tz_abbr: stub.tz_abbr,
                        region: stub.group,
                        image_url: `${CDN_BASE}/data/webcams/${stub.code}/latest.jpg`,
                        metar: {
                            id: stub.metar.id,
                            name: stub.metar.name,
                            distance_mi: stub.metar.distance_mi,
                            ...metar,
                        } as any,
                    };
                    return {props: {...props, cam, lang, radarFrames: radarFrames as RadarFrame[]}};
                }) as any}
            />

            {/* Versión simple para la app: foto a pantalla completa, logo,
                nombre del parque y cortesía del NPS (12/09/2026). */}
            <Composition
                id="Mockup-camara-simple"
                component={CamaraSimple as any}
                durationInFrames={DUR}
                fps={30}
                width={1920}
                height={1080}
                defaultProps={{code: 'yose', lang: 'es'} as any}
                calculateMetadata={(async ({props}: any) => {
                    const code = String(props?.code || 'yose').trim();
                    const stub = getCamByCode(code);
                    if (!stub) {
                        console.warn(`[camara] código desconocido: ${code}`);
                        return {props: {...props, cam: null, radarFrames: []}};
                    }
                    const [metar, radarFrames] = await Promise.all([
                        fetchMetarForStation(stub.metar.id),
                        fetchRadarFrames(6),
                    ]);
                    const lang = String(props?.lang || 'es').trim();
                    const cam: CamData = {
                        code: stub.code,
                        park_name_es: stub.park_name_es,
                        park_name_en: stub.park_name_en,
                        view_en: stub.view_en,
                        state: stub.state,
                        state_abbr: stub.state_abbr,
                        view_es: stub.view_es,
                        lat: stub.lat,
                        lon: stub.lon,
                        elevation_ft: stub.elevation_ft,
                        tz: stub.tz,
                        tz_abbr: stub.tz_abbr,
                        region: stub.group,
                        image_url: `${CDN_BASE}/data/webcams/${stub.code}/latest.jpg`,
                        metar: {
                            id: stub.metar.id,
                            name: stub.metar.name,
                            distance_mi: stub.metar.distance_mi,
                            ...metar,
                        } as any,
                    };
                    return {props: {...props, cam, lang, radarFrames: radarFrames as RadarFrame[]}};
                }) as any}
            />
        </>
    );
};
