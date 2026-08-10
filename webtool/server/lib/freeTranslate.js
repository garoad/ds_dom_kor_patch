"use strict";

/**
 * Free Translation engine bridge module (Google/macOS Translate engine based)
 * Preserves all control tags (<485C>, <6E5C>, <이름>, <0087> etc.) exactly as is.
 */

const http = require("https");

function translateSingle(text, fromLang = "ja", toLang = "ko") {
  return new Promise((resolve, reject) => {
    if (!text || !text.trim()) {
      return resolve(text);
    }

    const encoded = encodeURIComponent(text);
    const url = `https://translate.googleapis.com/translate_a/single?client=gtx&sl=${fromLang}&tl=${toLang}&dt=t&q=${encoded}`;

    const options = {
      headers: {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"
      },
      timeout: 10000
    };

    const req = http.get(url, options, (res) => {
      let body = "";
      res.on("data", (chunk) => (body += chunk));
      res.on("end", () => {
        try {
          if (res.statusCode !== 200) {
            return reject(new Error(`Translate API HTTP ${res.statusCode}`));
          }
          const parsed = JSON.parse(body);
          if (parsed && parsed[0]) {
            const result = parsed[0].map((item) => item[0] || "").join("");
            resolve(result);
          } else {
            resolve(text);
          }
        } catch (err) {
          reject(err);
        }
      });
    });

    req.on("error", (err) => reject(err));
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("Translate API request timed out"));
    });
  });
}

async function translateBatch(items, apiKey, modelName, onProgress) {
  const results = [];
  const total = items.length;

  for (let i = 0; i < total; i++) {
    const src = items[i];
    try {
      const trans = await translateSingle(src, "ja", "ko");
      results.push(trans);
    } catch (e) {
      // Fallback to original text on failure
      results.push(src);
    }

    if (onProgress && (i % 5 === 0 || i === total - 1)) {
      onProgress(`초벌번역 진행 중... (${i + 1}/${total})`);
    }

    // Gentle throttling to avoid rate limiting
    await new Promise((resolve) => setTimeout(resolve, 150));
  }

  return results;
}

module.exports = {
  translateSingle,
  translateBatch,
};
