"use strict";

const state = {
  projectName: localStorage.getItem("domtool.projectName") || null,
  currentFile: null,
  currentRows: [],
  imageDir: "",
  csvGroup: "dom1",
  allFiles: [],
  dirty: false,
};

function markDirty() {
  state.dirty = true;
  document.getElementById("btn-save-csv").classList.add("dirty");
}

function clearDirty() {
  state.dirty = false;
  document.getElementById("btn-save-csv").classList.remove("dirty");
}

function confirmDiscardIfDirty() {
  if (!state.dirty) return true;
  return confirm("저장하지 않은 번역 변경사항이 있습니다. 이동하면 사라집니다. 계속하시겠습니까?");
}

window.addEventListener("beforeunload", (e) => {
  if (!state.dirty) return;
  e.preventDefault();
  e.returnValue = "";
});

function setActiveProject(name) {
  state.projectName = name;
  localStorage.setItem("domtool.projectName", name || "");
  document.getElementById("active-project-name").textContent = name || "없음";
  refreshProjectList();
  refreshStatus();
  refreshFileList();
  loadTree("");
  updateCsvDownloadLink();
}

function updateCsvDownloadLink() {
  const link = document.getElementById("btn-download-csv");
  if (state.projectName) {
    link.href = `/api/csv/download?name=${encodeURIComponent(state.projectName)}`;
    link.classList.remove("hidden");
  } else {
    link.href = "#";
  }
}

async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `요청 실패: ${res.status}`);
  return data;
}

// ---- 탭 전환 ----
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const current = document.querySelector(".tab-btn.active");
    const leavingCsv = current && current.dataset.tab === "tab-csv" && btn.dataset.tab !== "tab-csv";
    if (leavingCsv && !confirmDiscardIfDirty()) return;
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab).classList.add("active");
  });
});

// ---- 탭 1: 프로젝트 ----
async function refreshProjectList() {
  const list = document.getElementById("project-list");
  list.innerHTML = "";
  try {
    const projects = await api("GET", "/api/project/list");
    if (!projects.length) {
      list.innerHTML = "<li>등록된 프로젝트가 없습니다</li>";
      return;
    }
    for (const p of projects) {
      const li = document.createElement("li");
      li.textContent = `${p.projectName} (${p.romFileName || "?"})`;
      if (p.projectName === state.projectName) li.classList.add("selected");
      li.addEventListener("click", () => setActiveProject(p.projectName));
      list.appendChild(li);
    }
  } catch (ex) {
    list.innerHTML = `<li>목록 로드 실패: ${ex.message}</li>`;
  }
}

// ROM 파일 선택: 클릭(파일 열기 다이얼로그) 또는 드래그앤드롭 — 브라우저는 로컬 파일의
// 절대경로를 노출하지 않으므로, 파일 자체를 서버로 업로드해서 그 사본으로 언팩한다.
let selectedRomFile = null;
const dropzone = document.getElementById("rom-dropzone");
const dropzoneText = document.getElementById("rom-dropzone-text");
const romFileInput = document.getElementById("rom-file-input");

function setRomFile(file) {
  selectedRomFile = file || null;
  dropzoneText.textContent = selectedRomFile
    ? `선택됨: ${selectedRomFile.name} (${(selectedRomFile.size / 1024 / 1024).toFixed(1)} MB)`
    : "ROM(.nds) 파일을 여기로 드래그하거나 클릭해서 선택하세요";
}

dropzone.addEventListener("click", () => romFileInput.click());
romFileInput.addEventListener("change", () => setRomFile(romFileInput.files[0]));

["dragenter", "dragover"].forEach((evt) => {
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });
});
["dragleave", "drop"].forEach((evt) => {
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
  });
});
dropzone.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files && e.dataTransfer.files[0];
  if (file) setRomFile(file);
});

document.getElementById("unpack-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const projectName = document.getElementById("project-name").value.trim();
  const resultBox = document.getElementById("unpack-result");
  if (!selectedRomFile) {
    resultBox.textContent = "ROM 파일을 먼저 선택하세요";
    return;
  }
  resultBox.textContent = "업로드 및 언팩 중...";
  try {
    const fd = new FormData();
    fd.append("projectName", projectName);
    fd.append("romFile", selectedRomFile);
    const res = await fetch("/api/project/unpack", { method: "POST", body: fd });
    const result = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(result.error || `요청 실패: ${res.status}`);
    resultBox.textContent = `언팩 완료: ${result.mesCount}개의 .mes 파일 발견`;
    setRomFile(null);
    romFileInput.value = "";
    setActiveProject(projectName);
  } catch (ex) {
    resultBox.textContent = `오류: ${ex.message}`;
  }
});

