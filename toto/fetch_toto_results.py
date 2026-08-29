"""toto公式結果ページから確定結果と当せん金を自動取得する。

ローカルに保存済みの round_*.json を対象に、公式結果ページが公開された回だけを
official_results.json へ追記する。取得に失敗した回があっても既存データは保持する。
"""
import glob
import io
import json
import os
import re
import sys

import pandas as pd
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
OUT_JSON = os.path.join(DATA_DIR, "official_results.json")
RESULT_URL = (
    "https://store.toto-dream.com/dcs/subos/screen/pi04/spin011/"
    "PGSPIN01101LnkHoldCntLotResultLsttoto.form?holdCntId={round_no}"
)
HEADERS = {"User-Agent": "Mozilla/5.0 (Play toto result fetcher)"}
KUJI_ORDER = ["toto", "mini_a", "mini_b", "goal3"]
PICK_MAP = {"1": "H", "0": "D", "2": "A"}


def load_json(path, fallback):
    if not os.path.exists(path):
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return fallback


def fetch_html(round_no):
    response = requests.get(RESULT_URL.format(round_no=round_no), headers=HEADERS, timeout=30)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def flatten_columns(table):
    """pandasのMultiIndex見出しを、末尾の有効な文字列へ平坦化する。"""
    columns = []
    for column in table.columns:
        parts = column if isinstance(column, tuple) else (column,)
        text_parts = [str(part).strip() for part in parts if str(part).strip() and "Unnamed" not in str(part)]
        columns.append(text_parts[-1] if text_parts else "")
    copy = table.copy()
    copy.columns = columns
    return copy


def parse_int(value):
    match = re.search(r"([\d,]+)", str(value))
    return int(match.group(1).replace(",", "")) if match else None


def parse_result_table(table):
    table = flatten_columns(table)
    result_columns = [column for column in table.columns if "くじ結果" in column]
    if not result_columns:
        return None
    values = []
    for value in table[result_columns[-1]].tolist():
        pick = str(value).strip()
        if pick in PICK_MAP:
            values.append(PICK_MAP[pick])
    return values or None


def parse_payout_table(table):
    """当せん金テーブルを1等金額と等級別明細へ変換する。"""
    table = flatten_columns(table)
    amount_row = None
    count_row = None
    for _, row in table.iterrows():
        values = [str(value).strip() for value in row.tolist()]
        if any(value == "当せん金" for value in values):
            amount_row = row
        if any(value == "当せん口数" for value in values):
            count_row = row
    if amount_row is None:
        return None

    details = []
    for index, column in enumerate(table.columns):
        rank_match = re.search(r"([123])等", str(column))
        if not rank_match:
            continue
        amount = parse_int(amount_row.iloc[index])
        count = parse_int(count_row.iloc[index]) if count_row is not None else None
        if amount is not None:
            details.append({"rank": f"{rank_match.group(1)}等", "amount": amount, "count": count})
    if not details:
        # 見出しが表の先頭行として読み込まれた場合に備え、当せん金行を左から等級順に読む。
        amounts = [parse_int(value) for value in amount_row.tolist()[1:]]
        counts = [parse_int(value) for value in count_row.tolist()[1:]] if count_row is not None else []
        details = [
            {"rank": f"{index + 1}等", "amount": amount, "count": counts[index] if index < len(counts) else None}
            for index, amount in enumerate(amounts)
            if amount is not None
        ]
    return {"payout": details[0]["amount"], "detail": details} if details else None


def parse_round(round_no, html):
    if f"第{round_no}回 toto　くじ結果" not in html and f"第{round_no}回 toto くじ結果" not in html:
        return None
    tables = pd.read_html(io.StringIO(html))
    result_tables = [parsed for table in tables if (parsed := parse_result_table(table))]
    payout_tables = [parsed for table in tables if (parsed := parse_payout_table(table))]
    if not result_tables or not payout_tables:
        return None

    payload = {"detail": {}, "results": {}}
    for index, key in enumerate(KUJI_ORDER):
        if index < len(result_tables):
            payload["results"][key] = result_tables[index]
        if index < len(payout_tables):
            payload[key] = payout_tables[index]["payout"]
            payload["detail"][key] = payout_tables[index]["detail"]
    return payload


def saved_round_numbers():
    numbers = []
    for path in glob.glob(os.path.join(DATA_DIR, "round_*.json")):
        match = re.search(r"round_(\d+)\.json$", path)
        if match:
            numbers.append(int(match.group(1)))
    return sorted(set(numbers))


def main():
    requested = [int(arg) for arg in sys.argv[1:] if arg.isdigit()]
    numbers = requested or saved_round_numbers()
    stored = load_json(OUT_JSON, {})
    updated = 0
    for round_no in numbers:
        existing = stored.get(str(round_no), {}) or {}
        # 通常運用では取得済みの確定回を再通信せず、新しい回だけを補完する。
        if not requested and len((existing.get("results", {}) or {}).get("toto", [])) == 13 and existing.get("detail", {}).get("toto"):
            continue
        try:
            parsed = parse_round(round_no, fetch_html(round_no))
        except Exception as error:
            print(f"  [WARN] 第{round_no}回の公式結果取得に失敗: {error}")
            continue
        if not parsed:
            print(f"  第{round_no}回: toto公式結果は未掲載")
            continue
        stored[str(round_no)] = parsed
        updated += 1
        print(f"  第{round_no}回: 1等 {parsed.get('toto', 0):,}円 / 結果{len(parsed.get('results', {}).get('toto', []))}試合")

    if updated:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(OUT_JSON, "w", encoding="utf-8") as handle:
            json.dump(stored, handle, ensure_ascii=False, indent=2)
    print(f"公式結果を{updated}回分更新しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
