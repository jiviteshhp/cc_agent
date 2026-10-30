# Hands-free microphone noise filtering

The browser requests acoustic echo cancellation and noise suppression, disables
automatic gain, and applies an 85 Hz high-pass. A local RNNoise model then consumes
480-sample mono frames at 48 kHz, before the existing resampler creates 20 ms,
16 kHz PCM16 packets for Sarvam. Partial frames carry across rendering callbacks.
There is no second VAD, amplitude gate, or minimum-word filter. The phone transport
and Sarvam browser profile are unchanged.

RNNoise reduces non-speech noise; it does not identify the intended speaker or
replace echo cancellation. Other people, TV, and speaker echo may still become
words. Filters may affect soft speech. The user selected automatic hands-free
listening, including during assistant playback.

The context must support 48 kHz. Model fetch and initialization have a 15-second
budget after microphone permission. The WebSocket starts only after worklet
readiness. Loading/processing failures show an error and release capture; there
is no silent fallback to unfiltered audio. Reset cancels setup and closes tracks,
worklet, context and socket. Text mode does not load the filter. Mute explicitly
sends silence even while internal filter buffers drain. Assets are same-origin
and covered by the existing proxy authentication, with no external CDN request
from a caller's browser. New code requires reopening an existing phone tab.

## Vendored files and reproducibility

Package: [@sapphi-red/web-noise-suppressor 0.4.1](https://github.com/sapphi-red/web-noise-suppressor),
whose bundled loader identifies [@shiguredo/rnnoise-wasm 2022.2.0](https://github.com/shiguredo/rnnoise-wasm).
The model is [RNNoise](https://github.com/xiph/rnnoise). Licenses for the wrapper,
Shiguredo, RNNoise and Babel helpers are bundled in `web/rnnoise-LICENSE.txt`.

Download paths used (no install scripts or package build executed):

```
https://cdn.jsdelivr.net/npm/@sapphi-red/web-noise-suppressor@0.4.1/dist/rnnoise/workletProcessor.js
https://cdn.jsdelivr.net/npm/@sapphi-red/web-noise-suppressor@0.4.1/dist/rnnoise.wasm
```

Upstream worklet SHA256:
`1e06facbb3d7459b89769aa4247cd4b71263e6662e4da0c54763f3bf06f5893b`.
The loader file is derived by splitting at the single literal `;const u=e=>`,
keeping the prefix (loader/classes), and appending `;\nexport { s as Rnnoise };\n`.
Prepend `// Vendored RNNoise loader; see rnnoise-LICENSE.txt and docs/NOISE_FILTER.md.\n`.
This removes the upstream worklet/frame adapter; our readable capture processor
owns framing, readiness, errors and disposal. No model/loader algorithm changes.

| Local file | SHA256 |
| --- | --- |
| `web/rnnoise-core.mjs` | `ae21435d692db6275dae671b281ddceb6b684bdaf647737379d5ef5e1f513972` |
| `web/rnnoise.wasm` | `8b60a2ab88fdae2d1a9f940249d0eb072f28ba8e796f7304347b4e07839c8853` |

The non-SIMD model is used for compatibility; no shared memory or isolation
headers are needed. The loader and model total about 215 KB uncompressed.

## Verification and limits

`tests/browser_demo_smoke.py` checks real Chrome capture, playback, 640-byte
packets, mute, repeated starts and cleanup. It injects missing/corrupt WASM and a
processor error to verify visible failure without an open/deaf call.

`uv run --with playwright python tests/browser_noise_probe.py http://localhost:18001`
uses locally generated espeak-ng Hindi speech plus seeded broadband noise.
It neither reads call recordings nor calls a speech provider. Initial noise RMS
ratio was 0.81, pre-speech settled ratio 0.72, and post-speech ratio 0.0066.
Speech correlation was 0.994 at a 10 ms model delay, with speech RMS ratio 0.999.
The initial target of halving noise RMS was not met. The regression checks retain
separate initial/post-speech measurements and speech-preservation checks.

These results only establish the behavior on this synthetic fixture. No physical
phone, real quiet Hindi answers, overlapping voices, room echo, end-to-end STT
accuracy, or mobile CPU/battery budget has been measured. Test those on a freshly
opened page; process health or a completed PDF is not evidence of audio quality.