async function refreshStatus() {
  const box = document.getElementById("project-status");
  if (!state.projectName) {
    box.textContent = "프로젝트를 선택하세요";
    return;
  }
  try {
    const s = await api("GET", `/api/project/status?name=${encodeURIComponent(state.projectName)}`);
    box.textContent = JSON.stringify(s, null, 2);
  } catch (ex) {
    box.textContent = `상태 조회 실패: ${ex.message}`;
  }
}

// ---- 탭 2: 번역 CSV ----
document.getElementById("btn-extract").addEventListener("click", async () => {
  const box = document.getElementById("extract-result");
  if (!state.projectName) return (box.textContent = "먼저 프로젝트를 선택하세요");
  box.textContent = "추출 중...";
  try {
    const summary = await api("POST", "/api/csv/extract", { name: state.projectName });
    box.textContent = JSON.stringify(summary, null, 2);
    refreshFileList();
    refreshStatus();
  } catch (ex) {
    box.textContent = `오류: ${ex.message}`;
  }
});

// 번역 대상 .mes 파일은 전부 dom1/dom2/dom3 중 하나로 시작(data/Script/ 865개 파일 전수 확인,
// 접두사 기준 셋 중 어디에도 안 걸리는 파일 0개) — 파일이 너무 많아 게임 루트별 탭으로 나눔.
document.querySelectorAll(".subtab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (!confirmDiscardIfDirty()) return;
    document.querySelectorAll(".subtab-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.csvGroup = btn.dataset.group;
    renderFileSelect();
  });
});

async function refreshFileList() {
  const select = document.getElementById("file-select");
  select.innerHTML = "";
  state.allFiles = [];
  if (!state.projectName) return;
  try {
    state.allFiles = await api("GET", `/api/csv/files?name=${encodeURIComponent(state.projectName)}`);
    renderFileSelect();
  } catch (ex) {
    select.innerHTML = `<option>목록 로드 실패</option>`;
  }
}

function renderFileSelect() {
  const select = document.getElementById("file-select");
  select.innerHTML = "";
  let files = [];
  if (state.csvGroup === "system_common") {
    files = state.allFiles.filter((f) => !f.file.startsWith("dom1") && !f.file.startsWith("dom2") && !f.file.startsWith("dom3"));
  } else {
    files = state.allFiles.filter((f) => f.file.startsWith(state.csvGroup));
  }
  for (const f of files) {
    const opt = document.createElement("option");
    opt.value = f.file;
    opt.textContent = `${f.file} (${f.translatedCount}/${f.blockCount} 번역됨)`;
    select.appendChild(opt);
  }
  if (!files.length) {
    state.currentFile = null;
    state.currentRows = [];
    renderCsvTable([]);
    return;
  }
  if (files.some((f) => f.file === state.currentFile)) {
    select.value = state.currentFile;
  } else {
    loadFileRows(files[0].file);
  }
}

document.getElementById("file-select").addEventListener("change", (e) => {
  if (!confirmDiscardIfDirty()) {
    e.target.value = state.currentFile;
    return;
  }
  loadFileRows(e.target.value);
});

