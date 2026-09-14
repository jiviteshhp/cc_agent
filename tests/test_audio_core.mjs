import assert from "node:assert/strict";
import { PCMResampler, writePCM } from "../web/audio-core.mjs";
for (const rate of [44100, 48000]) {
  const input = Float32Array.from({length: rate * 3}, (_, i) => Math.sin(2 * Math.PI * 440 * i / rate) * .3);
  const resampler = new PCMResampler(rate);
  const segmented = [];
  for (let i = 0; i < input.length; i += 128) segmented.push(...resampler.process(input.subarray(i, i + 128)));
  const continuous = new PCMResampler(rate).process(input);
  assert.equal(segmented.length, 48000, `${rate}: no samples lost between blocks`);
  assert.deepEqual(segmented, continuous, `${rate}: segmentation cannot change signal`);
  const toneRMS = freq => {
    const audio = Float32Array.from({length: rate}, (_, i) => Math.sin(2 * Math.PI * freq * i / rate));
    const output = new PCMResampler(rate).process(audio).slice(100);
    return Math.sqrt(output.reduce((sum, sample) => sum + sample * sample, 0) / output.length);
  };
  assert.ok(toneRMS(1000) > .65, "Preserve speech-band energy");
  assert.ok(toneRMS(12000) < .01, "Reject out-of-band sound before resampling");
}
const view = new DataView(new ArrayBuffer(6));
[-2, 0, 2].forEach((value, i) => writePCM(view, i, value));
assert.deepEqual([0,1,2].map(i => view.getInt16(i*2, true)), [-32768, 0, 32767]);
console.log("Audio checks passed: 44.1/48 kHz timing, block continuity, anti-alias filter, PCM clipping/endian.");
