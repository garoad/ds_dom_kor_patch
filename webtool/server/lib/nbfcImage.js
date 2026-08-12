"use strict";
// .nbfc(타일)+.nbfp(팔레트)+.nbfs(스크린맵) 세트를 PNG로 디코딩/인코딩.
// temp/decode_bg_image.py에서 실제 ROM으로 검증된 포맷을 그대로 포팅
// (analysis/ANALYSIS_NOTES.md "그래픽 리소스 추출/삽입 검증" 항목 참고):
//   .nbfc: LZ10 해제 후 8bpp 8x8 타일 flat array (64바이트/타일)
//   .nbfp: LZ10 해제 후 256 x RGB555(2바이트) = 512바이트 팔레트
//   .nbfs: LZ10 해제 후 u16 스크린맵 엔트리(bits0-9 타일 인덱스, bit10 hflip, bit11 vflip)
//
// encodeTilemapPng()(리팩)는 팔레트를 그대로 재사용하고(최근접 색상 매칭) 스크린맵을
// 단순 순차 인덱스로 생성한다 - 2026-08-12, encodeTilemapPng() 주석 참고.
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

// 스크린맵 엔트리 수(n) -> 타일맵 가로/세로 타일 수. decode/encode 양쪽에서 동일하게
// 써야 왕복이 맞는다.
function tilemapDims(n) {
  if (n === 289) {
    // Chr 폴더의 캐릭터 스탠딩 스몰/미디엄 스탠딩 포트레이트 (17x17 타일 = 136x136 px)
    return { mapW: 17, mapH: 17 };
  } else if (n === 768) {
    return { mapW: 32, mapH: 24 };
  } else if (n === 960) {
    return { mapW: 32, mapH: 30 };
  } else if (n === 1024) {
    return { mapW: 32, mapH: 32 };
  }
  // NDS 화면 타일맵의 기본 가로 폭(타일 수)은 32 (32 * 8 = 256px)
  return { mapW: 32, mapH: Math.ceil(n / 32) };
}

function decodeTilemapPng(nbfcBuf, nbfpBuf, nbfsBuf) {
  const tiles = loadTiles(nbfcBuf);
  const palette = loadPalette(nbfpBuf);
  const entries = loadScreen(nbfsBuf);

  const n = entries.length;
  const { mapW, mapH } = tilemapDims(n);

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

function nearestPaletteIndex(r, g, b, palette) {
  let best = 0;
  let bestDist = Infinity;
  for (let i = 0; i < palette.length; i++) {
    const p = palette[i];
    const dr = r - p[0];
    const dg = g - p[1];
    const db = b - p[2];
    const dist = dr * dr + dg * dg + db * db;
    if (dist < bestDist) {
      bestDist = dist;
      best = i;
      if (dist === 0) break;
    }
  }
  return best;
}

// PNG를 다시 타일(.nbfc/.nbfcn)+스크린맵(.nbfs) 압축 바이너리로 인코딩한다. 팔레트는
// 그대로 재사용(재생성하지 않음) - 업로드 PNG는 원본이 쓰던 팔레트 색상 범위 안에서만
// 표현 가능하고, 각 픽셀은 RGB 유클리드 거리로 가장 가까운 기존 팔레트 인덱스에 매핑된다.
// 스크린맵은 단순 순차 인덱스(hflip/vflip 없음)로 생성 - 원본이 쓰던 타일 재사용/플립
// 최적화는 하지 않는다(정확성 우선, 압축 전 크기가 다소 커져도 NitroPacker pack이 가변
// 크기 파일을 지원하므로 문제 없음).
function encodeTilemapPng(pngBuf, nbfpBuf, origEntryCount) {
  if (origEntryCount > 1024) {
    throw new Error(
      `타일 개수(${origEntryCount})가 1024개를 초과해 인코딩할 수 없습니다 (스크린맵 타일 ` +
        "인덱스 필드는 10비트)"
    );
  }
  const palette = loadPalette(nbfpBuf);
  const { mapW, mapH } = tilemapDims(origEntryCount);
  const expectedW = mapW * 8;
  const expectedH = mapH * 8;

  const png = PNG.sync.read(pngBuf);
  if (png.width !== expectedW || png.height !== expectedH) {
    throw new Error(
      `이미지 크기가 원본과 다릅니다 (원본 ${expectedW}x${expectedH}, 업로드 ${png.width}x${png.height}) - ` +
        "리팩은 원본과 정확히 같은 픽셀 크기만 지원합니다"
    );
  }

  const n = origEntryCount;
  const tiles = Buffer.alloc(n * 64);
  const screen = Buffer.alloc(n * 2);
  for (let i = 0; i < n; i++) {
    const tx = i % mapW;
    const ty = Math.floor(i / mapW);
    const tileOff = i * 64;
    for (let py = 0; py < 8; py++) {
      for (let px = 0; px < 8; px++) {
        const x = tx * 8 + px;
        const y = ty * 8 + py;
        const idx = (png.width * y + x) << 2;
        const colorIdx = nearestPaletteIndex(
          png.data[idx],
          png.data[idx + 1],
          png.data[idx + 2],
          palette
        );
        tiles[tileOff + py * 8 + px] = colorIdx;
      }
    }
    screen.writeUInt16LE(i, i * 2);
  }

  return { nbfc: lz10.compress(tiles), nbfs: lz10.compress(screen) };
}

module.exports = { decodeTilemapPng, encodeTilemapPng, loadScreen };
