// === メニュー作成 ===
function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu('BoatRace AI')
    .addItem('1. 分析用プロンプト作成 (Daily)', 'generateDailyPrompts')
    .addItem('2. 選手成績DB更新 (Full)', 'updateRacerStats')
    .addItem('3. AI予想を実行 (Gemini)', 'predictRaceOutcomes')
    .addSeparator()
    .addItem('4. 自身の予想を振り返る (Review)', 'runReviewCycle')
    .addItem('5. 完了分をアーカイブ (Archive)', 'archivePredictions') // 新機能
    .addSeparator()
    .addItem('※ 接続＆モデル診断', 'diagnoseConnection')
    .addToUi();
}

// ★★★ 新しいAPIキー (修正済み) ★★★
const API_KEY = "AIzaSyBpeIL65BP0cqup47_1A2HHIUVxYbc91SE";

// 使用するモデル (2026年最新)
let MODEL_NAME = "gemini-2.5-pro";

// === 診断機能 ===
function diagnoseConnection() {
  Logger.log("=== 診断開始 ===");
  const url = `https://generativelanguage.googleapis.com/v1beta/models?key=${API_KEY}`;
  try {
    const response = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    const json = JSON.parse(response.getContentText());
    if (json.error) {
       Browser.msgBox("❌ 接続失敗: " + json.error.message);
       return;
    }
    const availableModels = json.models.map(m => m.name.replace("models/", ""));
    const preferred = ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-pro"];
    let found = "";
    for (const p of preferred) {
      if (availableModels.includes(p)) { found = p; break; }
    }
    if (found) {
      PropertiesService.getScriptProperties().setProperty("VALID_MODEL", found);
      Browser.msgBox(`✅ 診断成功！モデル: ${found}`);
    } else {
      Browser.msgBox(`⚠️ 推奨モデルなし。利用可能: ${availableModels.join(",")}`);
    }
  } catch (e) {
    Browser.msgBox("❌ 通信エラー: " + e.toString());
  }
}

// === Phase 6: AI用プロンプト作成 (当日以降のみ) + 学習機能 ===
function generateDailyPrompts() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const dataSheet = ss.getSheetByName("features_daily") || ss.getSheetByName("Sheet1");
  const outputSheetName = "AI_Analysis";
  
  if (!dataSheet) { Browser.msgBox("エラー: features_dailyが見つかりません。"); return; }
  
  let outputSheet = ss.getSheetByName(outputSheetName);
  if (!outputSheet) {
    outputSheet = ss.insertSheet(outputSheetName);
    outputSheet.appendRow(["RaceID", "Venue", "RaceNo", "Analysis Prompt", "AI Response", "Review Status"]); // 列追加
    outputSheet.getRange("D:E").setWrap(true);
  }

  // ★学習内容を取得★
  const lessons = getRecentLessons(ss);
  const learningContext = lessons.length > 0 
    ? `\n\n【重要：過去の反省点（これを踏まえて予想すること）】\n${lessons.join("\n")}\n`
    : "";

  const lastRow = dataSheet.getLastRow();
  if (lastRow < 2) return;
  
  const data = dataSheet.getRange(2, 1, lastRow - 1, 12).getValues();
  const today = new Date();
  today.setHours(0, 0, 0, 0); 

  const races = {};
  data.forEach(row => {
    const raceDate = new Date(row[0]); 
    if (raceDate < today) return; 

    const raceId = row[3];
    const venue = row[1];
    const raceNo = row[2];
    const promptPart = row[11];
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
    
    // プロンプトに学習内容を含める
    const fullPrompt = `以下のボートレースデータから、レース展開と推奨買い目を予想してください。` +
                       learningContext + 
                       `\n\n開催地: ${info.venue} 第${info.raceNo}レース\n` +
                       `出走表:\n` + info.details.join("\n");
                       
    outputRows.push([id, info.venue, info.raceNo, fullPrompt, "", ""]);
  }
  
  if (outputRows.length > 0) {
    outputSheet.getRange(outputSheet.getLastRow() + 1, 1, outputRows.length, 6).setValues(outputRows);
    Logger.log(`${outputRows.length} 件の新規プロンプトを作成しました。`);
  }
}

