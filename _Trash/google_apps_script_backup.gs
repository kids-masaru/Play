function buildDailyAIPrompt() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const featureSheet = ss.getSheetByName("features_daily");
  const promptSheet = ss.getSheetByName("ai_prompt_daily");

  const today = Utilities.formatDate(new Date(), "Asia/Tokyo", "yyyy-MM-dd");
  const data = featureSheet.getDataRange().getValues();
  const header = data[0];

  const todayRows = data.filter((row, i) =>
    i > 0 && Utilities.formatDate(new Date(row[0]), "Asia/Tokyo", "yyyy-MM-dd") === today
  );

  if (todayRows.length === 0) return;

  let text = `あなたはボートレースの予想を行うAIではありません。
あなたの役割は「判断支援」です。

以下は本日のレースデータです。\n\n`;

  todayRows.forEach(row => {
    header.forEach((col, i) => {
      text += `${col}: ${row[i]}\n`;
    });
    text += `\n---\n\n`;
  });

  promptSheet.clear();
  promptSheet.getRange(1,1).setValue(text);
}
