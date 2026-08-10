"use strict";

const express = require("express");
const fs = require("fs");
const proj = require("../lib/project");
const pipeline = require("../lib/pipeline");
const { translateBatch: macTranslateBatch } = require("../lib/macTranslate");

const router = express.Router();

router.post("/extract", (req, res) => {
  const { name } = req.body || {};
  if (!name) return res.status(400).json({ error: "name은 필수입니다" });
  if (!proj.readState(name)) return res.status(404).json({ error: "프로젝트를 찾을 수 없습니다" });

  try {
    const summary = pipeline.extractProject(name);
    proj.writeState(name, { extractedAt: new Date().toISOString() });
    res.json(summary);
  } catch (ex) {
    res.status(500).json({ error: ex.message });
  }
});

router.get("/files", (req, res) => {
  const { name } = req.query;
  if (!name) return res.status(400).json({ error: "name은 필수입니다" });
  try {
    res.json(pipeline.fileSummaries(name));
  } catch (ex) {
    res.status(500).json({ error: ex.message });
  }
});

router.get("/file/:fname", (req, res) => {
  const { name } = req.query;
  if (!name) return res.status(400).json({ error: "name은 필수입니다" });
  try {
    res.json(pipeline.rowsForFile(name, req.params.fname));
  } catch (ex) {
    res.status(500).json({ error: ex.message });
  }
});

router.post("/file/:fname", (req, res) => {
  const { name } = req.query;
  const edits = req.body;
  if (!name) return res.status(400).json({ error: "name은 필수입니다" });
  if (!Array.isArray(edits)) return res.status(400).json({ error: "body는 [{block, translation}] 배열이어야 합니다" });

  try {
    const report = pipeline.saveFile(name, req.params.fname, edits);
    res.json({ ok: true, report });
  } catch (ex) {
    res.status(500).json({ error: ex.message });
  }
});

router.get("/translate-stream", async (req, res) => {
  const { name, fname } = req.query || {};
  if (!name || !fname) return res.status(400).send("name, fname은 필수입니다.");

  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");

  const sendEvent = (data) => {
    res.write(`data: ${JSON.stringify(data)}\n\n`);
  };

  try {
    const fileRows = pipeline.rowsForFile(name, fname);
    if (fileRows.length === 0) {
      sendEvent({ type: "error", message: "번역할 대사 행이 없습니다." });
      return res.end();
    }

    const sources = fileRows.map((r) => r.source);
    sendEvent({ type: "start", total: sources.length });

    const translatedList = await macTranslateBatch(sources, (msg) => {
      sendEvent({ type: "progress", message: msg });
    });

    const edits = fileRows.map((r, idx) => ({
      block: Number(r.block),
      ai_draft: translatedList[idx],
      translation: translatedList[idx],
    }));

    const report = pipeline.saveFile(name, fname, edits);
    sendEvent({ type: "done", translatedCount: edits.length, report });
    res.end();
  } catch (ex) {
    sendEvent({ type: "error", message: ex.message });
    res.end();
  }
});

const { execFile } = require("child_process");

router.get("/download", (req, res) => {
  const { name } = req.query;
  if (!name) return res.status(400).json({ error: "name은 필수입니다" });

  const transDir = proj.csvDir(name);
  if (!fs.existsSync(transDir)) {
    // 혹시 마스터 파일만 존재하는 경우
    const filePath = proj.csvPath(name);
    if (!fs.existsSync(filePath)) return res.status(404).json({ error: "CSV 파일이 없습니다. 먼저 생성/갱신하세요" });
    return res.download(filePath, `${name}_translation_export.csv`);
  }

  const zipPath = path.join(proj.projectDir(name), `${name}_translations.zip`);
  execFile("zip", ["-r", zipPath, "translations"], { cwd: proj.projectDir(name) }, (err) => {
    if (err) {
      return res.status(500).json({ error: `ZIP 압축 실패: ${err.message}` });
    }
    res.download(zipPath, `${name}_translations.zip`);
  });
});

module.exports = router;