// === 新機能: 反省と学習 (Run Review Cycle) ===
function runReviewCycle() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const analysisSheet = ss.getSheetByName("AI_Analysis");
  const resultSheet = ss.getSheetByName("history_results");
  const lessonSheetName = "AI_Lessons";
  
  if (!analysisSheet || !resultSheet) return;

  // 教訓シート作成
  let lessonSheet = ss.getSheetByName(lessonSheetName);
  if (!lessonSheet) {
    lessonSheet = ss.insertSheet(lessonSheetName);
    lessonSheet.appendRow(["Date", "RaceID", "Reflection & Lesson"]);
    lessonSheet.setColumnWidth(3, 400);
  }

  // 結果データのマップ化
  const results = {};
  const resData = resultSheet.getRange(2, 1, resultSheet.getLastRow()-1, 6).getValues(); // A-F
  resData.forEach(row => {
    const rid = String(row[3]); // RaceID
    const result = row[4]; // Result (e.g. 1-2-3)
    const payout = row[5];
    if (rid && result) results[rid] = { result: result, payout: payout };
  });

  // AI予想の確認
  const anaData = analysisSheet.getDataRange().getValues();
  // 予想データの構造: [RaceID, Venue, RaceNo, Prompt, Response, ReviewStatus]
  // ReviewStatus(F列/Index 5)が空ならレビュー対象
  
  let reviewCount = 0;
  
  for (let i = 1; i < anaData.length; i++) {
    const row = anaData[i];
    const rid = String(row[0]);
    const aiResponse = row[4];
    const status = row[5];
    
    // 既にレビュー済み、または予想が無い、または結果がまだ無い場合はスキップ
    if (status === "Reviewed" || !aiResponse || !results[rid]) continue;
    
    // ここで反省会を実施
    const actual = results[rid];
    const reflectionPrompt = `
あなたはボートレース予測AIです。過去に行った以下の予測と、実際の結果を比較して「反省会」を行ってください。

【あなたの予測】
${aiResponse.substring(0, 1000)}... (省略)

【実際の結果】
決着: ${actual.result}
配当: ${actual.payout}円

【タスク】
1. 予想は当たりましたか？外れましたか？
2. 外れた場合、何を見落としていましたか？（例：風の影響、展示タイムの過信、特定選手の不調など）
3. **次回への簡潔な教訓**を1行でまとめてください。
形式: 「教訓：〜」
`;

    try {
      const lesson = callGemini(reflectionPrompt, API_KEY, MODEL_NAME);
      
      // 教訓を保存
      lessonSheet.appendRow([new Date(), rid, lesson]);
      
      // ステータス更新
      analysisSheet.getRange(i + 1, 6).setValue("Reviewed");
      
      reviewCount++;
      Utilities.sleep(2000); // レート制限対策
      if (reviewCount >= 10) break; // 一度にやりすぎないように10件で止める
      
    } catch (e) {
      Logger.log(`Review Error ${rid}: ${e.message}`);
    }
  }
  
  if (reviewCount > 0) {
    Browser.msgBox(`${reviewCount} 件のレースを振り返り、教訓を記録しました！`);
  } else {
    Logger.log("振り返るべき新しいレース結果はまだありません。");
  }
}

// 過去の教訓を取得するヘルパー関数
function getRecentLessons(ss) {
  const lessonSheet = ss.getSheetByName("AI_Lessons");
  if (!lessonSheet || lessonSheet.getLastRow() < 2) return [];
  
  // 最新の5件を取得
  const startRow = Math.max(2, lessonSheet.getLastRow() - 4);
  const numRows = lessonSheet.getLastRow() - startRow + 1;
  const data = lessonSheet.getRange(startRow, 3, numRows, 1).getValues();
  
  return data.map(r => r[0]).filter(t => t.includes("教訓")); // "教訓"を含む行だけ抽出
}

// === Phase 5: 選手成績DB更新 (変更なし) ===
function updateRacerStats() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const rawSheet = ss.getSheetByName("features_daily") || ss.getSheetByName("Sheet1");
  const resultSheet = ss.getSheetByName("history_results");
  const dbSheetName = "racer_db";
  let dbSheet = ss.getSheetByName(dbSheetName);
  if (!rawSheet || !resultSheet) return;
  const rawData = rawSheet.getRange(2, 1, rawSheet.getLastRow()-1, 7).getValues();
  const histData = resultSheet.getRange(2, 1, resultSheet.getLastRow()-1, 5).getDisplayValues();
  const resultMap = {};
  histData.forEach(row => {
    const rid = String(row[3]); 
    let resultStr = String(row[4]); 
    if (rid && (resultStr.includes("-") || resultStr.includes("/"))) resultMap[rid] = resultStr;
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
    output.push([pid, s.name, s.runs, s.w1, s.w2, s.w3, s.w1/s.runs, (s.w1+s.w2)/s.runs, (s.w1+s.w2+s.w3)/s.runs]);
  }
  if (output.length > 0) {
    if (!dbSheet) dbSheet = ss.insertSheet(dbSheetName);
    if (dbSheet.getLastRow() > 1) dbSheet.getRange(2, 1, dbSheet.getLastRow()-1, 9).clearContent();
    dbSheet.getRange(2, 1, output.length, 9).setValues(output);
    dbSheet.getRange(2, 7, output.length, 3).setNumberFormat("0.0%"); 
  }
}

