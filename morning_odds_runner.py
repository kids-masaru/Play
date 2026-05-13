"""
朝バッチスクリプト: 当日の前売りオッズ取得 → EV計算 → EV強化予測 → LINE通知

タスクスケジューラで毎朝9:00 JSTに実行する想定。
夜間バッチ(main_runner.py)で生成された LightGBM確率ベースの予測に対し、
実オッズを掛け合わせて真のEV（期待値）を算出し、
EV > 1.0 の高期待値買い目に絞り込んだ推奨を生成する。
"""

import os
import sys
import time
import json
import re
import traceback
import numpy as np
import pandas as pd
import requests
import lightgbm as lgb
from datetime import datetime, timedelta, timezone

# --- 既存モジュールのインポート ---
from collect_race_data import (
    get_venues_for_date,
    scrape_odds_3t,
    close_odds_browser,
    append_to_csv,
    VENUE_MAP,
    ODDS_3T_HEADERS
)
from local_ai_pipeline import (
    call_deepseek,
    load_data,
    save_data,
    load_lgb_model,
    load_lgb_model_2nd,
    load_lgb_model_3rd,
    predict_with_model,
    estimate_trifecta_probs,
    build_race_features,
    clean_numeric,
    classify_wind_level,
    load_knowledge,
    get_recent_lessons,
    get_relevant_lessons,
    parse_buy_str,
    kelly_stake,
    PROG_FILE,
    PRED_FILE,
    BI_FILE,
    STATS_FILE,
    KNOWLEDGE_FILE,
    MODEL_FILE,
    MODEL_FILE_2ND,
    MODEL_FILE_3RD,
    DATA_DIR
)

# --- 設定 ---
ODDS_FILE = os.path.join(DATA_DIR, "daily_odds_3t.csv")
EV_THRESHOLD = 1.0  # 期待値がこの値を超える買い目のみ推奨

# 決定論版（LLM不使用）の買い目生成パラメータ
# auto_research/sweep_filters.py で val 期間最適化済み
# 並走目的: LLM版 vs Det版 を毎日記録 → 1〜2週間後に勝者を採用
DET_PROB_MIN = 0.01      # prob 1%未満は除外（低確率帯はモデル過大評価）
DET_EV_MIN = 2.0         # EV 2.0未満は除外（LLM版より厳しめ）
DET_ODDS_MAX = 500       # 500倍超は除外（極端 moonshot）
DET_TOP_N_COMBOS = 4     # 1レース最大 4 combo

# LINE通知（main_runner.py と同じ）
from linebot import LineBotApi
from linebot.models import TextSendMessage
from linebot.exceptions import LineBotApiError

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")


def send_line_message(message):
    """LINE Messaging APIを使ってスマホにメッセージを送信する"""
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("  [WARN] LINE_CHANNEL_ACCESS_TOKEN または LINE_USER_ID が未設定のため、LINE通知をスキップしました。")
        return

    line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
    try:
        line_bot_api.push_message(LINE_USER_ID, TextSendMessage(text=message))
        print("  [SUCCESS] LINEへ通知を送信しました。")
    except LineBotApiError as e:
        print(f"  [ERROR] LINE通知に失敗しました: {e.status_code} {e.error.message}")
    except Exception as e:
        print(f"  [ERROR] 予期せぬエラー: {e}")


