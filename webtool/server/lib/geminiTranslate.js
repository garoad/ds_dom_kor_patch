"use strict";

/**
 * Gemini API translation module for Days of Memories retro NDS scripts.
 * Calls Gemini REST API with chunking & rate-limit throttling.
 * Preserves all control tags (<485C>, <6E5C>, <이름>, <0087> etc.) exactly as is.
 */

async function translateChunk(items, apiKey, modelName) {
  const promptText = `
You are translating Japanese dialogue from the SNK NDS game 'Days of Memories' into natural Korean.

CRITICAL RULES:
1. Preserve ALL control codes and tags EXACTLY as they appear (e.g. <485C>, <6E5C>, <0087>, <이름>, <이름:3131>, <이름:3232>). DO NOT remove, alter, or translate any part of tags inside angle brackets <...>.
2. Keep the Korean translation concise and natural for retro game dialogue boxes.
3. Respond ONLY with a valid JSON array of strings, matching the order of input items exactly.

Input Japanese items to translate:
${JSON.stringify(items, null, 2)}
`;

  const url = `https://generativelanguage.googleapis.com/v1beta/models/${modelName}:generateContent?key=${encodeURIComponent(apiKey)}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      contents: [{ parts: [{ text: promptText }] }],
      generationConfig: {
        responseMimeType: "application/json",
        temperature: 0.2,
      },
    }),
  });

  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    const errMsg = errBody.error && errBody.error.message ? errBody.error.message : `HTTP ${res.status}`;
    const err = new Error(`Gemini API (${modelName}) 호출 실패: ${errMsg}`);
    err.status = res.status;
    err.errMsg = errMsg;
    throw err;
  }

  const data = await res.json();
  const rawText = data.candidates && data.candidates[0] && data.candidates[0].content && data.candidates[0].content.parts[0].text;
  if (!rawText) throw new Error("Gemini API 응답 데이터가 올바르지 않습니다.");

  let parsed;
  try {
    parsed = JSON.parse(rawText);
  } catch (e) {
    throw new Error(`Gemini 응답 JSON 파싱 실패: ${rawText}`);
  }

  if (!Array.isArray(parsed) || parsed.length !== items.length) {
    throw new Error(`Gemini 청크 번역 개수 불일치 (요청 ${items.length}개, 응답 ${parsed ? parsed.length : 0}개)`);
  }
  return parsed;
}

async function translateChunkWithRetry(items, apiKey, modelName, onProgress, maxRetries = 8) {
  let attempt = 0;
  while (true) {
    try {
      return await translateChunk(items, apiKey, modelName);
    } catch (err) {
      attempt += 1;
      const isQuotaError =
        err.status === 429 ||
        (err.message && (err.message.includes("Quota exceeded") || err.message.includes("rate-limits")));

      if (isQuotaError && attempt <= maxRetries) {
        let retrySeconds = 15;
        const m = /retry in ([\d\.]+)s/i.exec(err.message || "");
        if (m) {
          retrySeconds = Math.ceil(parseFloat(m[1])) + 2;
        } else {
          retrySeconds = Math.min(60, attempt * 10);
        }

        const msg = `⏳ 쿼터 제한(429) 대기 중: 구글 요청 대기 ${retrySeconds}초 후 자동 재시도합니다 (시도 ${attempt}/${maxRetries})...`;
        console.log(msg);
        if (onProgress) onProgress(msg);
        await new Promise((resolve) => setTimeout(resolve, retrySeconds * 1000));
        continue;
      }
      throw err;
    }
  }
}

async function translateBatch(items, apiKey, model = "gemini-2.0-flash", onProgress = null) {
  if (!apiKey) {
    throw new Error("Gemini API Key가 설정되지 않았습니다. UI 상단 또는 .env 파일에 키를 등록하세요.");
  }

  const CHUNK_SIZE = 15;
  const results = [];
  const totalChunks = Math.ceil(items.length / CHUNK_SIZE);

  for (let i = 0; i < items.length; i += CHUNK_SIZE) {
    const chunkIndex = Math.floor(i / CHUNK_SIZE) + 1;
    const chunk = items.slice(i, i + CHUNK_SIZE);

    if (i > 0) {
      const waitMsg = `⏳ API Rate Limit 방지를 위해 3초 대기 중 (${chunkIndex}/${totalChunks} 청크 준비)...`;
      if (onProgress) onProgress(waitMsg);
      await new Promise((resolve) => setTimeout(resolve, 3000));
    }

    const progressMsg = `🔄 AI 번역 진행 중: ${chunkIndex}/${totalChunks} 청크 (${Math.min(i + CHUNK_SIZE, items.length)}/${items.length} 행 완료)...`;
    if (onProgress) onProgress(progressMsg);

    const chunkResults = await translateChunkWithRetry(chunk, apiKey, model, onProgress);
    results.push(...chunkResults);
  }

  return results;
}

module.exports = { translateBatch };
