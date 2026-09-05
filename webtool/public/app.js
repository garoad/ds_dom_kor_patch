"use strict";

// 이 게임은 ROM이 하나뿐이라 여러 프로젝트를 오가며 작업할 일이 없어, 프로젝트
// 이름을 매번 입력/선택하게 하는 대신 고정 워크스페이스 이름 하나만 쓴다.
const PROJECT_NAME = "dom1";

const state = {
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

function updateCsvDownloadLink() {
  const link = document.getElementById("btn-download-csv");
  link.href = `/api/csv/download?name=${encodeURIComponent(PROJECT_NAME)}`;
  link.classList.remove("hidden");
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
  const resultBox = document.getElementById("unpack-result");
  if (!selectedRomFile) {
    resultBox.textContent = "ROM 파일을 먼저 선택하세요";
    return;
  }
  resultBox.textContent = "업로드 및 언팩 중...";
  try {
    const fd = new FormData();
    fd.append("projectName", PROJECT_NAME);
    fd.append("romFile", selectedRomFile);
    const res = await fetch("/api/project/unpack", { method: "POST", body: fd });
    const result = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(result.error || `요청 실패: ${res.status}`);
    resultBox.textContent = `언팩 완료: ${result.mesCount}개의 .mes 파일 발견`;
    setRomFile(null);
    romFileInput.value = "";
    refreshStatus();
    refreshFileList();
    loadTree("");
    updateCsvDownloadLink();
  } catch (ex) {
    resultBox.textContent = `오류: ${ex.message}`;
  }
});

async function refreshStatus() {
  const box = document.getElementById("project-status");
  try {
    const s = await api("GET", `/api/project/status?name=${encodeURIComponent(PROJECT_NAME)}`);
    box.textContent = JSON.stringify(s, null, 2);
  } catch (ex) {
    box.textContent = `상태 조회 실패: ${ex.message}`;
  }
}

