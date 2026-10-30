import { PCMResampler, writePCM } from "./audio-core.mjs";
import { Rnnoise } from "./rnnoise-core.mjs";
class CaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.destroyed = false;
    this.resampler = new PCMResampler(sampleRate);
    this.frame = new ArrayBuffer(640); this.view = new DataView(this.frame); this.used = 0;
    this.noiseFrame = new Float32Array(480); this.noiseUsed = 0;
    this.port.onmessage = ({data}) => { if (data === "destroy") this.destroy(); };
    this.init(options.processorOptions?.wasmBinary);
  }
  async init(wasmBinary) {
    try {
      if (sampleRate !== 48000 || !wasmBinary) throw new Error("Unsupported capture format");
      const module = await Rnnoise.loadBinary(wasmBinary);
      if (this.destroyed) return;
      if (module.frameSize !== 480) throw new Error("Unexpected denoiser frame size");
      this.denoiser = module.createDenoiseState();
      this.port.postMessage({type: "ready"});
    } catch {
      this.port.postMessage({type: "error"}); this.destroy();
    }
  }
  destroy() {
    this.destroyed = true;
    this.denoiser?.destroy(); this.denoiser = null;
  }
  process(inputs, outputs) {
    // Keep a zero-valued output to drive processing without microphone loopback.
    for (const channel of outputs[0] || []) channel.fill(0);
    if (this.destroyed) return false;
    const input = inputs[0]?.[0];
    if (!input || !this.denoiser) return true;
    try {
      for (const sample of input) {
        // RNNoise consumes 10 ms at 48 kHz, with float samples on the PCM16 scale.
        // Carry partial frames across render blocks; never discard or gate speech.
        this.noiseFrame[this.noiseUsed++] = sample * 32768;
        if (this.noiseUsed !== 480) continue;
        this.denoiser.processFrame(this.noiseFrame);
        let energy = 0;
        for (let i = 0; i < 480; i++) {
          this.noiseFrame[i] /= 32768;
          energy += this.noiseFrame[i] ** 2;
        }
        for (const value of this.resampler.process(this.noiseFrame)) {
          writePCM(this.view, this.used++, value);
          if (this.used === 320) {
            this.port.postMessage({pcm: this.frame, level: Math.sqrt(energy / 480)}, [this.frame]);
            this.frame = new ArrayBuffer(640); this.view = new DataView(this.frame); this.used = 0;
          }
        }
        this.noiseUsed = 0;
      }
    } catch {
      this.port.postMessage({type: "error"}); this.destroy(); return false;
    }
    return true;
  }
}
registerProcessor("pcm-capture", CaptureProcessor);
