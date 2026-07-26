"""
Phase 5: LightGBMモデル自動再学習スクリプト（本番版）
毎日蓄積される正解データ（daily_data）をpast_dataに統合し、
モデルを再学習してA/Bテストで精度向上を確認した場合のみ自動アップデートする。
Phase 4: SQLite対応 — daily_data を DB にも挿入する。
"""
import os
import shutil
import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from datetime import datetime, timedelta, timezone
import database as db
from det_feature_schema import select_live_features

# --- 設定 ---
DAILY_DIR = "daily_data"
PAST_DIR = "past_data"
MODEL_DIR = "models"
MODEL_FILE = os.path.join(MODEL_DIR, "lgb_model_1st.txt")
MODEL_BACKUP = os.path.join(MODEL_DIR, "lgb_model_1st_backup.txt")
MODEL_FILE_2ND = os.path.join(MODEL_DIR, "lgb_model_2nd.txt")
MODEL_BACKUP_2ND = os.path.join(MODEL_DIR, "lgb_model_2nd_backup.txt")
MODEL_FILE_3RD = os.path.join(MODEL_DIR, "lgb_model_3rd.txt")
MODEL_BACKUP_3RD = os.path.join(MODEL_DIR, "lgb_model_3rd_backup.txt")

# daily_data のファイル
DAILY_PROG = os.path.join(DAILY_DIR, "daily_raw_race_data.csv")
DAILY_RES = os.path.join(DAILY_DIR, "daily_history_results.csv")
DAILY_BI = os.path.join(DAILY_DIR, "daily_raw_beforeinfo.csv")
DAILY_ODDS = os.path.join(DAILY_DIR, "daily_odds_3t.csv")

# past_data のファイル
PAST_PROG = os.path.join(PAST_DIR, "past_race_data.csv")
PAST_RES = os.path.join(PAST_DIR, "past_history_results.csv")
PAST_BI = os.path.join(PAST_DIR, "past_raw_beforeinfo.csv")
PAST_ODDS = os.path.join(PAST_DIR, "past_odds_3t.csv")
FEATURES_FILE = os.path.join(PAST_DIR, "ml_features.csv")


def merge_daily_to_past():
    """daily_dataの新しいデータをpast_dataにマージする（CSV + DB両方に書き込む）"""
    print("\n--- Step 1: daily_data → past_data マージ ---")
    merged_count = 0

    # DB初期化
    db.ensure_db()

    file_pairs = [
        (DAILY_PROG, PAST_PROG, "出走表"),
        (DAILY_RES, PAST_RES, "結果"),
        (DAILY_BI, PAST_BI, "直前情報"),
        (DAILY_ODDS, PAST_ODDS, "オッズ"),
    ]

    # DB挿入用のマッピング
    db_table_map = {
        "出走表": ("races", db.RACE_COLUMNS),
        "結果": ("results", db.RESULT_COLUMNS),
        "直前情報": ("beforeinfo", db.BEFOREINFO_COLUMNS),
        "オッズ": ("odds", db.ODDS_COLUMNS),
    }

    for daily_file, past_file, label in file_pairs:
        if not os.path.exists(daily_file):
            print(f"  [{label}] daily_data に {os.path.basename(daily_file)} がありません。スキップ。")
            continue

        df_daily = pd.read_csv(daily_file)
        if df_daily.empty:
            print(f"  [{label}] daily_data は空です。スキップ。")
            continue

        if os.path.exists(past_file):
            df_past = pd.read_csv(past_file)
            # IDベースで重複を排除してマージ
            id_col = 'ID' if 'ID' in df_daily.columns else df_daily.columns[0]
            existing_ids = set(df_past[id_col].astype(str).unique()) if id_col in df_past.columns else set()
            df_new = df_daily[~df_daily[id_col].astype(str).isin(existing_ids)]

            if df_new.empty:
                print(f"  [{label}] 新規データなし（全て既存）。スキップ。")
                continue

            df_merged = pd.concat([df_past, df_new], ignore_index=True)
            df_merged.to_csv(past_file, index=False, encoding='utf-8')
            print(f"  [{label}] {len(df_new)} 件の新規データをマージしました。（合計: {len(df_merged)} 件）")
            merged_count += len(df_new)
        else:
            # past_data にファイルが無い場合はコピー
            df_daily.to_csv(past_file, index=False, encoding='utf-8')
            print(f"  [{label}] past_data に新規作成。（{len(df_daily)} 件）")
            merged_count += len(df_daily)

        # DBにも挿入（ON CONFLICT IGNORE で重複スキップ）
        if label in db_table_map:
            table, columns = db_table_map[label]
            df_db = df_daily.rename(columns={"ID": "RaceID"}) if "ID" in df_daily.columns else df_daily
            for col in columns:
                if col not in df_db.columns:
                    df_db[col] = ''
            rows = df_db[columns].fillna('').values.tolist()
            db.insert_rows(table, columns, rows)

    return merged_count


