"use strict";

const express = require("express");
const fs = require("fs");
const path = require("path");

const proj = require("../lib/project");
const nbfcImage = require("../lib/nbfcImage");

const router = express.Router();
const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".bmp", ".gif"]);

/** .nbfc 또는 .nbfcn 은 같은 폴더에 짝이 되는 .nbfp/.nbfpn 및 .nbfs가 있어야 디코딩 가능하다. */
function hasNbfcSiblings(dirNames, baseName, isNn = false) {
  const pExt = isNn ? ".nbfpn" : ".nbfp";
  return dirNames.has(baseName + pExt) && dirNames.has(baseName + ".nbfs");
}

// data/ 아래 배경 그래픽 중 상당수는 .nbfc/.nbfp/.nbfs가 아니라 같은 LZ10+타일/팔레트/
// 스크린맵 포맷을 .bin 확장자 + "<A>_bg_<B>c.bin"(타일)/"<A>_bg_<B>s.bin"(스크린맵)/
// "<A>_p_<B>.bin"(팔레트) 이름 규칙으로 저장한다(예: title02_bg_title02c/s.bin +
// title02_p_title02.bin, athena_bg_namec/s.bin + athena_p_name.bin). 실제 ROM 데이터로
// 바이트 단위 동일 포맷임을 확인함(analysis/ANALYSIS_NOTES.md 참고).
const BIN_TILE_RE = /^(.+)_bg_(.+)c\.bin$/i;

function binImageParts(fname) {
  const m = BIN_TILE_RE.exec(fname);
  if (!m) return null;
  return { a: m[1], b: m[2] };
}

function binSiblingNames(parts) {
  return {
    screen: `${parts.a}_bg_${parts.b}s.bin`,
    palette: `${parts.a}_p_${parts.b}.bin`,
  };
}

function hasBinSiblings(dirNames, parts) {
  const { screen, palette } = binSiblingNames(parts);
  return dirNames.has(screen) && dirNames.has(palette);
}

/** Resolve `rel` under the project's unpack root, rejecting any escape. */
function resolveInUnpack(name, rel) {
  const root = proj.unpackDir(name);
  const resolved = path.resolve(root, "." + path.sep + (rel || ""));
  if (resolved !== root && !resolved.startsWith(root + path.sep)) {
    throw new Error("잘못된 경로입니다");
  }
  return resolved;
}

router.get("/tree", (req, res) => {
  const { name, dir } = req.query;
  if (!name) return res.status(400).json({ error: "name은 필수입니다" });

  try {
    const target = resolveInUnpack(name, dir || "");
    if (!fs.existsSync(target)) return res.status(404).json({ error: "디렉터리를 찾을 수 없습니다" });

    const dirents = fs.readdirSync(target, { withFileTypes: true });
    const names = new Set(dirents.map((e) => e.name));
    const entries = dirents.map((e) => {
      const relPath = path.join(dir || "", e.name);
      if (e.isDirectory()) {
        return { name: e.name, type: "dir", path: relPath };
      }
      const ext = path.extname(e.name).toLowerCase();
      const stat = fs.statSync(path.join(target, e.name));
      const isStdImage = IMAGE_EXTS.has(ext);
      const isNbfcImage =
        (ext === ".nbfc" && hasNbfcSiblings(names, e.name.slice(0, -".nbfc".length), false)) ||
        (ext === ".nbfcn" && hasNbfcSiblings(names, e.name.slice(0, -".nbfcn".length), true));
      const binParts = ext === ".bin" ? binImageParts(e.name) : null;
      const isBinImage = binParts !== null && hasBinSiblings(names, binParts);
      return {
        name: e.name,
        type: "file",
        path: relPath,
        size: stat.size,
        isImage: isStdImage || isNbfcImage || isBinImage,
      };
    });
    entries.sort((a, b) => (a.type === b.type ? a.name.localeCompare(b.name) : a.type === "dir" ? -1 : 1));
    res.json(entries);
  } catch (ex) {
    res.status(400).json({ error: ex.message });
  }
});

router.get("/raw", (req, res) => {
  const { name, path: relPath } = req.query;
  if (!name || !relPath) return res.status(400).json({ error: "name, path는 필수입니다" });

  try {
    const ext = path.extname(relPath).toLowerCase();
    const target = resolveInUnpack(name, relPath);
    if (!fs.existsSync(target)) return res.status(404).json({ error: "파일을 찾을 수 없습니다" });

    if (IMAGE_EXTS.has(ext)) {
      return res.sendFile(target);
    }
    if (ext === ".nbfc" || ext === ".nbfcn") {
      const isNn = ext === ".nbfcn";
      const base = target.slice(0, -ext.length);
      const nbfpPath = base + (isNn ? ".nbfpn" : ".nbfp");
      const nbfsPath = base + ".nbfs";
      if (!fs.existsSync(nbfpPath) || !fs.existsSync(nbfsPath)) {
        return res.status(400).json({ error: `짝이 되는 ${isNn ? ".nbfpn" : ".nbfp"}/.nbfs 파일이 없어 디코딩할 수 없습니다` });
      }
      const png = nbfcImage.decodeTilemapPng(
        fs.readFileSync(target),
        fs.readFileSync(nbfpPath),
        fs.readFileSync(nbfsPath)
      );
      res.type("png").send(png);
      return;
    }
    if (ext === ".bin") {
      const fname = path.basename(target);
      const parts = binImageParts(fname);
      if (!parts) {
        return res.status(400).json({ error: "이미지로 인식되지 않는 .bin 파일입니다" });
      }
      const dir = path.dirname(target);
      const { screen, palette } = binSiblingNames(parts);
      const screenPath = path.join(dir, screen);
      const palettePath = path.join(dir, palette);
      if (!fs.existsSync(screenPath) || !fs.existsSync(palettePath)) {
        return res.status(400).json({
          error: `짝이 되는 스크린/팔레트 파일이 없어 디코딩할 수 없습니다 (필요: ${screen}, ${palette})`,
        });
      }
      const png = nbfcImage.decodeTilemapPng(
        fs.readFileSync(target),
        fs.readFileSync(palettePath),
        fs.readFileSync(screenPath)
      );
      res.type("png").send(png);
      return;
    }
    return res.status(400).json({ error: `미리보기를 지원하지 않는 형식입니다: ${ext}` });
  } catch (ex) {
    res.status(400).json({ error: ex.message });
  }
});

module.exports = router;