# =========================================================
# Job A: 当日の前売りオッズを取得
# =========================================================
def fetch_today_odds(target_date_str):
    """当日のレースの前売りオッズを取得する"""
    print(f"\n--- [Job A] 当日の前売りオッズ取得 ({target_date_str}) ---")

    target_date_csv = f"{target_date_str[:4]}-{target_date_str[4:6]}-{target_date_str[6:]}"

    # 既に取得済みかチェック
    if os.path.exists(ODDS_FILE):
        df_o = pd.read_csv(ODDS_FILE)
        if target_date_csv in df_o['Date'].astype(str).values:
            existing_count = len(df_o[df_o['Date'].astype(str) == target_date_csv])
            print(f"  > {target_date_csv} のオッズは既に {existing_count} 件取得済みです。")
            if existing_count > 100:  # 少なくとも1レース分以上あればスキップ
                print(f"  > [SKIP] 十分なデータがあるためスキップします。")
                return True

    venues = get_venues_for_date(target_date_str)
    if not venues:
        print(f"  > {target_date_str} の開催会場はありません。")
        return False

    print(f"  > 開催会場({len(venues)}): {venues}")
    total_rows = 0

    for jcd in venues:
        v_name = VENUE_MAP.get(jcd, jcd)
        print(f"    - 会場 {v_name} ({jcd})... ", end="", flush=True)
        venue_rows = []

        for rno in range(1, 13):
            time.sleep(0.3)
            o_rows = scrape_odds_3t(jcd, rno, target_date_str)
            if o_rows:
                venue_rows.extend(o_rows)

        if venue_rows:
            append_to_csv(ODDS_FILE, ODDS_3T_HEADERS, venue_rows)
            total_rows += len(venue_rows)
        print(f"完了 ({len(venue_rows)}行)")

    print(f"  > 合計 {total_rows} 件のオッズデータを取得しました。")
    return total_rows > 0


# =========================================================
# Job B: LightGBM確率 × 実オッズ → EV算出
# =========================================================
def calculate_ev_for_races(target_date):
    """各レースの各買い目について EV = predicted_prob × odds を算出する

    Args:
        target_date: 'YYYY-MM-DD' 形式の日付文字列

    Returns:
        dict: {race_id: [(combination, ev, odds, prob), ...]} — EVが高い順にソート済み
    """
    print(f"\n--- [Job B] EV算出 ({target_date}) ---")

    # 1. オッズデータの読み込み
    df_odds = load_data(ODDS_FILE)
    if df_odds.empty:
        print("  > オッズデータがありません。")
        return {}

    df_odds_today = df_odds[df_odds['Date'].astype(str) == target_date]
    if df_odds_today.empty:
        print(f"  > {target_date} のオッズデータがありません。")
        return {}

    # 2. 出走表データの読み込み
    df_prog = load_data(PROG_FILE)
    if df_prog.empty:
        print("  > 出走表データがありません。")
        return {}

    target_races = df_prog[df_prog['Date'].astype(str) == target_date]
    if target_races.empty:
        print(f"  > {target_date} の出走表データがありません。")
        return {}

    # 3. LightGBMモデルのロード（3モデル）
    lgb_model = load_lgb_model()
    if lgb_model is None:
        print("  > [WARN] LightGBMモデルが利用できません。EV計算をスキップします。")
        return {}

    lgb_model_2nd = load_lgb_model_2nd()
    lgb_model_3rd = load_lgb_model_3rd()
    use_3models = (lgb_model_2nd is not None and lgb_model_3rd is not None)
    if use_3models:
        print("  > 3モデル（1着/2着/3着）で高精度3連単確率を算出します。")
    else:
        print("  > [INFO] 2着/3着モデル未整備のため、1着モデルのみの簡易確率で算出します。")

    # 4. 直前情報の読み込み
    bi_dict = {}
    df_bi = load_data(BI_FILE)
    if not df_bi.empty:
        for _, bi_row in df_bi.iterrows():
            bi_id = str(bi_row.get('ID', ''))
            if bi_id:
                bi_dict[bi_id] = bi_row.to_dict()

    # 5. 各レースごとにEVを算出
    grouped = target_races.groupby('ID')
    ev_results = {}

    for race_id, group in grouped:
        race_id_str = str(race_id)

        # LightGBMで確率を算出
        try:
            features = build_race_features(group, bi_dict)
            probs_1st = predict_with_model(lgb_model, features)

            if use_3models:
                probs_2nd = predict_with_model(lgb_model_2nd, features)
                probs_3rd = predict_with_model(lgb_model_3rd, features)
                # 3モデル統合で全120通りの確率を算出
                trifecta_probs = estimate_trifecta_probs(probs_1st, probs_2nd, probs_3rd, top_n=120)
                trifecta_prob_dict = {combo: prob for combo, prob in trifecta_probs}
            else:
                trifecta_prob_dict = None
        except Exception as e:
            print(f"    [WARN] {race_id} の確率計算に失敗: {e}")
            continue

        # このレースのオッズを取得
        race_odds = df_odds_today[df_odds_today['ID'].astype(str) == race_id_str]
        if race_odds.empty:
            continue

        # 各買い目のEVを算出
        ev_list = []

        for _, odds_row in race_odds.iterrows():
            combo = str(odds_row['Combination'])
            odds_val = float(odds_row['Odds'])

            if odds_val <= 0:
                continue

            # 組み合わせをパース: "1-2-3" → (0, 1, 2) (0-indexed)
            parts = combo.split('-')
            if len(parts) != 3:
                continue

            try:
                i = int(parts[0]) - 1  # 1着（0-indexed）
                j = int(parts[1]) - 1  # 2着
                k = int(parts[2]) - 1  # 3着
            except ValueError:
                continue

            if i < 0 or i >= 6 or j < 0 or j >= 6 or k < 0 or k >= 6:
                continue

            if trifecta_prob_dict is not None:
                # 3モデル統合確率を使用
                prob_combo = trifecta_prob_dict.get(combo, 0.0)
            else:
                # フォールバック: 1着モデルのみの簡易3連単確率
                p_i = probs_1st[i]
                denom_j = 1.0 - p_i
                p_j = probs_1st[j] / denom_j if denom_j > 1e-10 else 0
                denom_k = 1.0 - p_i - probs_1st[j]
                p_k = probs_1st[k] / denom_k if denom_k > 1e-10 else 0
                prob_combo = p_i * p_j * p_k

            ev = prob_combo * odds_val
            ev_list.append((combo, ev, odds_val, prob_combo))

        # EVの高い順にソート
        ev_list.sort(key=lambda x: x[1], reverse=True)
        ev_results[race_id_str] = ev_list

    # サマリー出力
    high_ev_races = sum(1 for rid, evl in ev_results.items() if evl and evl[0][1] > EV_THRESHOLD)
    print(f"  > EV算出完了: {len(ev_results)} レース中 {high_ev_races} レースに EV > {EV_THRESHOLD} の買い目あり")

    return ev_results


