// === メニュー作成 ===
function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu('BoatRace AI')
    .addItem('1. 分析用プロンプト作成 (Daily)', 'generateDailyPrompts')
    .addItem('2. 選手成績DB更新 (Full)', 'updateRacerStats')
    .addItem('3. AI予想を実行 (Gemini)', 'predictRaceOutcomes')
    .addSeparator()
    .addItem('※ 接続＆モデル診断 (まずこれを実行)', 'diagnoseConnection')
    .addToUi();
}

// ★★★ 新しいAPIキー (修正済み) ★★★
const API_KEY = "AIzaSyBpeIL65BP0cqup47_1A2HHIUVxYbc91SE";

// 使用するモデル (診断機能で確認後に書き換える可能性あり)
// 候補: "gemini-1.5-flash", "gemini-1.5-flash-latest", "gemini-pro"
let MODEL_NAME = "gemini-1.5-flash";

// === 診断機能: 使えるモデルを探す ===
function diagnoseConnection() {
  Logger.log("=== 診断開始 ===");
  const url = `https://generativelanguage.googleapis.com/v1beta/models?key=${API_KEY}`;

  try {
    const response = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    const json = JSON.parse(response.getContentText());

    if (json.error) {
      Browser.msgBox("❌ 接続失敗: " + json.error.message);
      Logger.log("Error: " + JSON.stringify(json.error));
      return;
    }

    if (!json.models) {
      Browser.msgBox("⚠️ モデル一覧が取得できませんでした。");
      return;
    }

    Logger.log("=== 利用可能なモデル一覧 ===");
    const availableModels = json.models.map(m => m.name.replace("models/", ""));
    Logger.log(availableModels.join("\n"));

    // 優先順位で使えるモデルを探す
    const preferred = ["gemini-1.5-flash", "gemini-1.5-flash-001", "gemini-1.5-pro", "gemini-pro"];
    let found = "";

    for (const p of preferred) {
      if (availableModels.includes(p)) {
        found = p;
        break;
      }
    }

    if (found) {
      // 実際に見つかったモデルでテスト送信
      try {
        const testRes = callGemini("テスト", API_KEY, found);
        Browser.msgBox(`✅ 診断成功！\nこのキーで使える最適なモデルは: 「${found}」です。\n\nテスト回答: ${testRes}\n\n※このままAI予想を実行してください。自動的にこのモデルが使われます。`);
        // プロパティストアに保存して他の関数でも使えるようにする
        PropertiesService.getScriptProperties().setProperty("VALID_MODEL", found);
      } catch (e) {
        Browser.msgBox("⚠️ モデルは見つかりましたがテスト送信に失敗しました。\n" + e.toString());
      }
    } else {
      Browser.msgBox(`⚠️ 推奨モデルが見つかりません。\n利用可能なモデル:\n${availableModels.join("\n")}`);
    }

  } catch (e) {
    Browser.msgBox("❌ 通信エラー: " + e.toString());
  }
}

// === Phase 6: AI用プロンプト作成 (当日以降のみ) ===
function generateDailyPrompts() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  // シート名を 'features_daily' 優先に変更
  const dataSheet = ss.getSheetByName("features_daily") || ss.getSheetByName("Sheet1") || ss.getSheetByName("シート1");
  const outputSheetName = "AI_Analysis";

  if (!dataSheet) {
    Browser.msgBox("エラー: データシート(features_daily)が見つかりません。");
    return;
  }

  let outputSheet = ss.getSheetByName(outputSheetName);
  if (!outputSheet) {
    outputSheet = ss.insertSheet(outputSheetName);
    outputSheet.appendRow(["RaceID", "Venue", "RaceNo", "Analysis Prompt", "AI Response"]);
    outputSheet.getRange("D:D").setWrap(true);
    outputSheet.getRange("E:E").setWrap(true);
  }
  const lastRow = dataSheet.getLastRow();
  if (lastRow < 2) return;

  // L列(12)まで取得。風情報がL列の文字列に含まれている前提。
  const data = dataSheet.getRange(2, 1, lastRow - 1, 12).getValues();
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const races = {};
  data.forEach(row => {
    // 日付フィルタ: 過去のレースは無視
    const raceDate = new Date(row[0]);
    if (raceDate < today) return;

    const raceId = row[3];
    const venue = row[1];
    const raceNo = row[2];
    const promptPart = row[11]; // L列 (ここに '展6.8, 風2m' などが含まれていればOK)
    if (!raceId) return;
    if (!races[raceId]) {
      races[raceId] = { venue: venue, raceNo: raceNo, details: [] };
    }
    races[raceId].details.push(promptPart);
  });

  const outputRows = [];
  const existingData = outputSheet.getDataRange().getValues();
  const processedIds = new Set();
  for (let i = 1; i < existingData.length; i++) {
    processedIds.add(String(existingData[i][0]));
  }

  for (const [id, info] of Object.entries(races)) {
    if (processedIds.has(String(id))) continue;
    const fullPrompt = `以下のボートレースデータから、レース展開と推奨買い目を予想してください。\n` +
      `開催地: ${info.venue} 第${info.raceNo}レース\n` +
      `出走表:\n` + info.details.join("\n");
    outputRows.push([id, info.venue, info.raceNo, fullPrompt, ""]);
  }

  if (outputRows.length > 0) {
    outputSheet.getRange(outputSheet.getLastRow() + 1, 1, outputRows.length, 5).setValues(outputRows);
    Logger.log(`${outputRows.length} 件の新規プロンプトを作成しました。`);
  } else {
    Logger.log("新規プロンプトはありません。");
  }
}