def rebuild_features():
    """build_features.py のロジックを呼び出して特徴量を再計算する"""
    print("\n--- Step 2: 特徴量再計算 (build_features) ---")
    try:
        import build_features
        build_features.main()
        if os.path.exists(FEATURES_FILE):
            df = pd.read_csv(FEATURES_FILE)
            print(f"  特徴量データセット: {len(df)} 件")
            return True
        else:
            print("  [ERROR] ml_features.csv が生成されませんでした。")
            return False
    except Exception as e:
        print(f"  [ERROR] 特徴量再計算に失敗: {e}")
        return False


def _get_feature_and_target(target_col):
    """特徴量とターゲットを取得する共通関数"""
    if not os.path.exists(FEATURES_FILE):
        return None, None, None, None

    df = pd.read_csv(FEATURES_FILE)
    df = df.dropna(subset=[target_col])

    exclude_cols = ['ID', 'Date', 'Venue', 'Weather', 'WindDir', 'Result', 'Payout',
                    'Target_1st', 'Target_2nd', 'Target_3rd']
    numeric_cols = [c for c in df.columns if c not in exclude_cols and df[c].dtype in ['int64', 'float64']]
    feature_cols = select_live_features(numeric_cols)
    if not feature_cols:
        raise ValueError("本番互換のDet特徴量が見つかりません")

    X = df[feature_cols]
    y = df[target_col].astype(int) - 1  # 0-indexed (0-5)
    dates = pd.to_datetime(df['Date'], errors='coerce')
    return X, y, feature_cols, dates


def temporal_train_test_split(X, y, dates, test_ratio=0.2):
    """未来のレースを学習に混ぜない、時系列順の検証分割。"""
    order = dates.fillna(pd.Timestamp.min).sort_values(kind='stable').index
    X_sorted = X.loc[order]
    y_sorted = y.loc[order]
    split_at = max(1, int(len(X_sorted) * (1 - test_ratio)))
    if split_at >= len(X_sorted):
        split_at = len(X_sorted) - 1
    return X_sorted.iloc[:split_at], X_sorted.iloc[split_at:], y_sorted.iloc[:split_at], y_sorted.iloc[split_at:]


def train_single_model(target_col, label):
    """指定したターゲットカラムで1つのモデルを学習する"""
    X, y, feature_cols, dates = _get_feature_and_target(target_col)
    if X is None:
        print(f"  [ERROR] {label}: 学習データが見つかりません。")
        return None, 0

    print(f"  [{label}] 学習データ: {len(X)} 件")

    X_train, X_test, y_train, y_test = temporal_train_test_split(X, y, dates)

    train_data = lgb.Dataset(X_train, label=y_train)
    test_data = lgb.Dataset(X_test, label=y_test, reference=train_data)

    params = {
        'objective': 'multiclass',
        'num_class': 6,
        'metric': 'multi_error',
        'boosting_type': 'gbdt',
        'learning_rate': 0.05,
        'num_leaves': 31,
        'verbose': -1
    }

    model = lgb.train(
        params,
        train_data,
        num_boost_round=200,
        valid_sets=[train_data, test_data],
        callbacks=[lgb.early_stopping(stopping_rounds=20), lgb.log_evaluation(0)]
    )

    y_pred_probs = model.predict(X_test)
    y_pred = np.argmax(y_pred_probs, axis=1)
    accuracy = accuracy_score(y_test, y_pred)
    print(f"  [{label}] [HIT] 的中率: {accuracy * 100:.2f}%")

    return model, accuracy


def evaluate_saved_model(model_file, target_col, label):
    """指定済みモデルを、現在の時系列ホールドアウトで評価する。"""
    if not os.path.exists(model_file):
        print(f"  [{label}] 旧モデルが存在しません。新モデルを無条件で採用します。")
        return 0

    X_live, y, feature_cols, dates = _get_feature_and_target(target_col)
    if X_live is None:
        return 0

    try:
        old_model = lgb.Booster(model_file=model_file)
        old_features = old_model.feature_name()
        # 旧モデルは旧スキーマ（例: 202列）で学習済み。本番互換スキーマへ
        # 切り替えた後でも、旧モデルの列数・列順を保って公平に比較する。
        raw = pd.read_csv(FEATURES_FILE)
        raw = raw.dropna(subset=[target_col])
        raw_dates = pd.to_datetime(raw['Date'], errors='coerce')
        X_legacy = raw.reindex(columns=old_features, fill_value=0).apply(pd.to_numeric, errors='coerce').fillna(0)
        _, X_test_old, _, y_test = temporal_train_test_split(X_legacy, y, raw_dates)
        missing = [f for f in old_features if f not in raw.columns]
        if missing:
            print(f"  [{label}] [INFO] 旧専用の欠損特徴 {len(missing)} 件は0で補完して比較")
        y_pred_probs = old_model.predict(X_test_old)
        y_pred = np.argmax(y_pred_probs, axis=1)
        accuracy = accuracy_score(y_test, y_pred)
        print(f"  [{label}] [OLD] 旧モデル的中率: {accuracy * 100:.2f}%")
        return accuracy
    except Exception as e:
        print(f"  [{label}] [WARN] 旧モデル評価失敗: {e}")
        return 0