# =========================================================
# Job C: EV > 1.0 の買い目でAI予測を実行
# =========================================================
def run_ev_predictions(target_date, ev_results):
    """EV値が高い買い目のみを使ってAI予測を再実行し、daily_predictions.csvを更新する"""
    print(f"\n--- [Job C] EVベースAI予測 ({target_date}) ---")

    if not ev_results:
        print("  > EV算出結果がありません。予測をスキップします。")
        return []

    # EV > threshold のレースを抽出し、最大EVでソート
    high_ev_races = []
    for race_id, ev_list in ev_results.items():
        top_ev_bets = [(combo, ev, odds, prob) for combo, ev, odds, prob in ev_list if ev > EV_THRESHOLD]
        if top_ev_bets:
            max_ev = top_ev_bets[0][1]
            high_ev_races.append((race_id, max_ev, top_ev_bets))

    high_ev_races.sort(key=lambda x: x[1], reverse=True)

    if not high_ev_races:
        print(f"  > EV > {EV_THRESHOLD} の買い目がありません。推奨なし。")
        return []

    # 上位10レースに絞る
    top_races = high_ev_races[:10]
    print(f"  > EV > {EV_THRESHOLD} のレース: {len(high_ev_races)} 件 → 上位 {len(top_races)} 件を予測")

    # 出走表の読み込み
    df_prog = load_data(PROG_FILE)
    target_progs = df_prog[df_prog['Date'].astype(str) == target_date]
    grouped = target_progs.groupby('ID')
    prog_dict = {str(rid): grp for rid, grp in grouped}

    # コース別成績
    df_stats = load_data(STATS_FILE)
    stats_dict = {}
    if not df_stats.empty:
        stats_dict = df_stats.set_index('PlayerID').to_dict('index')

    # 専門知識
    knowledge = load_knowledge()
    knowledge_str = json.dumps(knowledge, ensure_ascii=False, indent=2)

    # 直前情報（教訓の条件フィルタ用）
    bi_dict = {}
    df_bi = load_data(BI_FILE)
    if not df_bi.empty:
        for _, bi_row in df_bi.iterrows():
            bi_id = str(bi_row.get('ID', ''))
            if bi_id:
                bi_dict[bi_id] = bi_row.to_dict()

    # 既存予測の読み込み（朝バッチで上書き更新する）
    df_pred = load_data(PRED_FILE)
    if df_pred.empty:
        df_pred = pd.DataFrame(columns=["RaceID", "Date", "Venue", "R", "Prediction", "Log"])

    new_preds = []

    for race_id, max_ev, top_ev_bets in top_races:
        if race_id not in prog_dict:
            continue

        group = prog_dict[race_id]
        venue = group['Venue'].iloc[0]
        r = group['R'].iloc[0]
        date_val = group['Date'].iloc[0]

        print(f"  [{len(new_preds)+1}/{len(top_races)}] {venue} {r}R (MaxEV: {max_ev:.2f})", flush=True)

        # 出走表情報
        racer_info = []
        for _, row in group.iterrows():
            lane = int(row['Lane'])
            pid = str(row['PlayerID'])
            base_info = f"{lane}号艇: {row['Name']} (モーター:{row['Motor']}, ランク:{row['Rank']}, 全国勝率:{row['WinRate']})"

            if pid in stats_dict:
                s = stats_dict[pid]
                c_win = s.get(f'C{lane}_Win', 0)
                c_2in = s.get(f'C{lane}_2in', 0)
                c_3in = s.get(f'C{lane}_3in', 0)
                base_info += f" [当コース実績: 1着率{c_win}%, 2連率{c_2in}%, 3連率{c_3in}%]"

            racer_info.append(base_info)
        prompt_data = "\n".join(racer_info)

        # EV情報をプロンプトに注入
        ev_lines = []
        for combo, ev, odds, prob in top_ev_bets[:15]:  # 上位15通りまで
            ev_mark = "🔥" if ev > 2.0 else "✨" if ev > 1.5 else "📊"
            ev_lines.append(f"  {ev_mark} {combo}: EV={ev:.2f} (確率{prob*100:.2f}% × オッズ{odds:.1f}倍)")
        ev_str = "\n".join(ev_lines)

        # Phase 3: レース条件に合致する教訓を優先取得
        bi_info = bi_dict.get(race_id, {})
        race_weather = str(bi_info.get('Weather', '')).strip()
        race_wind_level = classify_wind_level(bi_info.get('WindSpeed', ''))
        lessons = get_relevant_lessons(
            venue=venue,
            weather=race_weather,
            wind_level=race_wind_level,
            max_count=5
        )
        lessons_str = "\n".join([f"・{l}" for l in lessons]) if lessons else ""

        prompt = f"""あなたは日本最高峰の天才舟券師AIです。
以下のデータと専門知識をもとに、期待値を最大化する結論を導き出してください。

【重要: 実オッズに基づくEV（期待値）分析結果】
EV = AI推定確率 × 実オッズ。EV > 1.0 は長期的にプラス収支が見込める買い目です。
{ev_str}

【出走表】
{prompt_data}

【専門家の勝負鉄則】
{knowledge_str}
"""
        if lessons_str:
            prompt += f"""
【重要：過去の反省点（この会場・条件に関連する教訓を優先選択済み）】
{lessons_str}
"""
        prompt += """
出力形式は必ず以下を守ってください：
■展開予想と推奨理由
（EVデータを踏まえた分析）
■最終推奨買い目
（EV > 1.0 の買い目から、1-2-3, 1-3-2 のように記載。EV値も併記すること）"""

        print("    -> EV強化版AI 推論中...", end=" ", flush=True)
        start_time = time.time()
        response = call_deepseek(prompt)
        elapsed = time.time() - start_time
        print(f"完了 ({elapsed:.0f}秒)")

        # Kelly stakes: EV買い目ごとにケリー基準でステーク額を算出
        kelly_stakes_map = {}
        for combo, ev, odds, prob in top_ev_bets:
            s = kelly_stake(prob, odds)
            if s > 0:
                kelly_stakes_map[combo.replace('-', '')] = s

        # ===== LLM版 =====
        # AIが選んだ買い目にケリー額を割り当て（EVデータにない買い目は最低100円）
        chosen_eyes = parse_buy_str(response)
        stakes_for_race = {eye: kelly_stakes_map.get(eye, 100) for eye in chosen_eyes}

        # ===== 決定論版（並走、LLM不使用） =====
        # フィルタを通過した上位 N combo を Kelly stake で買う
        det_filtered = [
            (c, e, o, p) for c, e, o, p in top_ev_bets
            if p >= DET_PROB_MIN and e >= DET_EV_MIN and o <= DET_ODDS_MAX
        ]
        # top_ev_bets は既に EV 降順
        det_top = det_filtered[:DET_TOP_N_COMBOS]
        det_stakes = {}
        for combo, ev, odds, prob in det_top:
            s = kelly_stake(prob, odds)
            if s > 0:
                det_stakes[combo.replace('-', '')] = s

        pred_entry = {
            "RaceID": race_id,
            "Date": date_val,
            "Venue": venue,
            "R": r,
            "Prediction": response,
            "Log": f"【朝バッチ EV強化版】MaxEV={max_ev:.2f}\n{response}",
            "Stakes": json.dumps(stakes_for_race, ensure_ascii=False),
            "Stakes_Det": json.dumps(det_stakes, ensure_ascii=False),
        }
        new_preds.append(pred_entry)

        # 既存の同じRaceIDの予測を上書き
        df_pred = df_pred[df_pred['RaceID'].astype(str) != str(race_id)]
        df_pred = pd.concat([df_pred, pd.DataFrame([pred_entry])], ignore_index=True)
        save_data(df_pred, PRED_FILE)

    print(f"  > EV強化予測完了: {len(new_preds)} 件")
    return new_preds


