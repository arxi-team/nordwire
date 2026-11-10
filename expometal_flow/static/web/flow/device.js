// The stand's Raspberry Pi 4 (1 GB) drives the TV: there the screens render lighter (light layers at lower resolution,
// canvas/WebGL at 30 fps, no blur over moving content) with the same effects; the PC keeps full quality.
// ?pi forces the Pi profile on any machine, ?full turns it off. Chromium reports "Linux x86_64" on every Linux (the Pi
// too), so the Pi is found by its memory or its GPU (V3D/VideoCore; Mali on TV boxes; llvmpipe/SwiftShader = no GPU).
const q = new URLSearchParams(location.search);
const gpu = () => { try { const g = document.createElement('canvas').getContext('webgl'), s = g.getParameter(g.getExtension('WEBGL_debug_renderer_info').UNMASKED_RENDERER_WEBGL); g.getExtension('WEBGL_lose_context')?.loseContext(); return s; } catch { return ''; } };
export const PI = !q.has('full') && (q.has('pi') || navigator.deviceMemory <= 1 || /aarch64|armv7l|armv8l|raspbian|raspberry/i.test(navigator.userAgent) || /V3D|VideoCore|Mali|llvmpipe|SwiftShader/i.test(gpu()));
if (PI) document.documentElement.classList.add('-pi');
