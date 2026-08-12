"use strict";

const express = require("express");
const multer = require("multer");
const fs = require("fs");
const path = require("path");

const proj = require("../lib/project");
const nbfcImage = require("../lib/nbfcImage");

const router = express.Router();
const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 16 * 1024 * 1024 } });
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

/** 타깃 경로(.nbfc/.nbfcn/_bg_*c.bin)로부터 타일/팔레트/스크린맵 절대경로를 결정한다.
 * GET /raw(디코딩)와 POST /image(인코딩) 양쪽에서 공유하는 "짝 파일 찾기" 로직. 짝이
 * 되는 파일이 없거나 인식되지 않는 형식이면 { error }를, 성공하면
 * { tilePath, palettePath, screenPath }를 반환한다. */
function resolveTripletPaths(target) {
  const ext = path.extname(target).toLowerCase();
  if (ext === ".nbfc" || ext === ".nbfcn") {
    const isNn = ext === ".nbfcn";
    const base = target.slice(0, -ext.length);
    const palettePath = base + (isNn ? ".nbfpn" : ".nbfp");
    const screenPath = base + ".nbfs";
    if (!fs.existsSync(palettePath) || !fs.existsSync(screenPath)) {
      return { error: `짝이 되는 ${isNn ? ".nbfpn" : ".nbfp"}/.nbfs 파일이 없어 처리할 수 없습니다` };
    }
    return { tilePath: target, palettePath, screenPath };
  }
  if (ext === ".bin") {
    const fname = path.basename(target);
    const parts = binImageParts(fname);
    if (!parts) {
      return { error: "이미지로 인식되지 않는 .bin 파일입니다" };
    }
    const dir = path.dirname(target);
    const { screen, palette } = binSiblingNames(parts);
    const screenPath = path.join(dir, screen);
    const palettePath = path.join(dir, palette);
    if (!fs.existsSync(screenPath) || !fs.existsSync(palettePath)) {
      return {
        error: `짝이 되는 스크린/팔레트 파일이 없어 처리할 수 없습니다 (필요: ${screen}, ${palette})`,
      };
    }
    return { tilePath: target, palettePath, screenPath };
  }
  return { error: `타일맵 이미지로 인식되지 않는 형식입니다: ${ext}` };
}

/** unpack/ 트리 전체를 재귀 탐색하며 인코딩 가능한(짝이 있는) 타일 파일을 모아
 * { base(확장자 뺀 소문자 파일명), rel(unpack 루트 기준 상대경로) } 목록으로 반환한다.
 * 여러 이미지를 한 번에 업로드했을 때 파일명만으로 대상을 찾는 POST /images-batch가 사용. */
function walkImageFiles(dir, root, out) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) {
      walkImageFiles(full, root, out);
      continue;
    }
    const ext = path.extname(e.name).toLowerCase();
    if (ext !== ".nbfc" && ext !== ".nbfcn" && ext !== ".bin") continue;
    if (resolveTripletPaths(full).error) continue;
    out.push({ base: path.basename(e.name, ext).toLowerCase(), rel: path.relative(root, full) });
  }
}

function findImagesByBasename(name, targetBase) {
  const root = proj.unpackDir(name);
  const all = [];
  walkImageFiles(root, root, all);
  return all.filter((f) => f.base === targetBase.toLowerCase());
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
    if (ext === ".nbfc" || ext === ".nbfcn" || ext === ".bin") {
      const resolved = resolveTripletPaths(target);
      if (resolved.error) return res.status(400).json({ error: resolved.error });
      const png = nbfcImage.decodeTilemapPng(
        fs.readFileSync(resolved.tilePath),
        fs.readFileSync(resolved.palettePath),
        fs.readFileSync(resolved.screenPath)
      );
      // "다른 이름으로 저장"한 PNG를 나중에 파일명으로 자동 매칭(POST /images-batch)할 수
      // 있도록, 원본 타일 파일의 basename을 저장 파일명 힌트로 제공한다.
      const base = path.basename(target, ext);
      res.set("Content-Disposition", `inline; filename="${base}.png"`);
      res.type("png").send(png);
      return;
    }
    return res.status(400).json({ error: `미리보기를 지원하지 않는 형식입니다: ${ext}` });
  } catch (ex) {
    res.status(400).json({ error: ex.message });
  }
});