# =========================================================
# Job D: LINE通知（EVベース推奨買い目）
# =========================================================
def build_morning_notification(target_date, ev_results, new_preds):
    """朝バッチ用のLINE通知メッセージを構築する

    Det版本番一本化 (2026-05-12〜): Det stakes 空でないレースのみ列挙、
    買い目欄は Det 組み合わせを直接表示。LLM は参考表示として小さく出す。
    """
    msg_parts = [f"\n🌅 [朝バッチ Det本番推奨] {target_date}\n"]

    if not new_preds:
        msg_parts.append("本日はEV > 1.0 の推奨レースがありません。")
        return "\n".join(msg_parts)

    # Det stakes ありのレースだけ抽出（Det本番一本化のため、Det空は通知に出さない）
    det_preds = []
    for pred in new_preds:
        try:
            det_dict = json.loads(pred.get('Stakes_Det', '{}'))
        except Exception:
            det_dict = {}
        if det_dict:
            det_preds.append((pred, det_dict))

    llm_only_count = len(new_preds) - len(det_preds)

    if not det_preds:
        msg_parts.append("本日はDetフィルタを通る推奨買い目がありません（本番見送り）。")
        if llm_only_count:
            msg_parts.append(f"※LLM側のみ {llm_only_count} 件は記録済み（monitoring用）")
        dashboard_url = "https://kids-masaru.github.io/Play/"
        msg_parts.append(f"\n{dashboard_url}")
        return "\n".join(msg_parts)

    msg_parts.append(f"📊 本番推奨: {len(det_preds)} 件 (LLM monitoring: {llm_only_count} 件は記録のみ)\n")

    for pred, det_dict in det_preds:
        race_id = pred['RaceID']
        venue = pred['Venue']
        r = pred['R']

        # Det 買い目を 1-2-3 形式に整形して列挙
        det_combos = []
        for eye, stake in det_dict.items():
            combo = f"{eye[0]}-{eye[1]}-{eye[2]}" if len(eye) == 3 else eye
            det_combos.append(f"{combo}({stake}円)")
        det_buy_str = ", ".join(det_combos)
        det_total = sum(det_dict.values())

        # 参考: LLM stakes 合計
        llm_disp = ""
        try:
            llm_dict = json.loads(pred.get('Stakes', '{}'))
            if llm_dict:
                llm_total = sum(llm_dict.values())
                llm_disp = f" (参考LLM:{llm_total}円 {len(llm_dict)}点)"
        except Exception:
            pass

        # EVトップ3
        ev_list = ev_results.get(str(race_id), [])
        ev_top3 = [(c, e, o) for c, e, o, p in ev_list[:3] if e > EV_THRESHOLD]
        ev_disp = ", ".join([f"{c}(EV{e:.1f})" for c, e, o in ev_top3])

        msg_parts.append(f"📍 {venue}{r}R [本番:{det_total}円 {len(det_dict)}点]{llm_disp}")
        msg_parts.append(f"   └ 買い目: {det_buy_str}")
        if ev_disp:
            msg_parts.append(f"   └ EV上位: {ev_disp}")

    dashboard_url = "https://kids-masaru.github.io/Play/"
    msg_parts.append(f"\n※詳細はダッシュボードをご確認ください。\n{dashboard_url}")

    return "\n".join(msg_parts)


