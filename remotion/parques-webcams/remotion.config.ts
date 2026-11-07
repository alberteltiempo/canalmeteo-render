import {Config} from '@remotion/cli/config';

// Render para broadcast TV: 1920x1080 @ 30fps, h264 high quality
Config.setVideoImageFormat('jpeg');
Config.setConcurrency(2);  // sfo3-c tiene 2 vCPU
Config.setCodec('h264');
Config.setPixelFormat('yuv420p');
Config.setCrf(18);  // 18 = visually lossless, 23 = default

// Tiempo límite por frame (Mapbox + RainViewer pueden tardar)
Config.setDelayRenderTimeoutInMilliseconds(45000);

// Permitir Chromium con --no-sandbox (necesario en root en Linux)
Config.setChromiumOpenGlRenderer('angle-egl');
Config.setChromiumDisableWebSecurity(true);
