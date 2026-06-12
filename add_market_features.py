"""オッズ歪み特徴量 (B{1-6}_MarketProb) を ml_features.csv に追加。

各レースで、3連単オッズから「艇 i が 1着になる市場暗黙確率」を集約計算:
  暗黙確率の総和 = Σ_全120組合せ (1/odds)
  艇 i の市場確率 = (Σ_{j≠i, k≠i,k≠j} 1/odds(i-j-k)) / 総和

これで6艇の市場確率は sum=1 に正規化される (控除率25%は相殺)。

オッズが無い期間/レース (2024年大半など) は NaN で埋める。
LightGBMは NaN を扱えるので学習に支障なし。
"""
import os
import shutil
import time
import pandas as pd
import numpy as np

FEATURES_FILE = os.path.join("past_data", "ml_features.csv")
ODDS_FILE = os.path.join("past_data", "past_odds_3t.csv")
BACKUP_FILE = os.path.join("past_data", "ml_features_pre_market.csv")


def main():
    t0 = time.time()
    print("[1/4] バックアップ作成...")
    if not os.path.exists(BACKUP_FILE):
        shutil.copy2(FEATURES_FILE, BACKUP_FILE)
        print(f"    {FEATURES_FILE} -> {BACKUP_FILE}")
    else:
        print(f"    既存バックアップあり: {BACKUP_FILE}")

    print("[2/4] オッズデータ読み込み・市場確率集約...")
    odds = pd.read_csv(ODDS_FILE, usecols=["ID", "Combination", "Odds"])
    odds = odds[odds["Odds"] > 0].copy()
    # 1着艇番号
    odds["First"] = odds["Combination"].str.split("-").str[0].astype(int)
    odds["InvOdds"] = 1.0 / odds["Odds"]

    print(f"    オッズレコード: {len(odds):,}")

    # レース毎に集約
    agg = odds.groupby(["ID", "First"], as_index=False)["InvOdds"].sum()
    total = odds.groupby("ID", as_index=False)["InvOdds"].sum().rename(columns={"InvOdds": "Total"})
    agg = agg.merge(total, on="ID")
    agg["MarketProb"] = agg["InvOdds"] / agg["Total"]

    # wide format: 1行 = 1レース、B1_MarketProb...B6_MarketProb
    wide = agg.pivot_table(index="ID", columns="First", values="MarketProb", fill_value=np.nan).reset_index()
    wide.columns = ["ID"] + [f"B{i}_MarketProb" for i in wide.columns[1:]]
    # 念のため全列存在保証
    for i in range(1, 7):
        col = f"B{i}_MarketProb"
        if col not in wide.columns:
            wide[col] = np.nan
    wide = wide[["ID"] + [f"B{i}_MarketProb" for i in range(1, 7)]]
    print(f"    市場確率を持つレース数: {len(wide):,}")

    print("[3/4] ml_features.csv とマージ...")
    feat = pd.read_csv(FEATURES_FILE)
    print(f"    既存shape: {feat.shape}")
    # IDで left join (オッズ無いレースは NaN)
    feat = feat.merge(wide, on="ID", how="left")
    n_with = feat["B1_MarketProb"].notna().sum()
    n_without = feat["B1_MarketProb"].isna().sum()
    print(f"    市場確率付きレース: {n_with:,}")
    print(f"    NaN(オッズなし): {n_without:,}")
    print(f"    新shape: {feat.shape}")

    print("[4/4] 上書き保存...")
    tmp = FEATURES_FILE + ".tmp"
    feat.to_csv(tmp, index=False)
    os.replace(tmp, FEATURES_FILE)
    print(f"    出力: {FEATURES_FILE} ({os.path.getsize(FEATURES_FILE)/1024/1024:.1f} MB)")
    print(f"\n完了 ({time.time()-t0:.1f}s)")


if __name__ == "__main__":
    main()