document.getElementById("btn-auto-translate").addEventListener("click", () => {
  if (!state.projectName || !state.currentFile) return alert("프로젝트와 파일이 선택되지 않았습니다.");
  if (!confirmDiscardIfDirty()) return;

  const box = document.getElementById("translate-progress");
  box.classList.remove("hidden");
  box.textContent = "";

  const appendLog = (line) => {
    const ts = new Date().toLocaleTimeString("ko-KR", { hour12: false });
    box.textContent += `[${ts}] ${line}\n`;
    box.scrollTop = box.scrollHeight;
  };

  appendLog("자동 초벌번역 준비 중...");

  const engine = document.getElementById("engine-select").value;
  const url = `/api/csv/translate-stream?name=${encodeURIComponent(state.projectName)}&fname=${encodeURIComponent(state.currentFile)}&engine=${encodeURIComponent(engine)}`;
  const es = new EventSource(url);

  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.type === "start") {
        appendLog(`총 ${data.total}개 대사 초벌번역 시작...`);
      } else if (data.type === "progress") {
        appendLog(data.message);
      } else if (data.type === "done") {
        appendLog(`초벌번역 완료! (총 ${data.translatedCount}행 처리됨)`);
        const failed = Array.isArray(data.report) ? data.report.filter((r) => !r.ok) : [];
        if (failed.length) {
          appendLog(`⚠ 검증 문제 ${failed.length}건 (저장은 됐으나 재삽입 시 스킵될 수 있음):`);
          for (const r of failed.slice(0, 20)) appendLog(`  - block ${r.block}: ${r.error}`);
          if (failed.length > 20) appendLog(`  ... 외 ${failed.length - 20}건`);
        }
        es.close();
        loadFileRows(state.currentFile);
        refreshFileList();
      } else if (data.type === "error") {
        appendLog(`오류: ${data.message}`);
        es.close();
      }
    } catch (err) {
      appendLog(`이벤트 처리 실패: ${err.message}`);
      es.close();
    }
  };

  es.onerror = () => {
    appendLog("서버 연결 오류가 발생했습니다.");
    es.close();
  };
});

async function loadFileRows(fname) {
  if (!fname || !state.projectName) return;
  state.currentFile = fname;
  const rows = await api("GET", `/api/csv/file/${encodeURIComponent(fname)}?name=${encodeURIComponent(state.projectName)}`);
  state.currentRows = rows;
  renderCsvTable(rows);
  clearDirty();
}

function renderCsvTable(rows) {
  const body = document.getElementById("csv-table-body");
  body.innerHTML = "";
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.dataset.block = row.block;
    tr.dataset.source = row.source;
    tr.dataset.aiDraft = row.ai_draft || "";
    const maxLen = row.max_len === null || row.max_len === undefined ? "제한없음" : row.max_len;
    tr.innerHTML = `
      <td>${row.block}</td>
      <td>${maxLen}</td>
      <td>${escapeHtml(row.speaker || "")}</td>
      <td>${escapeHtml(row.source)}</td>
      <td>${escapeHtml(row.ai_draft || "")}</td>
      <td>
        <button type="button" class="btn-copy-source" title="원문을 번역란에 복사">원문 복사</button>
        <button type="button" class="btn-copy-ai" title="기계번역(초벌번역)을 번역란에 복사">기계번역 복사</button>
        <textarea class="translation-input">${escapeHtml(row.translation || "")}</textarea>
      </td>
      <td class="status-cell"></td>
    `;
    body.appendChild(tr);
  }
}

document.getElementById("csv-table-body").addEventListener("click", (e) => {
  const tr = e.target.closest("tr");
  if (!tr) return;
  if (e.target.classList.contains("btn-copy-source")) {
    tr.querySelector(".translation-input").value = tr.dataset.source;
    markDirty();
  } else if (e.target.classList.contains("btn-copy-ai")) {
    tr.querySelector(".translation-input").value = tr.dataset.aiDraft;
    markDirty();
  }
});

document.getElementById("csv-table-body").addEventListener("input", (e) => {
  if (e.target.classList.contains("translation-input")) markDirty();
});

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

document.getElementById("btn-save-csv").addEventListener("click", async () => {
  if (!state.projectName || !state.currentFile) return;
  const rowsEl = document.querySelectorAll("#csv-table-body tr");
  const edits = Array.from(rowsEl).map((tr) => ({
    block: Number(tr.dataset.block),
    translation: tr.querySelector(".translation-input").value,
  }));
  try {
    const result = await api(
      "POST",
      `/api/csv/file/${encodeURIComponent(state.currentFile)}?name=${encodeURIComponent(state.projectName)}`,
      edits
    );
    const byBlock = new Map(result.report.map((r) => [r.block, r]));
    rowsEl.forEach((tr) => {
      const r = byBlock.get(Number(tr.dataset.block));
      const cell = tr.querySelector(".status-cell");
      if (!r) return;
      cell.textContent = r.ok ? "OK" : r.error;
      cell.className = "status-cell " + (r.ok ? "badge-ok" : "badge-error");
    });
    clearDirty();
    refreshFileList();
  } catch (ex) {
    alert(`저장 실패: ${ex.message}`);
  }
});

