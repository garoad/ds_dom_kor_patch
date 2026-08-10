"use strict";
// .nbfc(타일)+.nbfp(팔레트)+.nbfs(스크린맵) 세트를 PNG로 디코딩.
// temp/decode_bg_image.py에서 실제 ROM으로 검증된 포맷을 그대로 포팅
// (analysis/ANALYSIS_NOTES.md "그래픽 리소스 추출/삽입 검증" 항목 참고):
//   .nbfc: LZ10 해제 후 8bpp 8x8 타일 flat array (64바이트/타일)
//   .nbfp: LZ10 해제 후 256 x RGB555(2바이트) = 512바이트 팔레트
//   .nbfs: LZ10 해제 후 u16 스크린맵 엔트리(bits0-9 타일 인덱스, bit10 hflip, bit11 vflip)
const { PNG } = require("pngjs");
const lz10 = require("./lz10");

function loadPalette(buf) {
  const dec = lz10.decompress(buf);
  const n = Math.floor(dec.length / 2);
  const pal = new Array(n);
  for (let i = 0; i < n; i++) {
    const v = dec.readUInt16LE(i * 2);
    pal[i] = [
      Math.round(((v & 0x1f) * 255) / 31),
      Math.round((((v >> 5) & 0x1f) * 255) / 31),
      Math.round((((v >> 10) & 0x1f) * 255) / 31),
    ];
  }
  return pal;
}

function loadTiles(buf) {
  const dec = lz10.decompress(buf);
  const n = Math.floor(dec.length / 64);
  const tiles = new Array(n);
  for (let i = 0; i < n; i++) tiles[i] = dec.subarray(i * 64, i * 64 + 64);
  return tiles;
}

function loadScreen(buf) {
  const dec = lz10.decompress(buf);
  const n = Math.floor(dec.length / 2);
  const entries = new Array(n);
  for (let i = 0; i < n; i++) entries[i] = dec.readUInt16LE(i * 2);
  return entries;
}

function decodeTilemapPng(nbfcBuf, nbfpBuf, nbfsBuf) {
  const tiles = loadTiles(nbfcBuf);
  const palette = loadPalette(nbfpBuf);
  const entries = loadScreen(nbfsBuf);

  const n = entries.length;
  let mapW, mapH;
  if (n === 289) {
    // Chr 폴더의 캐릭터 스탠딩 스몰/미디엄 스탠딩 포트레이트 (17x17 타일 = 136x136 px)
    mapW = 17;
    mapH = 17;
  } else if (n === 768) {
    mapW = 32;
    mapH = 24;
  } else if (n === 960) {
    mapW = 32;
    mapH = 30;
  } else if (n === 1024) {
    mapW = 32;
    mapH = 32;
  } else {
    // NDS 화면 타일맵의 기본 가로 폭(타일 수)은 32 (32 * 8 = 256px)
    mapW = 32;
    mapH = Math.ceil(n / mapW);
  }

  const png = new PNG({ width: mapW * 8, height: mapH * 8 });
  for (let i = 0; i < n; i++) {
    const e = entries[i];
    const tileIdx = e & 0x3ff;
    const hflip = (e >> 10) & 1;
    const vflip = (e >> 11) & 1;
    const tx = i % mapW;
    const ty = Math.floor(i / mapW);
    const tile = tileIdx < tiles.length ? tiles[tileIdx] : Buffer.alloc(64);
    for (let py = 0; py < 8; py++) {
      for (let px = 0; px < 8; px++) {
        const sx = hflip ? 7 - px : px;
        const sy = vflip ? 7 - py : py;
        const colorIdx = tile[sy * 8 + sx];
        const rgb = palette[colorIdx] || [0, 0, 0];
        const x = tx * 8 + px;
        const y = ty * 8 + py;
        const idx = (png.width * y + x) << 2;
        png.data[idx] = rgb[0];
        png.data[idx + 1] = rgb[1];
        png.data[idx + 2] = rgb[2];
        png.data[idx + 3] = 255;
      }
    }
  }
  return PNG.sync.write(png);
}

module.exports = { decodeTilemapPng };
