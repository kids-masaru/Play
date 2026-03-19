import os
import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
import matplotlib.pyplot as plt

# --- 設定 ---
INPUT_FILE = os.path.join("past_data", "ml_features.csv")
MODEL_DIR = "models"
MODEL_FILE = os.path.join(MODEL_DIR, "lgb_model_1st.txt")

def main():
    print("=== Phase 3: LightGBM 予測モデル学習テスト開始 ===")
    
    if not os.path.exists(INPUT_FILE):
        print(f"エラー: 学習データ {INPUT_FILE} が見つかりません。先に build_features.py を実行してください。")
        return
        
    os.makedirs(MODEL_DIR, exist_ok=True)

    # 1. データの読み込み
    print(f"[{INPUT_FILE}] を読み込んでいます...")
    df = pd.read_csv(INPUT_FILE)
    print(f"全データ件数: {len(df)} 件")

    # 欠損値（欠けているデータ）がある行を一旦削除（※後で補完処理を入れるとさらに良くなります）
    df = df.dropna(subset=['Target_1st'])
    
    # 2. 特徴量（X）と 正解ラベル（y）に分ける
    # 教師データに使わない列（IDや日付、文字の列）を除外
    exclude_cols = ['ID', 'Date', 'Venue', 'Weather', 'WindDir', 'Result', 'Payout', 'Target_1st']
    # 文字列の列は自動で除外
    feature_cols = [c for c in df.columns if c not in exclude_cols and df[c].dtype in ['int64', 'float64']]
    
    print("\n[使用する特徴量（AIに教える項目）]")
    print(", ".join(feature_cols[:10]) + " ...など全 " + str(len(feature_cols)) + " 項目")

    X = df[feature_cols]
    y = df['Target_1st'].astype(int) - 1  # LightGBM分類は0から始まる必要があるので (1着=0, 2着=1...) に変換

    # 3. データを「学習用(80%)」と「テスト用(20%)」に分割する
    # これにより、AIが答えを丸暗記していないか（カンニング検証）をテストできる
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    print(f"\n学習データ: {len(X_train)}件, テストデータ: {len(X_test)}件")

    # 4. LightGBMモデルの構築と学習
    # LightGBM用のデータセット枠を作成
    train_data = lgb.Dataset(X_train, label=y_train)
    test_data = lgb.Dataset(X_test, label=y_test, reference=train_data)

    # AIの脳みその設定（ハイパーパラメータ）
    params = {
        'objective': 'multiclass',  # 多クラス分類（1〜6着のどれかを当てる）
        'num_class': 6,             # 6艇
        'metric': 'multi_error',    # 誤差の測り方
        'boosting_type': 'gbdt',
        'learning_rate': 0.05,
        'num_leaves': 31,
        'verbose': -1               # 余計なログを消す
    }

    print("\nモデルの学習を開始します（数秒〜数十秒かかります）...")
    # 実際はデータ数万件でも一瞬で終わるのがLightGBMの強み
    model = lgb.train(
        params,
        train_data,
        num_boost_round=200,                # 勉強する回数（木の数）
        valid_sets=[train_data, test_data], # 勉強しながらテストで答え合わせをする
        callbacks=[lgb.early_stopping(stopping_rounds=20)] # 成長が止まったら途中で勉強を打ち切る
    )

    # 5. モデルの精度テスト（バックテスト）
    print("\n=== テストデータで実際の予測精度を検証 ===")
    
    # 予測の実行（出力は、各艇が1着になる [確率] のリストになる）
    y_pred_probs = model.predict(X_test)
    
    # 確率が一番高い艇番（インデックス）を取り出す
    y_pred = np.argmax(y_pred_probs, axis=1)
    
    # 人間が見やすいように 1〜6着 に戻す
    y_test_display = y_test + 1
    y_pred_display = y_pred + 1
    
    accuracy = accuracy_score(y_test_display, y_pred_display)
    print(f"🎯 1着的中率 (Accuracy): {accuracy * 100:.2f} %")
    
    # 各コース別の的中率詳細
    print("\n[コース別の結果]")
    print(classification_report(y_test_display, y_pred_display))

    # 6. 特徴量の重要度分析（AIは何を見て判断したか？）
    print("=== AIが重視したデータ ランキング TOP 10 ===")
    importance = model.feature_importance(importance_type='gain')
    feature_importance = pd.DataFrame({'Feature': feature_cols, 'Importance': importance})
    feature_importance = feature_importance.sort_values(by='Importance', ascending=False).head(10)
    for idx, row in enumerate(feature_importance.itertuples()):
        print(f"{idx+1}位: {row.Feature} (スコア: {row.Importance:.0f})")

    # 7. モデルの保存
    model.save_model(MODEL_FILE)
    print(f"\nモデルを保存しました: {MODEL_FILE}")
    print("本番データが集まったら、もう一度このスクリプトを実行するだけで最強モデルが完成します！")

if __name__ == "__main__":
    main()