// ---- 탭 3: 이미지 탐색 ----
async function loadTree(dir) {
  state.imageDir = dir;
  renderBreadcrumb(dir);
  const list = document.getElementById("file-tree");
  list.innerHTML = "";
  if (!state.projectName) return;
  try {
    const entries = await api(
      "GET",
      `/api/files/tree?name=${encodeURIComponent(state.projectName)}&dir=${encodeURIComponent(dir)}`
    );
    for (const e of entries) {
      const li = document.createElement("li");
      li.textContent = e.type === "dir" ? `📁 ${e.name}` : `${e.isImage ? "🖼️" : "📄"} ${e.name}`;
      li.addEventListener("click", () => {
        if (e.type === "dir") {
          loadTree(e.path);
        } else if (e.isImage) {
          document.getElementById("image-upload-status").textContent = "";
          previewImage(e.path);
        } else {
          document.getElementById("image-preview").textContent = `${e.name} (${e.size} bytes) - 미리보기 미지원 형식`;
        }
      });
      list.appendChild(li);
    }
  } catch (ex) {
    list.innerHTML = `<li>로드 실패: ${ex.message}</li>`;
  }
}

function renderBreadcrumb(dir) {
  const bc = document.getElementById("breadcrumb");
  bc.innerHTML = "";
  const root = document.createElement("span");
  root.textContent = "(루트)";
  root.addEventListener("click", () => loadTree(""));
  bc.appendChild(root);
  if (!dir) return;
  const parts = dir.split("/").filter(Boolean);
  let acc = "";
  for (const part of parts) {
    acc = acc ? `${acc}/${part}` : part;
    bc.appendChild(document.createTextNode(" / "));
    const span = document.createElement("span");
    span.textContent = part;
    const target = acc;
    span.addEventListener("click", () => loadTree(target));
    bc.appendChild(span);
  }
}

function previewImage(relPath) {
  state.currentImagePath = relPath;
  selectedImageFile = null;
  document.getElementById("image-upload-input").value = "";
  const preview = document.getElementById("image-preview");
  preview.innerHTML = "";
  const img = document.createElement("img");
  img.src = `/api/files/raw?name=${encodeURIComponent(state.projectName)}&path=${encodeURIComponent(relPath)}&t=${Math.floor(performance.now())}`;
  preview.appendChild(img);
}

// 이미지 파일 선택: 클릭(파일 열기 다이얼로그) 또는 드래그앤드롭 - ROM 업로드의
// selectedRomFile/setRomFile 패턴과 동일.
let selectedImageFile = null;
const imageDropzone = document.getElementById("image-dropzone");
const imageUploadInput = document.getElementById("image-upload-input");

function setImageFile(file) {
  selectedImageFile = file || null;
  document.getElementById("image-upload-status").textContent = selectedImageFile
    ? `선택됨: ${selectedImageFile.name}`
    : "";
}

imageDropzone.addEventListener("click", () => imageUploadInput.click());
imageUploadInput.addEventListener("change", () => setImageFile(imageUploadInput.files[0]));

["dragenter", "dragover"].forEach((evt) => {
  imageDropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    imageDropzone.classList.add("dragover");
  });
});
["dragleave", "drop"].forEach((evt) => {
  imageDropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    imageDropzone.classList.remove("dragover");
  });
});
imageDropzone.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files && e.dataTransfer.files[0];
  if (file) setImageFile(file);
});

document.getElementById("btn-image-upload").addEventListener("click", async () => {
  const status = document.getElementById("image-upload-status");
  if (!state.projectName || !state.currentImagePath) {
    status.textContent = "먼저 이미지를 선택하세요";
    return;
  }
  if (!selectedImageFile) {
    status.textContent = "업로드할 PNG 파일을 선택하세요";
    return;
  }
  status.textContent = "업로드 중...";
  try {
    const fd = new FormData();
    fd.append("image", selectedImageFile);
    const res = await fetch(
      `/api/files/image?name=${encodeURIComponent(state.projectName)}&path=${encodeURIComponent(state.currentImagePath)}`,
      { method: "POST", body: fd }
    );
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `요청 실패: ${res.status}`);
    previewImage(state.currentImagePath);
    status.textContent = `적용됨 (타일 ${data.tileCount}개) - 다음 재삽입/빌드에 반영됩니다`;
  } catch (ex) {
    status.textContent = `실패: ${ex.message}`;
  }
});

