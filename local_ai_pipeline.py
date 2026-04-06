import os
import time
import numpy as np
import pandas as pd
import requests
import lightgbm as lgb
from datetime import datetime, timedelta, timezone
import database as db

# --- 設定 ---
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "deepseek-r1:14b"
DATA_DIR = "daily_data"

PROG_FILE = os.path.join(DATA_DIR, "daily_raw_race_data.csv")
RES_FILE  = os.path.join(DATA_DIR, "daily_history_results.csv")
PRED_FILE = os.path.join(DATA_DIR, "daily_predictions.csv")
REFL_FILE = os.path.join(DATA_DIR, "daily_reflections.csv")
STATS_FILE = os.path.join(DATA_DIR, "daily_player_course_stats.csv")
KNOWLEDGE_FILE = "expert_knowledge.json"
MODEL_FILE = os.path.join("models", "lgb_model_1st.txt")
MODEL_FILE_2ND = os.path.join("models", "lgb_model_2nd.txt")
MODEL_FILE_3RD = os.path.join("models", "lgb_model_3rd.txt")
BI_FILE = os.path.join(DATA_DIR, "daily_raw_beforeinfo.csv")
ODDS_FILE = os.path.join(DATA_DIR, "daily_odds_3t.csv")

def load_knowledge():
    if os.path.exists(KNOWLEDGE_FILE):
        with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

import json

def call_deepseek(prompt, max_retries=3):
    """ローカルOllama DeepSeekを呼び出す"""
    for attempt in range(max_retries):
        try:
            response = requests.post(OLLAMA_URL, json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "num_predict": 2000
                }
            }, timeout=900)
            
            # 推論が非常に重いため、少し待ち時間を入れる
            time.sleep(5)
            
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "")
            else:
                print(f"  [WARN] Ollama応答エラー (HTTP {response.status_code}): {response.text[:200]}")
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(10)
            else:
                return f"[ERROR] {str(e)}"
    return "[ERROR] 失敗"

def load_data(filepath):
    if os.path.exists(filepath):
        return pd.read_csv(filepath)
    return pd.DataFrame()

def save_data(df, filepath):
    df.to_csv(filepath, index=False, encoding='utf-8')

def get_recent_lessons(max_count=5):
    """daily_reflections.csv から最新の教訓を取得する（後方互換用）"""
    df_refl = load_data(REFL_FILE)
    if df_refl.empty:
        return []

    # 最新 max_count 件を取得
    recent = df_refl.tail(max_count)
    lessons = []
    for _, row in recent.iterrows():
        text = str(row.get('Lesson', ''))
        if '教訓' in text:
            # 教訓テキストを整形（改行除去、150文字以内に制限）
            cleaned = text.replace('\n', ' ').strip()[:150]
            lessons.append(cleaned)
    return lessons


def classify_wind_level(wind_speed):
    """風速を3段階レベルに分類する
    calm: 0-2m, moderate: 3-5m, strong: 6m+
    """
    if pd.isna(wind_speed):
        return 'unknown'
    try:
        ws = float(str(wind_speed).replace('m', '').strip())
    except (ValueError, TypeError):
        return 'unknown'
    if ws <= 2:
        return 'calm'
    elif ws <= 5:
        return 'moderate'
    else:
        return 'strong'


def get_relevant_lessons(venue=None, weather=None, wind_level=None, max_count=5):
    """対象レースの条件に合致する教訓を優先的に取得する

    優先度:
      1. 同会場 + 似た天候 → 優先度高
      2. 同会場（天候不問）→ 優先度中
      3. 似た風レベル → 優先度低
      4. その他 → 最低優先

    Args:
        venue: 会場名（例: "住之江"）
        weather: 天候（例: "晴"）
        wind_level: 風レベル（"calm"/"moderate"/"strong"）
        max_count: 最大件数

    Returns:
        list of str: 教訓テキストのリスト
    """
    df_refl = load_data(REFL_FILE)
    if df_refl.empty:
        return []

    # スコアリング: 各教訓に関連度スコアを付与
    scored = []
    for _, row in df_refl.iterrows():
        text = str(row.get('Lesson', ''))
        if '教訓' not in text:
            continue

        cleaned = text.replace('\n', ' ').strip()[:150]
        score = 0

        # 条件カラムが存在する場合のみ条件フィルタリング
        row_venue = str(row.get('Venue', ''))
        row_weather = str(row.get('Weather', ''))
        row_wind = str(row.get('WindLevel', ''))

        # 同会場 → +3点
        if venue and row_venue == venue:
            score += 3

        # 同天候 → +2点
        if weather and row_weather and row_weather == weather:
            score += 2

        # 同風レベル → +1点
        if wind_level and row_wind and row_wind == wind_level:
            score += 1

        scored.append((score, cleaned, row.get('Date', '')))

    # スコアの高い順 → 日付の新しい順にソート
    scored.sort(key=lambda x: (x[0], x[2]), reverse=True)

    return [text for _, text, _ in scored[:max_count]]

