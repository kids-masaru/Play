# 自己改善ループ 試行候補リスト

## 最終更新: 2026-05-12

リーク修正後の build_features.py の盤面で、優先度順に試行する特徴量候補を整理する。
過去 293 試行 (`results_legacy_pre_leak_fix.tsv`) はリーク前提のスコアだったため、ここでは「再評価候補」として扱う (リーク後にも効くかは未知)。

## ステータス凡例
- 🔁 リーク前提で「効いた」とされた → リーク修正後で再評価
- 🆕 未試行アイデア (新規)
- ❌ catastrophic 履歴あり → 慎重に
- ✅ リーク修正後セッション (4/27) でコミット済 → 既に build_features.py に組み込み済み

---

## 優先度 高 (まず試す候補、10件)

### 1. 🆕 直近N走のフォーム指標 (leak-safe実装)
- B*_RecentWinRate_5 / B*_RecentWinRate_10 (各艇の直近N走の勝率)
- 注意: `build_features.py` の `_compute_leak_safe_player_stats` の累積方式で実装し、各レース時点の直近Nレースのみ集計
- 効きそうな理由: career累積より「今のフォーム」を反映、競艇でよく使われる指標
- 過去: RecentWinRate20 (tr 198) は catastrophic だったが、リーク前提だった → leak-safe で再挑戦価値あり

### 2. 🔁 Race_Min_Career2inRate
- レース内最低キャリア2着率
- 過去: trial #260 で +18.15 という大幅改善
- リーク前提だったが、Race集約系は本来リーク影響少 → 再現可能性高い

### 3. 🔁 Race_N_BottomTier (RankScore=1 の艇数)
- 過去: trial #279 で +10.48 改善 ★大幅
- RankScore は当日固定値でリーク無し → 効果再現の可能性大

### 4. 🆕 時間帯特徴 (発走時刻)
- R + 会場の発走時刻 → 「夜レース」「準優勝戦のR12」など時間軸の偏り
- まだ全く触られてない次元 (notes.md 4/27 セッションで指摘あり)

### 5. 🔁 B*_VenueLanePWR_Bayes (Bayesian smoothed VenueLanePWinRate)
- 過去: trial #99 で +1.8 (リーク前提)
- 会場×コース固有勝率はDB集計だが、leak-safe 化済みなのでバイアス低減期待

### 6. 🆕 ExTime ratio features
- B*_ExTime / Race_Min_ExTime (最速艇に対する相対モーター速度)
- vs_Min は数値特徴で既にあるが、ratio はまだ無い
- LightGBM は ratio で別パターンを掴むことがある

### 7. 🔁 B*_VenueLanePR_x_ExAdv (venue-lane mastery × 速いモーター)
- 過去: trial #91 +0.07 (リーク前提)
- 会場×コース固有 + 当日モーター速度の compound

### 8. 🆕 odds_to_prob 比較系 (実オッズが推測される直前情報)
- LightGBM 確率と「市場合意」(rank order が分かれば良い) の不一致を特徴化
- 直前情報の「展示タイム」「気象」が変わる前のレース直後のbias を埋め込む

### 9. 🆕 出目バイアス系 (会場×コース)
- 過去N年の会場×コース固有1着率の divergence from naive 6-equal-prior
- HHI/Gini 系は catastrophic だった (notes.md) が、prior 比較なら別物として効くかも

### 10. 🔁 Race_Min_RankScore
- リーク後セッション #7 で +0.05 採用済 ✅
- 既に組み込まれているので「派生展開」: Race_Min_RankScore_x_N_BottomTier 等

---

## 優先度 中 (次に試す候補、10件)

### 11. 🆕 B*_Tilt 全レーン展開
- 現状 B1 vs 外艇のみ実装 (notes.md 4/27)
- B2-B6 も B*_Tilt 数値化 + B*_Tilt_vs_AvgOuter を全レーン

### 12. 🔁 B*_VenueWinRate (会場固有勝率)
- 過去 #73 で +22.65 (リーク前提)
- 会場×プレイヤー集計だが leak-safe なら効くかも

### 13. 🔁 B*_Career2inRate / Career3inRate (キャリア2/3着率)
- 過去 #78 で +14.95 (リーク前提)
- キャリア累積系で leak-safe 実装済みなので再現可能性中

### 14. 🆕 「逃げ予測信号」系
- B1 単独で勝てそうな条件のbinary集約: WinRate_Top1 AND ExTime_Rank=1 AND CourseWin>0.4
- 過去 #251 B1_Absolute_Dominance は catastrophic だったが、より弱い条件で組めば違う可能性

### 15. 🆕 Inner-Outer 配分
- Race内の InnerLanes(1-3) と OuterLanes(4-6) の WR/ExTime 配分指数
- per-pair diff は既にあるが、3-vs-3 グループ集約は未開拓

### 16. 🔁 B*_Course_2in_Rank (コース別2着率順位)
- 過去 #36 で +1.99 (リーク前提)
- コース別実績は出走表データなのでリークほぼなし → 効く可能性高

### 17. 🆕 履歴のレース間相関
- 同じ艇 (PlayerID×Venue) の直近2レース勝敗パターン (連勝中 / 連敗中)
- leak-safe 実装で「過去N走の勝率推移」

### 18. 🆕 Bayesian shrinkage の係数調整
- VenueLanePWR の Bayesian smoothing α を 5→10, 20 で振ってみる
- 現状 α=5 で trial #99 で効いてる、もっと安定する可能性

### 19. 🔁 ExTimeMin_vs_VenueAvg (会場平均比モーター速度)
- 過去 #80 で +3.06 (リーク前提)
- 会場固有のExTimeベンチマーク

### 20. 🆕 直前気象変化検知
- BeforeInfo の WindSpeed と当初予報の差 (気象変化率)
- BeforeInfo は当日のみだがリーク無し

---

## 優先度 低 / 慎重 (catastrophic履歴があるので注意)

### ❌ 危険ゾーン (過去 catastrophic、再試行非推奨)
- WinRate_Zscore (tr 209) - 200台に大崩れ
- Race_WinRate_Gini (tr 253), Race_Max_RankScore (tr 264) - スコア分布形状系
- ExTime_Skew (tr 255), B1_Absolute_Dominance (tr 251)
- Course2in×VenueWR (tr 226), Course_2in compound 多用
- 共通点: 「B1 過信を強化」「分布の高次モーメント」 → モデルが overconfident に走る

### ⚠️ 試行価値あり (条件付き)
- モーター系派生: df_motor のデータ充実待ち (現状ゼロ埋め)
- 高次インタラクション (3つ以上の積) は基本避ける

---

## 試行戦略 (新ループ向け)

1. **優先度高から順に1試行ずつ実行** → walk-forward でモデル精度評価
2. **コミット判定**: 主条件 (2年WF Brier 改善 + monthly_win_rate ≥ 60%) AND 副条件 (45日WF Det ROI 劣化 ≤ -10pt)
3. **同点判定**: モデルが特徴量を無視した可能性大、特徴量名を変えて深掘りするか別カテゴリへ
4. **catastrophic 判定 (Brier 大幅悪化)**: 即 revert、なぜそうなったか notes.md に記録
5. **10試行連続で更新無しなら停止** (旧ループの停止条件3を継承)

## 関連ファイル
- `auto_research/results.tsv` (新ベースライン以降の記録)
- `auto_research/results_legacy_pre_leak_fix.tsv` (リーク前提の旧記録、参考)
- `auto_research/notes.md` (セッション別の詳細学習ログ)
- `walkforward_spec.md` / `walkforward_task.md` (本タスクの仕様)