// 여러 PNG를 한 번에 드래그앤드롭/선택 - 탐색 트리에서 대상을 고를 필요 없이 파일명으로
// 서버가 자동으로 짝을 찾아 교체한다(POST /api/files/images-batch).
let selectedBatchFiles = [];
const batchDropzone = document.getElementById("batch-image-dropzone");
const batchImageInput = document.getElementById("batch-image-input");

function setBatchFiles(fileList) {
  selectedBatchFiles = fileList ? Array.from(fileList) : [];
  const box = document.getElementById("batch-image-result");
  box.textContent = selectedBatchFiles.length
    ? `${selectedBatchFiles.length}개 파일 선택됨 - "일괄 교체 실행"을 누르세요\n(${selectedBatchFiles.map((f) => f.name).join(", ")})`
    : "";
}

batchDropzone.addEventListener("click", () => batchImageInput.click());
batchImageInput.addEventListener("change", () => setBatchFiles(batchImageInput.files));

["dragenter", "dragover"].forEach((evt) => {
  batchDropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    batchDropzone.classList.add("dragover");
  });
});
["dragleave", "drop"].forEach((evt) => {
  batchDropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    batchDropzone.classList.remove("dragover");
  });
});
batchDropzone.addEventListener("drop", (e) => {
  if (e.dataTransfer.files && e.dataTransfer.files.length) setBatchFiles(e.dataTransfer.files);
});

document.getElementById("btn-batch-image-upload").addEventListener("click", async () => {
  const box = document.getElementById("batch-image-result");
  if (!state.projectName) {
    box.textContent = "먼저 프로젝트를 선택하세요";
    return;
  }
  if (!selectedBatchFiles.length) {
    box.textContent = "PNG 파일을 먼저 선택하세요";
    return;
  }
  box.textContent = `${selectedBatchFiles.length}개 파일 업로드 중...`;
  try {
    const fd = new FormData();
    for (const f of selectedBatchFiles) fd.append("images", f);
    const res = await fetch(`/api/files/images-batch?name=${encodeURIComponent(state.projectName)}`, {
      method: "POST",
      body: fd,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `요청 실패: ${res.status}`);
    const lines = data.results.map((r) =>
      r.ok ? `✅ ${r.file} -> ${r.matchedPath} (타일 ${r.tileCount}개)` : `❌ ${r.file}: ${r.error}`
    );
    selectedBatchFiles = [];
    batchImageInput.value = "";
    if (state.currentImagePath && data.results.some((r) => r.ok && r.matchedPath === state.currentImagePath)) {
      previewImage(state.currentImagePath);
    }
    box.textContent = lines.join("\n");
  } catch (ex) {
    box.textContent = `실패: ${ex.message}`;
  }
});

// ---- 탭 4: 빌드 ----
document.getElementById("btn-reinsert").addEventListener("click", async () => {
  const box = document.getElementById("reinsert-result");
  if (!state.projectName) return (box.textContent = "먼저 프로젝트를 선택하세요");
  box.textContent = "재삽입 중...";
  try {
    const result = await api("POST", "/api/build/reinsert", { name: state.projectName });
    box.textContent = JSON.stringify(result, null, 2);
  } catch (ex) {
    box.textContent = `오류: ${ex.message}`;
  }
});

document.getElementById("btn-pack").addEventListener("click", async () => {
  const box = document.getElementById("pack-result");
  const link = document.getElementById("download-link");
  link.classList.add("hidden");
  if (!state.projectName) return (box.textContent = "먼저 프로젝트를 선택하세요");
  box.textContent = "빌드 중...";
  try {
    const result = await api("POST", "/api/build/pack", { name: state.projectName });
    box.textContent = JSON.stringify(result, null, 2);
    link.href = `/api/build/download?name=${encodeURIComponent(state.projectName)}`;
    link.classList.remove("hidden");
  } catch (ex) {
    box.textContent = `오류: ${ex.message}`;
  }
});

// ---- 초기화 ----
document.getElementById("project-name").value = "";
if (state.projectName) {
  document.getElementById("active-project-name").textContent = state.projectName;
}
refreshProjectList();
refreshStatus();
refreshFileList();
loadTree("");
updateCsvDownloadLink();