def rank_to_score(rank_str):
    """ランクを数値スコアに変換 (A1=4, A2=3, B1=2, B2=1)"""
    mapping = {"A1": 4, "A2": 3, "B1": 2, "B2": 1}
    return mapping.get(str(rank_str).upper(), 0)

def clean_numeric(val):
    """文字列から数値を安全に抽出する"""
    if pd.isna(val) or val == "": return np.nan
    try:
        s = ''.join(c for c in str(val) if c.isdigit() or c in ['.', '-'])
        return float(s) if s else np.nan
    except:
        return np.nan

def parse_buy_str(pred_text):
    """AIの予測テキストから買い目（コンボ）リストを抽出する"""
    import re as _re
    try:
        text = str(pred_text)
        for marker in ['■最終推奨買い目', '【最終推奨買い目】', '【最終推奨買い目', '最終推奨買い目']:
            if marker in text:
                buy_part = text.split(marker)[-1].strip()
                eyes = _re.findall(r'\d-\d-\d|\d{3}', buy_part)
                if eyes:
                    return [e.replace('-', '') for e in eyes]
        return []
    except:
        return []

def kelly_stake(prob, odds, bankroll=10000, fraction=0.5, min_bet=100, max_bet=5000):
    """ケリー基準でステーク額を算出する（ハーフケリーデフォルト）

    Args:
        prob: 的中確率 (0.0〜1.0)
        odds: トータルオッズ（例: 20.0 → 100円賭けで2000円リターン）
        bankroll: 仮想バンクロール (デフォルト10000円/レース)
        fraction: フラクショナルケリー係数 (デフォルト0.5 = ハーフケリー)
        min_bet: 最低ベット額 (デフォルト100円)
        max_bet: 最大ベット額 (デフォルト5000円)

    Returns:
        stake: ベット額 (100円単位)。EV < 1.0 の場合は 0。
    """
    if odds <= 1.0 or prob <= 0.0:
        return 0
    kelly_f = (prob * odds - 1.0) / (odds - 1.0)
    if kelly_f <= 0:
        return 0
    stake = bankroll * kelly_f * fraction
    stake = int(stake // 100) * 100
    return max(min_bet, min(max_bet, stake))

def load_lgb_model():
    """学習済みLightGBMモデルをロードする"""
    if os.path.exists(MODEL_FILE):
        try:
            model = lgb.Booster(model_file=MODEL_FILE)
            print(f"  ✅ LightGBMモデルをロードしました ({model.num_trees()}本の決定木)", flush=True)
            return model
        except Exception as e:
            print(f"  [WARN] LightGBMモデルロード失敗: {e}", flush=True)
    else:
        print(f"  [WARN] モデルファイル {MODEL_FILE} が見つかりません", flush=True)
    return None

def load_lgb_model_2nd():
    """学習済みLightGBM 2着予測モデルをロードする"""
    if os.path.exists(MODEL_FILE_2ND):
        try:
            model = lgb.Booster(model_file=MODEL_FILE_2ND)
            print(f"  ✅ LightGBM 2着モデルをロードしました ({model.num_trees()}本の決定木)", flush=True)
            return model
        except Exception as e:
            print(f"  [WARN] LightGBM 2着モデルロード失敗: {e}", flush=True)
    else:
        print(f"  [WARN] 2着モデルファイル {MODEL_FILE_2ND} が見つかりません", flush=True)
    return None


def load_lgb_model_3rd():
    """学習済みLightGBM 3着予測モデルをロードする"""
    if os.path.exists(MODEL_FILE_3RD):
        try:
            model = lgb.Booster(model_file=MODEL_FILE_3RD)
            print(f"  ✅ LightGBM 3着モデルをロードしました ({model.num_trees()}本の決定木)", flush=True)
            return model
        except Exception as e:
            print(f"  [WARN] LightGBM 3着モデルロード失敗: {e}", flush=True)
    else:
        print(f"  [WARN] 3着モデルファイル {MODEL_FILE_3RD} が見つかりません", flush=True)
    return None


def predict_with_model(model, features_dict):
    """任意のLightGBMモデルで確率を算出する共通関数"""
    feature_names = model.feature_name()
    values = []
    for fname in feature_names:
        val = features_dict.get(fname, np.nan)
        values.append(val if not (isinstance(val, float) and np.isnan(val)) else 0.0)
    X = np.array([values])
    return model.predict(X)[0]  # [P(1号艇), P(2号艇), ..., P(6号艇)]


def estimate_trifecta_probs(probs_1st, probs_2nd, probs_3rd, top_n=20):
    """3つのLightGBMモデルの出力から3連単確率を推定する

    条件付き確率の近似:
      P(i-j-k) ≈ P_1st(i) × P_2nd(j|i≠j) × P_3rd(k|i≠k,j≠k)

    ここで:
      P_2nd(j|i≠j) = P_2nd(j) / (1 - P_2nd(i))   ← i番が1着なので2着候補から除外
      P_3rd(k|i≠k,j≠k) = P_3rd(k) / (1 - P_3rd(i) - P_3rd(j))  ← i,jを除外

    Args:
        probs_1st: 1着モデルの確率配列 [P(1号艇), ..., P(6号艇)]
        probs_2nd: 2着モデルの確率配列 [P(1号艇), ..., P(6号艇)]
        probs_3rd: 3着モデルの確率配列 [P(1号艇), ..., P(6号艇)]
        top_n: 上位何通りを返すか

    Returns:
        list of (combination_str, probability): 確率の高い順にソート済み
    """
    combos = []

    for i in range(6):
        p_i = probs_1st[i]
        if p_i < 0.01:  # 1着確率1%未満は無視
            continue

        # 2着の条件付き確率: iが1着になったので、2着候補からiを除外
        denom_2nd = max(1.0 - probs_2nd[i], 1e-10)
        for j in range(6):
            if j == i:
                continue
            p_j_given_i = probs_2nd[j] / denom_2nd

            # 3着の条件付き確率: i,jが上位2着なので、3着候補からi,jを除外
            denom_3rd = max(1.0 - probs_3rd[i] - probs_3rd[j], 1e-10)
            for k in range(6):
                if k == i or k == j:
                    continue
                p_k_given_ij = probs_3rd[k] / denom_3rd

                prob = p_i * p_j_given_i * p_k_given_ij
                if prob > 0.0005:  # 0.05%以上のみ保持
                    combos.append((f"{i+1}-{j+1}-{k+1}", prob))

    # 確率の高い順にソート
    combos.sort(key=lambda x: x[1], reverse=True)

    # 正規化（全120通りの確率の合計が1になるように）
    total = sum(p for _, p in combos)
    if total > 0:
        combos = [(c, p / total) for c, p in combos]

    return combos[:top_n]


def build_race_features(group, bi_dict):
    """1レース分の出走表データ(group)と直前情報(bi_dict)から、LightGBMモデル用のフィーチャーを構築する"""
    race_id = group['ID'].iloc[0]
    r_no = int(group['R'].iloc[0])
    venue = str(group['Venue'].iloc[0])
    date_str = str(group['Date'].iloc[0])

    # --- 直前情報の取得 ---
    bi = bi_dict.get(str(race_id), {})
    wind_speed = clean_numeric(bi.get('WindSpeed', np.nan))
    wave = clean_numeric(bi.get('Wave', np.nan))
    water_temp = clean_numeric(bi.get('WaterTemp', np.nan))
    wind_dir = str(bi.get('WindDir', '無風')).strip()

    features = {'R': r_no, 'WindSpeed': wind_speed, 'Wave': wave, 'WaterTemp': water_temp}

    # --- 艇別データの構築 ---
    for _, row in group.iterrows():
        lane = int(row['Lane'])
        prefix = f'B{lane}'

        # 勝率
        features[f'{prefix}_WinRate'] = clean_numeric(row.get('WinRate', np.nan))
        # モーター番号
        features[f'{prefix}_Motor'] = clean_numeric(row.get('Motor', 0))
        # ランクスコア
        features[f'{prefix}_RankScore'] = rank_to_score(row.get('Rank', ''))

        # 直前情報からTiltとExTime
        features[f'{prefix}_Tilt'] = clean_numeric(bi.get(f'{prefix}_Tilt', np.nan))
        features[f'{prefix}_ExTime'] = clean_numeric(bi.get(f'{prefix}_ExTime', np.nan))

        # コース別成績（あれば）
        features[f'{prefix}_Course_Win'] = clean_numeric(row.get('Course_Win', 0))
        features[f'{prefix}_Course_2in'] = clean_numeric(row.get('Course_2in', 0))
        features[f'{prefix}_Course_3in'] = clean_numeric(row.get('Course_3in', 0))
        # Weight
        features[f'{prefix}_Weight'] = clean_numeric(bi.get(f'{prefix}_Weight', np.nan))

    # --- 派生特徴量（既存） ---
    b1_wr = features.get('B1_WinRate', np.nan)
    b2_wr = features.get('B2_WinRate', np.nan)
    features['Diff_WinRate_1_2'] = (b1_wr - b2_wr) if not (np.isnan(b1_wr) or np.isnan(b2_wr)) else 0

    win_rates = [features.get(f'B{i}_WinRate', np.nan) for i in range(1, 7)]
    valid_wr = [w for w in win_rates if not np.isnan(w)]
    avg_wr = np.mean(valid_wr) if valid_wr else 0
    features['Avg_WinRate'] = avg_wr
    features['B1_WinRate_Over_Avg'] = (b1_wr - avg_wr) if not np.isnan(b1_wr) else 0

    # --- 派生特徴量（2026-04 拡張） ---
    # (A) 会場エンコーディング
    _venue_list = ['びわこ','ボートレース','下関','三国','住之江','児島','唐津','多摩川','大村',
                   '宮島','尼崎','常滑','平和島','徳山','戸田','桐生','浜名湖','津','芦屋',
                   '蒲郡','若松','丸亀','福岡','鳴門','江戸川']
    _venue_list_sorted = sorted(_venue_list)
    _venue_map = {v: i for i, v in enumerate(_venue_list_sorted)}
    features['VenueID'] = _venue_map.get(venue, -1)

    # (B) 月
    try:
        features['Month'] = int(date_str.split('-')[1])
    except Exception:
        features['Month'] = 0

    # (C) 展示タイム相対指標
    ex_vals = [features.get(f'B{i}_ExTime', np.nan) for i in range(1, 7)]
    valid_ex = [v for v in ex_vals if not (isinstance(v, float) and np.isnan(v))]
    if valid_ex:
        ex_min = min(valid_ex)
        ex_max = max(valid_ex)
        ex_avg = np.mean(valid_ex)
        features['ExTime_Min'] = ex_min
        features['ExTime_Max'] = ex_max
        features['ExTime_Spread'] = ex_max - ex_min
        b1_ex = features.get('B1_ExTime', np.nan)
        features['B1_ExTime_vs_Min'] = (b1_ex - ex_min) if not (isinstance(b1_ex, float) and np.isnan(b1_ex)) else 0
        features['B1_ExTime_vs_Avg'] = (b1_ex - ex_avg) if not (isinstance(b1_ex, float) and np.isnan(b1_ex)) else 0
    else:
        features['ExTime_Min'] = 0
        features['ExTime_Max'] = 0
        features['ExTime_Spread'] = 0
        features['B1_ExTime_vs_Min'] = 0
        features['B1_ExTime_vs_Avg'] = 0

    # (D) 勝率の追加相対指標
    valid_wr_all = [w for w in win_rates if not (isinstance(w, float) and np.isnan(w))]
    if valid_wr_all:
        features['Max_WinRate'] = max(valid_wr_all)
        features['WinRate_Spread'] = max(valid_wr_all) - min(valid_wr_all)
        features['B1_Is_Top_WinRate'] = 1 if (not np.isnan(b1_wr) and b1_wr >= max(valid_wr_all)) else 0
        outer_wr = [features.get(f'B{i}_WinRate', 0) for i in range(2, 7)]
        outer_valid = [w for w in outer_wr if not (isinstance(w, float) and np.isnan(w))]
        max_outer = max(outer_valid) if outer_valid else 0
        features['Max_Outer_WinRate'] = max_outer
        features['Diff_B1_vs_MaxOuter'] = (b1_wr - max_outer) if not np.isnan(b1_wr) else 0
    else:
        features['Max_WinRate'] = 0
        features['WinRate_Spread'] = 0
        features['B1_Is_Top_WinRate'] = 0
        features['Max_Outer_WinRate'] = 0
        features['Diff_B1_vs_MaxOuter'] = 0

    # (E) ランクスコア集約
    rank_scores = [features.get(f'B{i}_RankScore', 0) for i in range(1, 7)]
    features['Avg_RankScore'] = np.mean(rank_scores)
    features['B1_RankScore_Over_Avg'] = features.get('B1_RankScore', 0) - features['Avg_RankScore']

    # (F) 風向き交互作用
    wind_dir_map = {'追い風': 0, '向かい風': 1, '右横風': 2, '左横風': 3, '無風': 4}
    features['WindDirCode'] = wind_dir_map.get(wind_dir, 4)
    features['IsHeadwind'] = 1 if wind_dir == '向かい風' else 0
    ws = wind_speed if not (isinstance(wind_speed, float) and np.isnan(wind_speed)) else 0
    features['Headwind_x_Speed'] = features['IsHeadwind'] * ws

    return features

def score_race_with_lgb(model, features_dict):
    """LightGBMモデルで1レースの期待値スコアを算出する"""
    # モデルが期待するフィーチャー順に並べる
    feature_names = model.feature_name()
    values = []
    for fname in feature_names:
        val = features_dict.get(fname, np.nan)
        values.append(val if not (isinstance(val, float) and np.isnan(val)) else 0.0)
    
    # 予測（各艇の1着確率を算出）
    X = np.array([values])
    probs = model.predict(X)[0]  # [P(1号艇1着), P(2号艇1着), ..., P(6号艇1着)]
    
    # 期待値スコア: 確率分布の偏りが大きいほど予測しやすい（エントロピーが低い＝良い）
    # 最大確率が高いほど自信がある → スコアを高くする
    max_prob = max(probs)
    entropy = -sum(p * np.log(p + 1e-10) for p in probs)
    score = max_prob * (1.0 / (entropy + 0.1))  # 高確率 × 低エントロピー = 高スコア
    
    return score, probs

# =========================================================
# Phase 1: 予測フェーズ (マルチエージェント)
# =========================================================
def run_predictions():
    print("\n=== Phase 1: 明日のレース予測（マルチエージェント討論） ===", flush=True)
    df_prog = load_data(PROG_FILE)
    if df_prog.empty:
        print("  > 出走表データがありません。")
        return
        
    df_pred = load_data(PRED_FILE)
    if df_pred.empty:
        # PRED_FILEが存在しない場合、空のDFにカラムを定義
        df_pred = pd.DataFrame(columns=["RaceID", "Date", "Venue", "R", "Prediction", "Log"])

    # 明日の日付（JST）
    JST = timezone(timedelta(hours=9))
    now_jst = datetime.now(JST)
    target_date = (now_jst + timedelta(days=1)).strftime('%Y-%m-%d') if now_jst.hour >= 18 else now_jst.strftime('%Y-%m-%d')

    # 対象日のレースを抽出
    # 出走表は1レース6行あるので、IDでグループ化してレースデータを組み立てる
    target_races = df_prog[df_prog['Date'].astype(str) == target_date]
    if target_races.empty:
        print(f"  > {target_date} の出走表データがありません。")
        return

    # 既に予測済みのRaceIDを取得
    predicted_ids = set(df_pred['RaceID'].astype(str).unique()) if not df_pred.empty else set()

    grouped = target_races.groupby('ID')
    
    # ─── 直前情報の読み込み（特徴量構築用） ───
    bi_dict = {}
    df_bi = load_data(BI_FILE)
    if not df_bi.empty:
        for _, bi_row in df_bi.iterrows():
            bi_id = str(bi_row.get('ID', ''))
            if bi_id:
                bi_dict[bi_id] = bi_row.to_dict()
    
    # ─── LightGBMモデルによる全レースの期待値算出と上位10レース抽出 ───
    lgb_model = load_lgb_model()
    lgb_model_2nd = load_lgb_model_2nd()
    lgb_model_3rd = load_lgb_model_3rd()
    use_lgb = lgb_model is not None
    use_3models = (lgb_model_2nd is not None and lgb_model_3rd is not None)

    if use_lgb:
        model_desc = "3モデル（1着/2着/3着）" if use_3models else "1着モデルのみ"
        print(f"  > LightGBM ({model_desc}): 全 {len(grouped)} レースの期待値を計算・選抜中...", flush=True)
    else:
        print(f"  > [WARN] LightGBMモデル無効のため、勝率ベースの簡易スコアで選抜します", flush=True)

    race_scores = []
    skipped_count = 0
    lgb_probs_map = {}       # レースID → 1着確率配列
    lgb_probs_2nd_map = {}   # レースID → 2着確率配列
    lgb_probs_3rd_map = {}   # レースID → 3着確率配列

    for race_id, group in grouped:
        if str(race_id) in predicted_ids:
            skipped_count += 1
            continue

        if use_lgb:
            # 実際のLightGBMモデルで期待値を計算
            try:
                features = build_race_features(group, bi_dict)
                score, probs = score_race_with_lgb(lgb_model, features)
                lgb_probs_map[str(race_id)] = probs

                # 2着・3着モデルの確率も算出
                if use_3models:
                    probs_2nd = predict_with_model(lgb_model_2nd, features)
                    probs_3rd = predict_with_model(lgb_model_3rd, features)
                    lgb_probs_2nd_map[str(race_id)] = probs_2nd
                    lgb_probs_3rd_map[str(race_id)] = probs_3rd
            except Exception as e:
                print(f"    [WARN] {race_id} のスコア計算に失敗: {e}", flush=True)
                # フォールバック: 勝率ベースの簡易スコア
                b1_wr = clean_numeric(group[group['Lane']==1]['WinRate'].iloc[0]) if len(group[group['Lane']==1]) > 0 else 5.0
                score = b1_wr / 10.0 if not np.isnan(b1_wr) else 0.5
                lgb_probs_map[str(race_id)] = None
        else:
            # フォールバック: 1号艇の勝率が高いほどスコアが高い
            b1_wr = clean_numeric(group[group['Lane']==1]['WinRate'].iloc[0]) if len(group[group['Lane']==1]) > 0 else 5.0
            score = b1_wr / 10.0 if not np.isnan(b1_wr) else 0.5
            lgb_probs_map[str(race_id)] = None

        race_scores.append((race_id, score, group))
        
    if skipped_count > 0:
        print(f"  > 予測済み {skipped_count} 件をスキップ")
        
    knowledge = load_knowledge()
    knowledge_str = json.dumps(knowledge, ensure_ascii=False, indent=2)

    # ─── 教訓はレースごとに条件フィルタ付きで取得する（Phase 3） ───
    print(f"  > 教訓注入: レースごとに条件（会場・天候・風）に合致する教訓を選択します", flush=True)

    # 期待値の高い順にソートして上位10レースを厳選
    race_scores.sort(key=lambda x: x[1], reverse=True)
    top_races = race_scores[:10]
    
    if not top_races:
        print(f"  > 新規に予測すべきレースがありませんでした。")
        return
        
    print(f"  > 激アツ抽出完了: 上位 {len(top_races)} レースに対し『統合天才AI (Expert Knowledge版)』のディープ推論を開始します。\n")

    new_preds = []
    processed = 0
    total = len(top_races)
    
    # コース別成績の読み込み
    df_stats = load_data(STATS_FILE)
    stats_dict = {}
    if not df_stats.empty:
        stats_dict = df_stats.set_index('PlayerID').to_dict('index')
    
    for race_id, expected_value, group in top_races:
        venue = group['Venue'].iloc[0]
        r = group['R'].iloc[0]
        date_val = group['Date'].iloc[0]
        
        print(f"  [{processed+1}/{total}] {venue} {r}R ({race_id}) の推論を開始します... (期待値: {expected_value:.2f})", flush=True)
        start_time = time.time()
        
        racer_info = []
        for _, row in group.iterrows():
            lane = int(row['Lane'])
            pid = str(row['PlayerID'])
            base_info = f"{lane}号艇: {row['Name']} (モーター:{row['Motor']}, ランク:{row['Rank']}, 全国勝率:{row['WinRate']})"
            
            # コース別成績の追加
            if pid in stats_dict:
                s = stats_dict[pid]
                c_win = s.get(f'C{lane}_Win', 0)
                c_2in = s.get(f'C{lane}_2in', 0)
                c_3in = s.get(f'C{lane}_3in', 0)
                course_info = f" [当コース実績: 1着率{c_win}%, 2連率{c_2in}%, 3連率{c_3in}%]"
                base_info += course_info
            
            racer_info.append(base_info)
        prompt_data = "\n".join(racer_info)

        # 1. 統合天才AIによる推論（1回で済ませる）
        print("    -> 統合天才AI 深い自問自答中...", end=" ", flush=True)
        
        # LightGBM確率をプロンプトに反映
        race_probs = lgb_probs_map.get(str(race_id))
        if race_probs is not None:
            prob_lines = [f"{i+1}号艇: {race_probs[i]*100:.1f}%" for i in range(min(6, len(race_probs)))]
            lgb_probs_str = f"【LightGBM算出1着確率】: {', '.join(prob_lines)}。総合スコア {expected_value:.3f}"

            # 3連単確率推定: 3モデル利用可能なら高精度版、なければ1着モデルのみの簡易版
            race_probs_2nd = lgb_probs_2nd_map.get(str(race_id))
            race_probs_3rd = lgb_probs_3rd_map.get(str(race_id))

            if race_probs_2nd is not None and race_probs_3rd is not None:
                # Phase 2: 3モデルによる高精度3連単確率推定
                prob_2nd_lines = [f"{i+1}号艇: {race_probs_2nd[i]*100:.1f}%" for i in range(6)]
                prob_3rd_lines = [f"{i+1}号艇: {race_probs_3rd[i]*100:.1f}%" for i in range(6)]
                lgb_probs_str += f"\n【LightGBM算出2着確率】: {', '.join(prob_2nd_lines)}"
                lgb_probs_str += f"\n【LightGBM算出3着確率】: {', '.join(prob_3rd_lines)}"

                top_combos = estimate_trifecta_probs(race_probs, race_probs_2nd, race_probs_3rd, top_n=10)
                if top_combos:
                    ev_hint_lines = [f"  {c}: 推定確率{p*100:.2f}%" for c, p in top_combos]
                    lgb_probs_str += f"\n【3モデル統合 有力3連単候補（確率順）】\n" + "\n".join(ev_hint_lines)
                    lgb_probs_str += "\n※朝バッチで実オッズを取得後、真のEVに更新されます"
            else:
                # フォールバック: 1着モデルのみの簡易3連単確率
                top3_combos = []
                sorted_boats = sorted(range(6), key=lambda x: race_probs[x], reverse=True)
                for i_idx in range(min(3, len(sorted_boats))):
                    for j_idx in range(min(4, len(sorted_boats))):
                        for k_idx in range(min(5, len(sorted_boats))):
                            bi = sorted_boats[i_idx]
                            bj = sorted_boats[j_idx]
                            bk = sorted_boats[k_idx]
                            if bi == bj or bi == bk or bj == bk:
                                continue
                            p_i = race_probs[bi]
                            denom_j = max(1.0 - p_i, 1e-10)
                            p_j = race_probs[bj] / denom_j
                            denom_k = max(1.0 - p_i - race_probs[bj], 1e-10)
                            p_k = race_probs[bk] / denom_k
                            prob = p_i * p_j * p_k
                            if prob > 0.001:
                                top3_combos.append((f"{bi+1}-{bj+1}-{bk+1}", prob))

                top3_combos.sort(key=lambda x: x[1], reverse=True)
                if top3_combos:
                    ev_hint_lines = [f"  {c}: 推定確率{p*100:.1f}%" for c, p in top3_combos[:5]]
                    lgb_probs_str += f"\n【AI推定 有力3連単候補（1着モデルのみ・確率順）】\n" + "\n".join(ev_hint_lines)
                    lgb_probs_str += "\n※朝バッチで実オッズを取得後、真のEVに更新されます"
        else:
            lgb_probs_str = f"【簡易スコア】: 総合スコア {expected_value:.2f}（LightGBMデータ不足のため勝率ベース）"
        
        # Phase 3: レース条件に合致する教訓を優先取得
        bi_info = bi_dict.get(str(race_id), {})
        race_weather = str(bi_info.get('Weather', '')).strip()
        race_wind_level = classify_wind_level(bi_info.get('WindSpeed', ''))
        lessons = get_relevant_lessons(
            venue=venue,
            weather=race_weather,
            wind_level=race_wind_level,
            max_count=5
        )
        lessons_str = ""
        if lessons:
            lessons_str = "\n".join([f"・{l}" for l in lessons])

        prompt_genius = f"""あなたは日本最高峰の天才舟券師AIです。
以下のデータと専門知識をもとに、期待値を最大化する結論を導き出してください。

{lgb_probs_str}

【出走表】
{prompt_data}

【専門家の勝負鉄則】
{knowledge_str}
"""
        # 条件フィルタ付き教訓をプロンプトに追加
        if lessons_str:
            prompt_genius += f"""
【重要：過去の反省点（この会場・条件に関連する教訓を優先選択済み）】
{lessons_str}
"""
        prompt_genius += """
出力形式は必ず以下を守ってください：
■展開予想と推奨理由
...
■最終推奨買い目
（1-2-3, 1-3-2 のように買い目のみを記載）"""
        
        judge_response = call_deepseek(prompt_genius)
        print("完了")
        
        elapsed = time.time() - start_time
        log_text = f"【天才AI 統合推論ログ】\n{judge_response}"
        
        new_preds.append({
            "RaceID": race_id,
            "Date": date_val,
            "Venue": venue,
            "R": r,
            "Prediction": judge_response,
            "Log": log_text
        })
        
        processed += 1
        print(f"  -> 分析時間: {elapsed:.0f}秒\n", flush=True)

        # こまめに保存（CSV + DB）
        df_pred = pd.concat([df_pred, pd.DataFrame([new_preds[-1]])], ignore_index=True)
        save_data(df_pred, PRED_FILE)
        if db.db_exists():
            db.insert_prediction(race_id, date_val, venue, r, judge_response, log_text)

    print(f"  予測完了: 新規 {processed} 件")

# =========================================================
# Phase 2: 反省会フェーズ (マルチエージェント)
# =========================================================
def run_reflection():
    print("\n=== Phase 2: 昨日の予測の反省会（自動自己改善） ===", flush=True)
    df_pred = load_data(PRED_FILE)
    df_res = load_data(RES_FILE)

    if df_pred.empty or df_res.empty:
        print("  > 予測データまたは結果データがありません。")
        return

    df_refl = load_data(REFL_FILE)
    if df_refl.empty:
        df_refl = pd.DataFrame(columns=["RaceID", "Date", "Venue", "Weather", "WindLevel", "Lesson"])

    # 既存データにVenue/Weather/WindLevelカラムがなければ追加（後方互換）
    for col in ['Venue', 'Weather', 'WindLevel']:
        if col not in df_refl.columns:
            df_refl[col] = ''

    reflected_ids = set(df_refl['RaceID'].astype(str).unique()) if not df_refl.empty else set()

    # 予測があり、かつ結果データが存在し、まだ反省していないレースを探す
    # 重複回避処理を追加
    df_res_unique = df_res.drop_duplicates(subset=['ID'], keep='last')
    res_dict = df_res_unique.set_index('ID')[['Result', 'Payout']].to_dict('index')

    # 直前情報から天候・風速を取得するための辞書を構築
    bi_condition_dict = {}  # race_id → {Weather, WindSpeed, WindLevel, Venue}
    df_bi = load_data(BI_FILE)
    if not df_bi.empty:
        for _, bi_row in df_bi.iterrows():
            bi_id = str(bi_row.get('ID', ''))
            if bi_id and bi_id not in bi_condition_dict:
                weather_val = str(bi_row.get('Weather', '')).strip()
                wind_speed = bi_row.get('WindSpeed', '')
                wind_level = classify_wind_level(wind_speed)
                venue_val = str(bi_row.get('Venue', '')).strip()
                bi_condition_dict[bi_id] = {
                    'Weather': weather_val,
                    'WindLevel': wind_level,
                    'Venue': venue_val
                }

    new_refls = []
    processed = 0

    for _, row in df_pred.iterrows():
        if processed >= 10:
            print("  > 過去の未反省データが多数存在するため、本日は最新10件で反省処理を打ち切ります。", flush=True)
            break

        race_id = str(row['RaceID'])
        if race_id in reflected_ids:
            continue

        if race_id in res_dict:
            # 反省会実施
            prediction = str(row['Prediction'])
            actual_res = res_dict[race_id]['Result']
            actual_pay = res_dict[race_id]['Payout']

            # 条件情報の取得（直前情報から）
            conditions = bi_condition_dict.get(race_id, {})
            venue = conditions.get('Venue', str(row.get('Venue', '')))
            weather = conditions.get('Weather', '')
            wind_level = conditions.get('WindLevel', 'unknown')

            print(f"  [{race_id}] の反省会を開始... (会場:{venue}, 天候:{weather}, 風:{wind_level})", flush=True)

            # 天候・風情報もプロンプトに含めてより具体的な教訓を引き出す
            condition_text = ""
            if weather or wind_level != 'unknown':
                condition_parts = []
                if weather:
                    condition_parts.append(f"天候: {weather}")
                if wind_level != 'unknown':
                    wind_label = {'calm': '弱風(0-2m)', 'moderate': '中風(3-5m)', 'strong': '強風(6m+)'}
                    condition_parts.append(f"風: {wind_label.get(wind_level, wind_level)}")
                condition_text = f"\n【レース条件】\n会場: {venue}, {', '.join(condition_parts)}"

            print("    -> 統合反省会AI 分析中...", end=" ", flush=True)
            prompt_lesson = f"""あなたはボートレースの最高峰システム改善分析官です。
以下のAIの「予測」と実際の「結果（答え）」を比較し、なぜその結果になったのか（モーター機力の見誤りか、展開・風の影響か等）を脳内で瞬時に自問自答し、システム改善の「教訓」を1行で抽出してください。
{condition_text}

【AIの予測】
{prediction[:300]}

【実際の結果】
{actual_res} ({actual_pay}円)

出力形式は必ず以下を守ってください：
「教訓: 〜」のみを出力"""
            lesson_response = call_deepseek(prompt_lesson)
            print("完了")

            new_refls.append({
                "RaceID": race_id,
                "Date": row['Date'],
                "Venue": venue,
                "Weather": weather,
                "WindLevel": wind_level,
                "Lesson": lesson_response
            })

            processed += 1
            print(f"  -> 反省完了\n", flush=True)

            # こまめに保存（CSV + DB）
            df_refl = pd.concat([df_refl, pd.DataFrame([new_refls[-1]])], ignore_index=True)
            save_data(df_refl, REFL_FILE)
            if db.db_exists():
                db.insert_reflection(race_id, row['Date'], venue, weather, wind_level, lesson_response)

    print(f"  反省会完了: 新規 {processed} 件")

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    run_predictions()
    run_reflection()
    print("=== 全処理完了 ===")

if __name__ == "__main__":
    main()