// === Phase 6: AI予想実行 (Gemini) ===
function predictRaceOutcomes() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const analysisSheet = ss.getSheetByName("AI_Analysis");
  if (!analysisSheet) { Browser.msgBox("エラー: 'AI_Analysis' シートが見つかりません。"); return; }
  
  const savedModel = PropertiesService.getScriptProperties().getProperty("VALID_MODEL");
  const modelToUse = savedModel || MODEL_NAME;
  
  const lastRow = analysisSheet.getLastRow();
  if (lastRow < 2) { Browser.msgBox("エラー: データがありません。"); return; }

  const range = analysisSheet.getRange(2, 1, lastRow - 1, 5);
  const data = range.getValues();
  let processedCount = 0;
  
  Logger.log(`処理開始: 全${data.length}件. 使用モデル: ${modelToUse}`);
  const MAX_BATCH = 30; // 制限回避のため少し減らす
  let currentBatch = 0;

  for (let i = 0; i < data.length; i++) {
    if (currentBatch >= MAX_BATCH) { Logger.log("バッチ上限"); break; }

    const prompt = data[i][3];
    const existingResponse = data[i][4];
    
    if (!prompt) continue;
    if (existingResponse !== "" && !String(existingResponse).startsWith("Error")) continue;
    
    try {
      const response = callGemini(prompt, API_KEY, modelToUse);
      analysisSheet.getRange(i + 2, 5).setValue(response);
      SpreadsheetApp.flush();
      Utilities.sleep(2000); 
      processedCount++;
      currentBatch++;
    } catch (e) {
      const errorMsg = "Error: " + e.toString();
      analysisSheet.getRange(i + 2, 5).setValue(errorMsg);
      Logger.log(`Row ${i+2} Failed: ${errorMsg}`);
    }
  }
  Browser.msgBox(`完了: ${processedCount} 件の予想を更新しました(モデル:${modelToUse})`);
}

// === Gemini呼び出し (8000トークン対応) ===
function callGemini(prompt, apiKey, modelName) {
  if (!apiKey) throw new Error("API Key is missing");
  const model = modelName || "gemini-2.5-pro";
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey.trim()}`;
  
  const payload = {
    "contents": [{"parts": [{"text": prompt}]}],
    "generationConfig": { 
      "temperature": 0.7, 
      "maxOutputTokens": 8000 // ★ここを8000に増量！
    }
  };
  
  const options = {
    "method": "post",
    "contentType": "application/json",
    "payload": JSON.stringify(payload),
    "muteHttpExceptions": true
  };

  const response = UrlFetchApp.fetch(url, options);
  const json = JSON.parse(response.getContentText());
  
  if (json.error) throw new Error(json.error.message);
  return json.candidates[0].content.parts[0].text;
}

// === 新機能: 完了分をアーカイブ ===
function archivePredictions() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const analysisSheet = ss.getSheetByName("AI_Analysis");
  const archiveSheetName = "AI_Archive";
  
  if (!analysisSheet) {
    Browser.msgBox("エラー: AI_Analysisシートが見つかりません。");
    return;
  }
  
  // アーカイブシート作成（なければ）
  let archiveSheet = ss.getSheetByName(archiveSheetName);
  if (!archiveSheet) {
    archiveSheet = ss.insertSheet(archiveSheetName);
    archiveSheet.appendRow(["RaceID", "Venue", "RaceNo", "Prompt", "AI Response", "Review Status", "Archived Date"]);
    archiveSheet.getRange("D:E").setWrap(true);
  }
  
  const data = analysisSheet.getDataRange().getValues();
  const header = data[0];
  
  // Reviewed の行を抽出
  const rowsToArchive = [];
  const rowIndicesToDelete = [];
  
  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    const status = row[5]; // F列 (Review Status)
    const response = row[4]; // E列 (AI Response)
    
    // Reviewed済み、または正常な予測がある行をアーカイブ対象に
    if (status === "Reviewed" || (response && !String(response).startsWith("Error"))) {
      // 行データをコピー
      let archivedRow = [...row];
      
      // 長さを6列（A-F）に揃える（足りない場合は空文字追加）
      while (archivedRow.length < 6) {
        archivedRow.push("");
      }
      
      // 7列目（G列）にアーカイブ日時を追加
      if (archivedRow.length < 7) {
        archivedRow.push(new Date());
      } else {
        archivedRow[6] = new Date(); // 既に7列以上ある場合は上書き
        // 8列以上ある場合は削除して7列にする
        archivedRow = archivedRow.slice(0, 7);
      }
      
      rowsToArchive.push(archivedRow);
      rowIndicesToDelete.push(i + 1); // 1-indexed for sheet
    }
  }
  
  if (rowsToArchive.length === 0) {
    Browser.msgBox("アーカイブ対象の行がありません。\n（振り返り済み or 予測完了の行が対象です）");
    return;
  }
  
  // アーカイブシートに追加
  archiveSheet.getRange(
    archiveSheet.getLastRow() + 1, 
    1, 
    rowsToArchive.length, 
    7
  ).setValues(rowsToArchive);
  
  // 元シートから削除（下から削除）
  rowIndicesToDelete.reverse().forEach(rowIndex => {
    analysisSheet.deleteRow(rowIndex);
  });
  
  Browser.msgBox(`✅ ${rowsToArchive.length} 件をアーカイブしました！\n\nAI_Analysisは未処理分だけになりました。`);
}