// === Phase 5: 選手成績DB更新 ===
function updateRacerStats() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  // シート名を 'features_daily' 優先に変更
  const rawSheet = ss.getSheetByName("features_daily") || ss.getSheetByName("Sheet1") || ss.getSheetByName("シート1");
  const resultSheet = ss.getSheetByName("history_results");
  const dbSheetName = "racer_db";

  let dbSheet = ss.getSheetByName(dbSheetName);
  if (!rawSheet || !resultSheet) return;

  const rawData = rawSheet.getRange(2, 1, rawSheet.getLastRow() - 1, 7).getValues();
  const histData = resultSheet.getRange(2, 1, resultSheet.getLastRow() - 1, 5).getDisplayValues();

  const resultMap = {};
  histData.forEach(row => {
    const rid = String(row[3]);
    let resultStr = String(row[4]);
    if (rid && (resultStr.includes("-") || resultStr.includes("/"))) {
      resultMap[rid] = resultStr;
    }
  });

  const stats = {};
  rawData.forEach(row => {
    const rid = String(row[3]);
    const lane = row[4];
    const pid = row[5];
    const name = row[6];
    if (!pid || !resultMap[rid]) return;
    if (!stats[pid]) stats[pid] = { name: name, runs: 0, w1: 0, w2: 0, w3: 0 };
    stats[pid].runs++;
    const nums = resultMap[rid].match(/\d+/g);
    if (nums && nums.length >= 3) {
      if (parseInt(nums[0]) == lane) stats[pid].w1++;
      if (parseInt(nums[1]) == lane) stats[pid].w2++;
      if (parseInt(nums[2]) == lane) stats[pid].w3++;
    }
  });

  const output = [];
  for (const pid in stats) {
    const s = stats[pid];
    output.push([pid, s.name, s.runs, s.w1, s.w2, s.w3, s.w1 / s.runs, (s.w1 + s.w2) / s.runs, (s.w1 + s.w2 + s.w3) / s.runs]);
  }

  if (output.length > 0) {
    if (!dbSheet) dbSheet = ss.insertSheet(dbSheetName);
    if (dbSheet.getLastRow() > 1) dbSheet.getRange(2, 1, dbSheet.getLastRow() - 1, 9).clearContent();
    dbSheet.getRange(2, 1, output.length, 9).setValues(output);
    dbSheet.getRange(2, 7, output.length, 3).setNumberFormat("0.0%");
  }
}

// === Phase 6: AI予想実行 (Gemini) ===
function predictRaceOutcomes() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const analysisSheet = ss.getSheetByName("AI_Analysis");
  if (!analysisSheet) {
    Browser.msgBox("エラー: 'AI_Analysis' シートが見つかりません。");
    return;
  }

  // 診断済みのモデルがあればそれを使う
  const savedModel = PropertiesService.getScriptProperties().getProperty("VALID_MODEL");
  const modelToUse = savedModel || MODEL_NAME;

  const lastRow = analysisSheet.getLastRow();
  if (lastRow < 2) {
    Browser.msgBox("エラー: データがありません。");
    return;
  }

  const range = analysisSheet.getRange(2, 1, lastRow - 1, 5);
  const data = range.getValues();
  let processedCount = 0;

  Logger.log(`処理開始: 全${data.length}件. 使用モデル: ${modelToUse}`);

  // 最大50件ずつ処理（制限回避のため）
  const MAX_BATCH = 50;
  let currentBatch = 0;

  for (let i = 0; i < data.length; i++) {
    // 処理数が多すぎたら一度止める
    if (currentBatch >= MAX_BATCH) {
      Logger.log("バッチ上限に達したため一時停止します。");
      break;
    }

    const prompt = data[i][3];
    const existingResponse = data[i][4];

    if (!prompt) continue;
    // 成功（文字が入っている）ならスキップ（API節約）
    // ※ エラーだった場合は再実行したいのでスキップしない
    if (existingResponse !== "" && !String(existingResponse).startsWith("Error")) continue;

    try {
      const response = callGemini(prompt, API_KEY, modelToUse);
      analysisSheet.getRange(i + 2, 5).setValue(response);

      // リアルタイム更新のために頻繁にflush
      SpreadsheetApp.flush();

      // Rate Limit対策 (2秒待機)
      Utilities.sleep(2000);
      processedCount++;
      currentBatch++;
    } catch (e) {
      const errorMsg = "Error: " + e.toString();
      analysisSheet.getRange(i + 2, 5).setValue(errorMsg);
      Logger.log(`Row ${i + 2} Failed: ${errorMsg}`);
    }
  }
  Browser.msgBox(`完了: ${processedCount} 件の予想を更新しました(使用モデル:${modelToUse})`);
}

// === Gemini呼び出し共通関数 (ログ機能強化) ===
function callGemini(prompt, apiKey, modelName) {
  if (!apiKey) throw new Error("API Key is missing (キーが設定されていません)");

  // User confirmed gemini-2.5-flash works
  // モデル名が渡されていなければデフォルト
  const model = modelName || "gemini-2.5-flash";
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey.trim()}`;

  const payload = {
    "contents": [{ "parts": [{ "text": prompt }] }],
    "generationConfig": { "temperature": 0.7, "maxOutputTokens": 2000 } // トークン数を増加
  };

  const options = {
    "method": "post",
    "contentType": "application/json",
    "payload": JSON.stringify(payload),
    "muteHttpExceptions": true
  };

  const response = UrlFetchApp.fetch(url, options);
  const contentText = response.getContentText();
  const json = JSON.parse(contentText);

  if (json.error) {
    throw new Error(json.error.message);
  }
  return json.candidates[0].content.parts[0].text;
}
