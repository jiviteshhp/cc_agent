// Stateful, anti-aliased conversion: browser device rate -> mono 16 kHz.
// The FIR delay is 31 input samples. Fractional output position survives every
// AudioWorklet block, preventing sample loss/drift at both 44.1 and 48 kHz.
export class PCMResampler {
  constructor(inputRate, outputRate = 16000) {
    if (inputRate < outputRate) throw new Error("Input sample rate is too low");
    this.ratio = inputRate / outputRate;
    this.index = 0; this.nextOutput = 0; this.previous = 0; this.head = 0;
    this.ring = new Float64Array(63); this.coefficients = new Float64Array(63);
    const cutoff = .45 * outputRate / inputRate;
    let total = 0;
    for (let n = 0; n < 63; n++) {
      const x = n - 31;
      const sinc = x === 0 ? 2 * cutoff : Math.sin(2 * Math.PI * cutoff * x) / (Math.PI * x);
      this.coefficients[n] = sinc * (.54 - .46 * Math.cos(2 * Math.PI * n / 62));
      total += this.coefficients[n];
    }
    for (let n = 0; n < 63; n++) this.coefficients[n] /= total;
  }
  process(input) {
    const output = [];
    for (const sample of input) {
      this.ring[this.head] = sample;
      let filtered = 0;
      for (let tap = 0; tap < 63; tap++) filtered += this.coefficients[tap] * this.ring[(this.head - tap + 63) % 63];
      this.head = (this.head + 1) % 63;
      if (this.nextOutput <= this.index + 1e-7) {
        const fraction = Math.max(0, Math.min(1, this.nextOutput - (this.index - 1)));
        output.push(this.previous + fraction * (filtered - this.previous));
        this.nextOutput += this.ratio;
      }
      this.previous = filtered;
      this.index++;
    }
    return output;
  }
}
export function writePCM(view, index, value) {
  const clipped = Math.max(-1, Math.min(1, value));
  view.setInt16(index * 2, Math.round(clipped * (clipped < 0 ? 32768 : 32767)), true);
}