def evaluate_old_single_model(model_file, target_col, label):
    """後方互換用: 旧モデルの精度を評価する。"""
    return evaluate_saved_model(model_file, target_col, label)


def train_new_model():
    """1着予測モデルを学習（後方互換）"""
    print("\n--- Step 3: 新モデルの学習 ---")
    return train_single_model('Target_1st', '1着予測')


def evaluate_old_model():
    """旧1着予測モデルの評価（後方互換）"""
    print("\n--- Step 4: 旧モデルとのA/Bテスト ---")
    return evaluate_old_single_model(MODEL_FILE, 'Target_1st', '1着予測')


def main():
    """
    Phase 5: LightGBMモデル自動再学習プロセス
    1. daily_data → past_data にマージ
    2. 特徴量を再計算（build_features）
    3. 新モデルを学習（train_model のロジック）
    4. 旧モデルとA/Bテスト比較
    5. 新モデルが優れていれば自動アップデート
    """
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    print(f"=== Phase 5: AIモデル自動再学習プロセス 開始 ===")
    print(f"実行時刻: {now.strftime('%Y-%m-%d %H:%M:%S')} JST")

    os.makedirs(MODEL_DIR, exist_ok=True)

    # Step 1: データマージ
    merged = merge_daily_to_past()
    if merged == 0:
        print("\n新規データがありません。再学習をスキップします。")
        print("--- 自動再学習プロセス 完了（スキップ） ---")
        return

    # Step 2: 特徴量再計算
    if not rebuild_features():
        print("\n[ERROR] 特徴量再計算に失敗したため、再学習を中止します。")
        return

    # Step 3: 新モデル学習
    new_model, new_accuracy = train_new_model()
    if new_model is None:
        print("\n[ERROR] モデル学習に失敗しました。")
        return

    # Step 4: 旧モデルとA/Bテスト
    old_accuracy = evaluate_old_model()

    # Step 5: 1着モデルの更新判定
    print("\n--- Step 5: モデル更新判定 ---")
    _update_model_if_better(new_model, new_accuracy, old_accuracy, MODEL_FILE, MODEL_BACKUP, "1着予測")

    # ─── Step 6: 2着予測モデル ───
    print("\n--- Step 6: 2着予測モデルの学習 ---")
    new_model_2nd, new_acc_2nd = train_single_model('Target_2nd', '2着予測')
    if new_model_2nd is not None:
        old_acc_2nd = evaluate_old_single_model(MODEL_FILE_2ND, 'Target_2nd', '2着予測')
        _update_model_if_better(new_model_2nd, new_acc_2nd, old_acc_2nd, MODEL_FILE_2ND, MODEL_BACKUP_2ND, "2着予測")

    # ─── Step 7: 3着予測モデル ───
    print("\n--- Step 7: 3着予測モデルの学習 ---")
    new_model_3rd, new_acc_3rd = train_single_model('Target_3rd', '3着予測')
    if new_model_3rd is not None:
        old_acc_3rd = evaluate_old_single_model(MODEL_FILE_3RD, 'Target_3rd', '3着予測')
        _update_model_if_better(new_model_3rd, new_acc_3rd, old_acc_3rd, MODEL_FILE_3RD, MODEL_BACKUP_3RD, "3着予測")

    print(f"\n--- 自動再学習プロセス 完了 ---")


def _update_model_if_better(new_model, new_accuracy, old_accuracy, model_file, backup_file, label):
    """新モデルが旧モデルより良ければ更新する"""
    improvement = (new_accuracy - old_accuracy) * 100
    print(f"\n  [{label}] 新: {new_accuracy*100:.2f}% / 旧: {old_accuracy*100:.2f}%")

    if new_accuracy > old_accuracy:
        if os.path.exists(model_file):
            shutil.copy2(model_file, backup_file)
            print(f"  [{label}] [BACKUP] 旧モデルをバックアップ")
        new_model.save_model(model_file)
        print(f"  [{label}] [UPDATE] 自動アップデート (+{improvement:.2f}%)")
    elif new_accuracy == old_accuracy:
        if os.path.exists(model_file):
            shutil.copy2(model_file, backup_file)
        new_model.save_model(model_file)
        print(f"  [{label}] [REFRESH] 同精度のため新データモデルに更新")
    else:
        print(f"  [{label}] [SKIP] アップデート見送り ({improvement:.2f}%)")


if __name__ == "__main__":
    main()