# =========================================================
# メインエントリーポイント
# =========================================================
def main():
    print(f"=== 朝バッチ: EVベース予測強化システム 開始 ===")
    start_time = datetime.now()

    JST = timezone(timedelta(hours=9))
    now_jst = datetime.now(JST)

    # 当日の日付
    target_date_str = now_jst.strftime("%Y%m%d")  # YYYYMMDD (スクレイピング用)
    target_date = now_jst.strftime("%Y-%m-%d")     # YYYY-MM-DD (CSV照合用)

    print(f"対象日: {target_date} (JST: {now_jst.strftime('%Y-%m-%d %H:%M:%S')})")

    try:
        # Job A: 当日の前売りオッズを取得
        has_odds = fetch_today_odds(target_date_str)

        if not has_odds:
            print("\n[INFO] オッズデータが取得できなかったため、朝バッチを終了します。")
            send_line_message(f"🌅 [朝バッチ] {target_date}\n本日の開催がないか、オッズデータの取得に失敗しました。")
            return

        # Job B: EV算出
        ev_results = calculate_ev_for_races(target_date)

        # Job C: EV強化予測
        new_preds = run_ev_predictions(target_date, ev_results)

        # Job D: LINE通知
        print("\n--- [Job D] LINE通知送信 ---")
        msg = build_morning_notification(target_date, ev_results, new_preds)
        send_line_message(msg)

    except Exception as e:
        error_msg = traceback.format_exc()
        print(f"\n[FATAL ERROR] 朝バッチでエラーが発生しました:\n{error_msg}")
        send_line_message(f"🌅 [朝バッチ] {target_date}\n❌ エラー発生: {e}")
    finally:
        # ブラウザのクリーンアップ
        close_odds_browser()

    end_time = datetime.now()
    duration = end_time - start_time
    print(f"\n=== 朝バッチ完了 (所要時間: {duration}) ===")


if __name__ == "__main__":
    main()