// ---- 탭 2: 번역 CSV ----
document.getElementById("btn-extract").addEventListener("click", async () => {
  const box = document.getElementById("extract-result");
  box.textContent = "추출 중...";
  try {
    const summary = await api("POST", "/api/csv/extract", { name: PROJECT_NAME });
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
  try {
    state.allFiles = await api("GET", `/api/csv/files?name=${encodeURIComponent(PROJECT_NAME)}`);
    renderFileSelect();
  } catch (ex) {
    select.innerHTML = `<option>목록 로드 실패</option>`;
  }
}

function renderFileSelect(targetFileToSelect) {
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
  const fileToSelect = targetFileToSelect || state.currentFile;
  if (fileToSelect && files.some((f) => f.file === fileToSelect)) {
    select.value = fileToSelect;
    if (fileToSelect !== state.currentFile) {
      loadFileRows(fileToSelect);
    }
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

// ---- CSV 검색 기능 ----
function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function highlightKeyword(text, keyword) {
  if (!text) return "";
  if (!keyword || !keyword.trim()) return escapeHtml(text);
  const escaped = escapeHtml(text);
  const regex = new RegExp(`(${escapeRegex(keyword)})`, "gi");
  return escaped.replace(regex, `<mark class="search-highlight">$1</mark>`);
}

async function performCsvSearch() {
  const inputEl = document.getElementById("csv-search-input");
  const query = inputEl.value.trim();
  if (!query) {
    alert("검색어를 입력하세요.");
    return;
  }
  const target = document.getElementById("csv-search-target").value;
  const panel = document.getElementById("csv-search-panel");
  const countEl = document.getElementById("csv-search-count");
  const bodyEl = document.getElementById("csv-search-results-body");
  const clearBtn = document.getElementById("btn-csv-search-clear");

  countEl.textContent = `"${query}" 검색 중...`;
  bodyEl.innerHTML = "";
  panel.classList.remove("hidden");
  clearBtn.classList.remove("hidden");

  try {
    const data = await api(
      "GET",
      `/api/csv/search?name=${encodeURIComponent(PROJECT_NAME)}&q=${encodeURIComponent(query)}&target=${encodeURIComponent(target)}`
    );

    const total = data.total || 0;
    const results = data.results || [];

    if (total === 0) {
      countEl.textContent = `검색 결과: 0건 ("${query}")`;
      bodyEl.innerHTML = `<tr><td colspan="6" style="text-align: center; color: #888; padding: 16px;">일치하는 대사를 찾을 수 없습니다.</td></tr>`;
      return;
    }

    countEl.textContent = `검색 결과: 총 ${total}건 ${total > results.length ? `(상위 ${results.length}건 표시)` : ""} ("${query}")`;

    for (const item of results) {
      const tr = document.createElement("tr");
      const transText = item.translation || (item.ai_draft ? `[초벌] ${item.ai_draft}` : "");
      tr.innerHTML = `
        <td><strong>${escapeHtml(item.file)}</strong></td>
        <td>${item.block}</td>
        <td>${escapeHtml(item.speaker || "-")}</td>
        <td>${highlightKeyword(item.source, query)}</td>
        <td>${highlightKeyword(transText, query)}</td>
        <td>
          <button type="button" class="btn-jump-file" data-file="${escapeHtml(item.file)}" data-block="${item.block}">
            이동 ➔
          </button>
        </td>
      `;
      bodyEl.appendChild(tr);
    }
  } catch (ex) {
    countEl.textContent = `검색 오류: ${ex.message}`;
  }
}

function clearCsvSearch() {
  document.getElementById("csv-search-input").value = "";
  document.getElementById("csv-search-panel").classList.add("hidden");
  document.getElementById("btn-csv-search-clear").classList.add("hidden");
  document.getElementById("csv-search-results-body").innerHTML = "";
}

function closeCsvSearchPanel() {
  document.getElementById("csv-search-panel").classList.add("hidden");
}

async function goToFileAndBlock(fname, blockNumber) {
  if (!confirmDiscardIfDirty()) return;

  let group = "system_common";
  if (fname.startsWith("dom1")) group = "dom1";
  else if (fname.startsWith("dom2")) group = "dom2";
  else if (fname.startsWith("dom3")) group = "dom3";

  state.csvGroup = group;
  document.querySelectorAll(".subtab-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.group === group);
  });

  renderFileSelect(fname);
  if (state.currentFile !== fname) {
    await loadFileRows(fname);
  }

  setTimeout(() => {
    const tr = document.querySelector(`#csv-table-body tr[data-block="${blockNumber}"]`);
    if (tr) {
      tr.scrollIntoView({ behavior: "smooth", block: "center" });
      tr.classList.remove("highlight-target-row");
      void tr.offsetWidth;
      tr.classList.add("highlight-target-row");
      const input = tr.querySelector(".translation-input");
      if (input) input.focus();
    }
  }, 100);
}

document.getElementById("btn-csv-search").addEventListener("click", performCsvSearch);
document.getElementById("csv-search-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") performCsvSearch();
});
document.getElementById("btn-csv-search-clear").addEventListener("click", clearCsvSearch);
document.getElementById("btn-csv-search-close").addEventListener("click", closeCsvSearchPanel);
document.getElementById("csv-search-results-body").addEventListener("click", (e) => {
  const btn = e.target.closest(".btn-jump-file");
  if (!btn) return;
  const file = btn.dataset.file;
  const block = Number(btn.dataset.block);
  goToFileAndBlock(file, block);
});

document.getElementById("btn-auto-translate").addEventListener("click", () => {
  if (!state.currentFile) return alert("파일이 선택되지 않았습니다.");
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
  const url = `/api/csv/translate-stream?name=${encodeURIComponent(PROJECT_NAME)}&fname=${encodeURIComponent(state.currentFile)}&engine=${encodeURIComponent(engine)}`;
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
  if (!fname) return;
  state.currentFile = fname;
  const rows = await api("GET", `/api/csv/file/${encodeURIComponent(fname)}?name=${encodeURIComponent(PROJECT_NAME)}`);
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
  if (!state.currentFile) return;
  const rowsEl = document.querySelectorAll("#csv-table-body tr");
  const edits = Array.from(rowsEl).map((tr) => ({
    block: Number(tr.dataset.block),
    translation: tr.querySelector(".translation-input").value,
  }));
  try {
    const result = await api(
      "POST",
      `/api/csv/file/${encodeURIComponent(state.currentFile)}?name=${encodeURIComponent(PROJECT_NAME)}`,
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
  try {
    const entries = await api(
      "GET",
      `/api/files/tree?name=${encodeURIComponent(PROJECT_NAME)}&dir=${encodeURIComponent(dir)}`
    );
    for (const e of entries) {
      const li = document.createElement("li");
      const nameSpan = document.createElement("span");
      nameSpan.textContent = e.type === "dir" ? `📁 ${e.name}` : `${e.isImage ? "🖼️" : "📄"} ${e.name}`;
      li.appendChild(nameSpan);

      if (e.hasPatch) {
        const tag = document.createElement("span");
        tag.className = "patch-tag";
        tag.textContent = "한글 패치";
        tag.title = `매칭 파일: ${e.patchRel}`;
        li.appendChild(tag);
      }

      li.addEventListener("click", () => {
        if (e.type === "dir") {
          loadTree(e.path);
        } else if (e.isImage) {
          previewImage(e.path, e.hasPatch, e.patchRel);
        } else {
          document.getElementById("image-preview-orig").textContent = `${e.name} (${e.size} bytes) - 미리보기 미지원 형식`;
          document.getElementById("image-preview-patch").textContent = "미리보기 미지원";
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

function previewImage(relPath, hasPatch = false, patchRel = "") {
  state.currentImagePath = relPath;

  // 1. 왼쪽: 원본 이미지 (ROM 언팩)
  const prevOrig = document.getElementById("image-preview-orig");
  prevOrig.innerHTML = "";
  const imgOrig = document.createElement("img");
  imgOrig.src = `/api/files/raw?name=${encodeURIComponent(PROJECT_NAME)}&path=${encodeURIComponent(relPath)}&type=orig&t=${Math.floor(performance.now())}`;
  prevOrig.appendChild(imgOrig);

  // 2. 오른쪽: image_patch 폴더의 한글 이미지
  const prevPatch = document.getElementById("image-preview-patch");
  const patchHeader = document.getElementById("image-patch-header");
  prevPatch.innerHTML = "";

  if (hasPatch || patchRel) {
    patchHeader.textContent = `✨ 한글 패치 이미지 (${patchRel || "image_patch"})`;
    const imgPatch = document.createElement("img");
    imgPatch.src = `/api/files/raw?name=${encodeURIComponent(PROJECT_NAME)}&path=${encodeURIComponent(relPath)}&type=patch&t=${Math.floor(performance.now())}`;
    imgPatch.onerror = () => {
      prevPatch.textContent = "패치 이미지 로드 실패";
    };
    prevPatch.appendChild(imgPatch);
  } else {
    patchHeader.textContent = "✨ 한글 패치 이미지 (image_patch)";
    prevPatch.innerHTML = '<span style="color: #888; font-size: 13px;">image_patch 폴더에 매칭되는 PNG가 없습니다</span>';
  }
}

// ---- 탭 4: 빌드 ----
document.getElementById("btn-reinsert").addEventListener("click", async () => {
  const box = document.getElementById("reinsert-result");
  box.textContent = "재삽입 중...";
  try {
    const result = await api("POST", "/api/build/reinsert", { name: PROJECT_NAME });
    box.textContent = JSON.stringify(result, null, 2);
  } catch (ex) {
    box.textContent = `오류: ${ex.message}`;
  }
});

document.getElementById("btn-pack").addEventListener("click", async () => {
  const box = document.getElementById("pack-result");
  const link = document.getElementById("download-link");
  link.classList.add("hidden");
  box.textContent = "빌드 중...";
  try {
    const result = await api("POST", "/api/build/pack", { name: PROJECT_NAME });
    box.textContent = JSON.stringify(result, null, 2);
    link.href = `/api/build/download?name=${encodeURIComponent(PROJECT_NAME)}`;
    link.classList.remove("hidden");
  } catch (ex) {
    box.textContent = `오류: ${ex.message}`;
  }
});

// ---- 초기화 ----
refreshStatus();
refreshFileList();
loadTree("");
updateCsvDownloadLink();
updateCsvDownloadLink();
