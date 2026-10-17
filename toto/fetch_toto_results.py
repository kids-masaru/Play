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
# 勝敗（1=ホーム勝 / 0=引分 / 2=アウェイ勝）を当てるくじ。goal3 は得点数なので含めない。
RESULT_KUJI_ORDER = ["toto", "mini_a", "mini_b"]
PICK_MAP = {"1": "H", "0": "D", "2": "A"}
# 公式結果の読み方の版。版が古い保存分は一度だけ取り直す（2026-10-17 の修正前の誤読を消すため）。
OFFICIAL_VERSION = 2


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


def expected_kuji(round_data):
    """その回で勝敗を当てるくじ（toto / mini_a / mini_b）と試合数を、公式ページの並び順で返す。"""
    kuji = (round_data or {}).get("kuji", {}) or {}
    return [
        (key, len(kuji[key]["matches"]))
        for key in RESULT_KUJI_ORDER
        if (kuji.get(key) or {}).get("matches")
    ]


def is_goal3_table(table):
    """totoGOAL3（チームごとの得点数を当てるくじ）の表。くじ結果は得点数なので勝敗として読まない。"""
    return any("予想チーム" in column for column in flatten_columns(table).columns)


def parse_round(round_no, html, expected):
    """公式結果ページを、くじ種別ごとの結果（H/D/A）と当せん金に分ける。

    2026-10-17 修正：
    - 見出しは「第N回 toto　くじ結果」に限らず「第N回 mini toto-A組　くじ結果」等も受け付ける
      （平日のmini回が永遠に未確定になっていた）。
    - 表の位置で割り当てず、形で見分ける。GOAL3の表は勝敗として読まない
      （以前は4番目の結果表をgoal3として 0/1/2 得点を H/D/A に読み替えていた）。
    - 結果の表は、その回にあるくじへ、試合数が合うものだけを順に割り当てる。
      直後の当せん金の表は、直前に割り当てたくじのものとして扱う。
    """
    if not re.search(rf"第{round_no}回[^<]{{0,40}}くじ結果", html):
        return None
    tables = pd.read_html(io.StringIO(html))
    payload = {"version": OFFICIAL_VERSION, "detail": {}, "results": {}}
    pending = list(expected)
    current = None
    for table in tables:
        if is_goal3_table(table):
            current = "goal3"
            continue
        values = parse_result_table(table)
        if values is not None:
            current = None
            for index, (key, count) in enumerate(pending):
                if len(values) == count:
                    payload["results"][key] = values
                    current = key
                    pending.pop(index)
                    break
            continue
        payout = parse_payout_table(table)
        if payout and current:
            payload[current] = payout["payout"]
            payload["detail"][current] = payout["detail"]
            current = None
    return payload if payload["results"] else None


def is_complete(entry, expected):
    """新しい読み方で、その回の全くじの結果がそろっているか。"""
    if not entry or entry.get("version") != OFFICIAL_VERSION:
        return False
    results = entry.get("results", {}) or {}
    return all(len(results.get(key, []) or []) == count for key, count in expected)


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
        expected = expected_kuji(load_json(os.path.join(DATA_DIR, f"round_{round_no}.json"), {}))
        if not expected:
            continue
        # 通常運用では取得済みの確定回を再通信せず、新しい回・未完成の回だけを補完する。
        if not requested and is_complete(existing, expected):
            continue
        try:
            parsed = parse_round(round_no, fetch_html(round_no), expected)
        except Exception as error:
            print(f"  [WARN] 第{round_no}回の公式結果取得に失敗: {error}")
            continue
        if not parsed:
            print(f"  第{round_no}回: 公式結果は未掲載")
            continue
        stored[str(round_no)] = parsed
        updated += 1
        summary = " / ".join(
            f"{key} {len(parsed['results'].get(key, []))}試合・1等{(parsed.get(key) or 0):,}円"
            for key, _ in expected
        )
        print(f"  第{round_no}回: {summary}")

    if updated:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(OUT_JSON, "w", encoding="utf-8") as handle:
            json.dump(stored, handle, ensure_ascii=False, indent=2)
    print(f"公式結果を{updated}回分更新しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
