import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
// Mapbox usa WebGL. En Chromium headless (sin GPU) hay que usar el renderer de
// software ANGLE+SwiftShader o falla con "failed to initialize WebGL".
Config.setChromiumOpenGlRenderer("swangle");
// WebGL por software es lento cargando/pintando los frames del mapa; sube el
// límite de delayRender (por defecto 30s) para que no aborte en máquinas sin GPU.
Config.setDelayRenderTimeoutInMilliseconds(120000);
// El render a escala completa (1920x1080) se controla con --scale=1 en render.sh.
