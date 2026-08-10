"use strict";

// Port of analysis/lz10.py - Nitro LZSS (LZ10) decompress/compress.
// decompress(compress(data)) must reproduce `data` exactly (verified in
// analysis by mes_codec_roundtrip_test.py against the real NDS BIOS format).

function decompress(data) {
  if (data.length === 0 || data[0] !== 0x10) return data;
  const size = data[1] | (data[2] << 8) | (data[3] << 16);
  const out = Buffer.alloc(size);
  let outLen = 0;
  let pos = 4;
  while (outLen < size) {
    const flags = data[pos];
    pos += 1;
    for (let bit = 0; bit < 8; bit++) {
      if (outLen >= size) break;
      if (flags & (0x80 >> bit)) {
        const b1 = data[pos];
        const b2 = data[pos + 1];
        pos += 2;
        const length = (b1 >> 4) + 3;
        const disp = (((b1 & 0xf) << 8) | b2) + 1;
        for (let i = 0; i < length; i++) {
          out[outLen] = out[outLen - disp];
          outLen++;
        }
      } else {
        out[outLen] = data[pos];
        pos += 1;
        outLen++;
      }
    }
  }
  return out;
}

function compress(data, minMatch = 3, maxMatch = 18, maxDisp = 4096) {
  const n = data.length;
  const out = [];
  out.push(0x10);
  out.push(n & 0xff, (n >> 8) & 0xff, (n >> 16) & 0xff);

  let pos = 0;
  while (pos < n) {
    let flagByte = 0;
    const chunk = [];
    for (let bit = 0; bit < 8; bit++) {
      if (pos >= n) {
        chunk.push(0);
        continue;
      }
      let bestLen = 0;
      let bestDisp = 0;
      const lo = Math.max(0, pos - maxDisp);
      let k = pos - 1;
      while (k >= lo) {
        if (data[k] === data[pos]) {
          let L = 0;
          const limit = Math.min(maxMatch, n - pos);
          while (L < limit && data[k + L] === data[pos + L]) L++;
          if (L > bestLen) {
            bestLen = L;
            bestDisp = pos - k;
            if (bestLen >= maxMatch) break;
          }
        }
        k--;
      }
      if (bestLen >= minMatch) {
        flagByte |= 0x80 >> bit;
        const b1 = ((bestLen - 3) << 4) | (((bestDisp - 1) >> 8) & 0xf);
        const b2 = (bestDisp - 1) & 0xff;
        chunk.push(b1, b2);
        pos += bestLen;
      } else {
        chunk.push(data[pos]);
        pos += 1;
      }
    }
    out.push(flagByte, ...chunk);
  }

  while (out.length % 4 !== 0) out.push(0);
  return Buffer.from(out);
}

module.exports = { decompress, compress };
