import { PCMResampler, writePCM } from "./audio-core.mjs";
class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.resampler = new PCMResampler(sampleRate);
    this.frame = new ArrayBuffer(640); this.view = new DataView(this.frame); this.used = 0;
  }
  process(inputs, outputs) {
    // Keep a zero-valued output to drive processing without microphone loopback.
    for (const channel of outputs[0] || []) channel.fill(0);
    const input = inputs[0]?.[0];
    if (!input) return true;
    let energy = 0;
    for (const sample of input) energy += sample * sample;
    for (const sample of this.resampler.process(input)) {
      writePCM(this.view, this.used++, sample);
      if (this.used === 320) {
        this.port.postMessage({pcm: this.frame, level: Math.sqrt(energy / input.length)}, [this.frame]);
        this.frame = new ArrayBuffer(640); this.view = new DataView(this.frame); this.used = 0;
      }
    }
    return true;
  }
}
registerProcessor("pcm-capture", CaptureProcessor);