// POST /api/files/image  multipart/form-data: image (PNG)
// query: name, path - 업로드한 PNG를 타일/스크린맵으로 재인코딩해 프로젝트의 unpack/
// 작업 사본에 그대로 덮어쓴다(팔레트는 수정하지 않음). 이후 재삽입/빌드 시 자동 반영됨.
router.post("/image", upload.single("image"), (req, res) => {
  const { name, path: relPath } = req.query;
  if (!name || !relPath) return res.status(400).json({ error: "name, path는 필수입니다" });
  if (!req.file) return res.status(400).json({ error: "image 파일이 필요합니다" });

  try {
    const ext = path.extname(relPath).toLowerCase();
    if (ext !== ".nbfc" && ext !== ".nbfcn" && ext !== ".bin") {
      return res.status(400).json({ error: `리팩을 지원하지 않는 형식입니다: ${ext}` });
    }
    const target = resolveInUnpack(name, relPath);
    if (!fs.existsSync(target)) return res.status(404).json({ error: "파일을 찾을 수 없습니다" });

    const resolved = resolveTripletPaths(target);
    if (resolved.error) return res.status(400).json({ error: resolved.error });

    const paletteBuf = fs.readFileSync(resolved.palettePath);
    const screenBuf = fs.readFileSync(resolved.screenPath);
    const origEntryCount = nbfcImage.loadScreen(screenBuf).length;

    const { nbfc, nbfs } = nbfcImage.encodeTilemapPng(req.file.buffer, paletteBuf, origEntryCount);
    fs.writeFileSync(resolved.tilePath, nbfc);
    fs.writeFileSync(resolved.screenPath, nbfs);
    res.json({ ok: true, tileCount: origEntryCount });
  } catch (ex) {
    res.status(400).json({ error: ex.message });
  }
});

// POST /api/files/images-batch  multipart/form-data: images (여러 PNG)
// query: name - 각 업로드 파일의 원래 파일명(확장자 제외)으로 unpack/ 트리 전체를 뒤져
// 같은 이름의 타일 파일을 찾아 자동으로 재인코딩해 덮어쓴다. GET /raw가 내려주는
// Content-Disposition filename 힌트를 그대로 "다른 이름으로 저장"하면 파일명이 맞아떨어짐.
router.post("/images-batch", upload.array("images", 100), (req, res) => {
  const { name } = req.query;
  if (!name) return res.status(400).json({ error: "name은 필수입니다" });
  if (!req.files || !req.files.length) return res.status(400).json({ error: "images 파일이 필요합니다" });

  const root = proj.unpackDir(name);
  if (!fs.existsSync(root)) return res.status(404).json({ error: "프로젝트를 찾을 수 없습니다" });

  const results = req.files.map((file) => {
    const base = path.parse(file.originalname).name;
    try {
      const matches = findImagesByBasename(name, base);
      if (matches.length === 0) {
        return { file: file.originalname, ok: false, error: "일치하는 파일을 찾지 못했습니다" };
      }
      if (matches.length > 1) {
        return {
          file: file.originalname,
          ok: false,
          error: `여러 파일과 일치해 자동 선택할 수 없습니다: ${matches.map((m) => m.rel).join(", ")}`,
        };
      }
      const match = matches[0];
      const target = path.join(root, match.rel);
      const resolved = resolveTripletPaths(target);
      if (resolved.error) return { file: file.originalname, ok: false, error: resolved.error };

      const paletteBuf = fs.readFileSync(resolved.palettePath);
      const screenBuf = fs.readFileSync(resolved.screenPath);
      const origEntryCount = nbfcImage.loadScreen(screenBuf).length;
      const { nbfc, nbfs } = nbfcImage.encodeTilemapPng(file.buffer, paletteBuf, origEntryCount);
      fs.writeFileSync(resolved.tilePath, nbfc);
      fs.writeFileSync(resolved.screenPath, nbfs);
      return { file: file.originalname, ok: true, matchedPath: match.rel, tileCount: origEntryCount };
    } catch (ex) {
      return { file: file.originalname, ok: false, error: ex.message };
    }
  });

  res.json({ results });
});

module.exports = router;
