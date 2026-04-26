# 自己改善ループ ノート

## 2026-04-27 セッション（trial 1-17、リーク修正後の新ベースライン）

### 結果サマリー
- 実行試行数: 17
- 終了理由: 停止条件 #3（直近10試行連続でベスト未更新、#8〜#17）
- セッション開始時ベスト: なし（results.tsv 空、リーク修正後に再構築開始）
- セッション終了時ベスト: **591.42**（trial #7: Race_Min_RankScore）
- 改善幅: 588.55 → 591.42（+2.87）
- コミット: **4件**（#1, #2, #3, #7）

### コミット済み改善（4件）
| 試行 | 変更 | スコア | 伸び |
|------|------|--------|------|
| #1 | Race_N_DoubleWeak (WR<3.0 AND RankScore=1) | 588.55 | （ベースライン） |
| #2 | Race_HasUnanimousFavorite (B1_Top_WR AND VeryWeakBoats>0) | 589.33 | +0.78 |
| #3 | B1_Tilt_vs_AvgOuter (self-exclusion in Tilt dimension) | 591.37 | +2.04 ★最大 |
| #7 | Race_Min_RankScore (Min は Max が破壊的だった中で別情報) | 591.42 | +0.05 |

### リーク修正後の知見（重要）
1. **スコアレンジが大幅低下**: legacy セッションでは 870-888 だったが、リーク修正後は 588-591 にシフト。
   時系列リークが含まれていた Career/Venue/VenueLane 系の信号が、未来情報を使えなくなり弱まった。
2. **Tilt dimension が最大の伸び**: 文字列カラムだった B*_Tilt を数値化し B1 vs 外艇平均で +2.04。
   未開拓次元の特徴量化が legacy 知見と独立に効く可能性を示唆。
3. **Race_Min_RankScore は微改善**: legacy 知見「Race_Max_RankScore は catastrophic」と一致して
   Min 側は安全。Race-level Min/Max のうち Min は概ね無害。

### 効かなかった試行
- Race_Mean_Tilt / Race_N_PositiveTilt（Tilt の集約系は Mean/Count 形式は効かない）
- Race_Median_Career3inRate / Race_Median_VenueLanePWinRate（Median は Career2in 以外で機能せず）
- B1_Weight_vs_AvgOuter（Weight 次元は Tilt と違って機能せず）
- Wave_Squared（legacy で +1.26 だったが、本セッションでは識別子完全同一 = 既存 Wave 特徴で吸収）
- Course_2in / Course_3in / Career3in の self-exclusion 版（Career2in 系列の不発と一致）
- Wave_vs_VenueAvg（環境異常シグナルだが効果薄）
- Race_N_Outer_RankScore_ge_B1 / Race_N_Outer_Better_CourseWin（脅威カウントの WR 以外版は効果薄）

### 次回のアイデア（未試行）
- **B*_Tilt の数値化を全レーンに適用してから探索**: 現状 B1 vs 外艇のみ実装。各レーンの Tilt 数値特徴を露出させると別の信号が見つかるかも。
- **Race-level バイナリ複合**: HasUnanimousFavorite が機能した。他の binary AND 候補（B1_Is_Top_WinRate AND Race_N_DoubleWeak>0 など）は未試行。
- **モーター系 motor_stats の活用検証**: df_motor が空だと特徴量はゼロ埋め。実 DB に motor_stats があれば再評価。
- **直近 N 走の動的特徴**: 過去セッションで catastrophic だったが、leak-safe な実装ならば再挑戦価値あり。
- **Header/before info の時間情報**: time_of_day（R + 会場の発走時刻）など時間軸特徴は未開拓。

## 2026-04-25 セッション（trial 249-270）

### 結果サマリー
- 実行試行数: 22（#249-#270）
- 終了理由: 停止条件 #3（直近10試行連続でセッションベスト未更新）
- セッション開始時ベスト: 823.90 (trial #238 Race_N_WeakBoats)
- セッションベスト: 823.90 → **872.30** (+48.40)
- コミット: **4件**

### セッションベスト更新
| 試行 | 変更 | スコア | 伸び |
|------|------|--------|------|
| 249 | Race_N_OuterStrongerThanB1 (B1より勝率高い外艇数) | 848.37 | +24.47 |
| 256 | Race_Min_WinRate (レース最低勝率) | 848.65 | +0.28 |
| 257 | Race_Max_Career2inRate (レース最高キャリア2着率) | 854.15 | +5.50 |
| 260 | **Race_Min_Career2inRate** (レース最低キャリア2着率) | **872.30** | +18.15 ★ |

### 学んだこと（次回以降の指針）
1. **Race 単体集約（Min/Max）が効く**: `Race_N_OuterStrongerThanB1` `Race_Min_WinRate` `Race_Max/Min_Career2inRate` などの **レース全体を1変数で要約する単純特徴** が強い。per-lane の派生や複合積より有効。
2. **Min 系が Max 系より強い傾向**: 同じ Career2inRate でも Min (+18.15) > Max (+5.50)。「弱いほう」に独立情報がある可能性（2着/3着争いの下限が payout 判断に効く）。
3. **B1 過信フラグは catastrophic**: `B1_Absolute_Dominance` (WR_Rank==1 AND ExTime_Rank==1) は 219.53 に大崩れ。B1 優位強化系は避け、B1 脅威強化系（Race_N_OuterStrongerThanB1 など）を選ぶ。
4. **Race 全体の格差/形状指標は危険**: `Race_WinRate_Gini` `ExTime_Skew` `Race_Max_RankScore` は catastrophic。Std/Entropy/HHI 系と同じく model を混乱させる。
5. **最近は「勝率以外」の単体集約が未開拓**: Career2in の Max/Min が効いたが、VenueWinRate/VLPBayes の Min は効かなかった。勝率相関が強いものは冗長化しやすい。

### 今回のセッションで試行した全変更
249 Race_N_OuterStrongerThanB1 848.37 ★採用
250 Race_N_OuterFasterThanB1 848.37 (ignored 同点)
251 B1_Absolute_Dominance 219.53 (catastrophic)
252 Race_N_OuterBetterVenueLane 848.37 (ignored 同点)
253 Race_WinRate_Gini 215.00 (catastrophic)
254 Race_VLPBayes_Std 839.68
255 ExTime_Skew 215.85 (catastrophic)
256 Race_Min_WinRate 848.65 ★採用
257 Race_Max_Career2inRate 854.15 ★採用
258 Race_Max_Career3inRate 834.21
259 Race_Max_VenueWinRate 841.71
260 Race_Min_Career2inRate 872.30 ★★採用（ベスト）
261 Race_Min_Career3inRate 837.88
262 Race_Min_VenueWinRate 832.96
263 Race_N_OuterBetterCareer2in 850.18
264 Race_Max_RankScore 230.23 (catastrophic)
265 Race_Min_VLPBayes 852.40
266 B1_Career2in_vs_AvgOuter 835.86
267 Race_Min_VenueLanePRaceCount 868.16 (接戦だが未更新)
268 Race_Range_Career2inRate 838.32
269 Race_N_HighCareer2in 852.34
270 B1_Career2in_Rank 850.18

### 次回のアイデア（未試行）
- **Race_Min_Motor2inRate / Race_Min_MotorWinRate**: モーター系の Min 未試行（ただし df_motor が空の環境では 0 埋めで効かない）
- **Race_Min_RankScore**: 最低公式グレード（B2 present フラグ）— RankScore Max は catastrophic だったが Min は別情報
- **Race_N_Outer_RankScore_ge_B1**: B1以上クラスの外艇の数（1st model用 B1脅威）
- **Career2in/3in の cross products や log 変換**: Min系との補完
- **267 の接戦（868.16）改良**: VenueLanePRaceCount の log or sqrt 変換

## 2026-04-23 セッション（trial 208-226）

### 結果サマリー
- 実行試行数: 19
- 終了理由: 停止条件 #3（直近10試行連続でセッションベスト未更新）
- セッション開始時ベスト（results.tsv all-time）: 903.42 (trial 152, 旧データウィンドウ)
- セッションベスト更新: 784.36 → 791.35 (+7.00)
- コミット: **0件**（全時ベスト 903.42 を下回るため）

### セッションベスト更新
| 試行 | 変更 | スコア |
|------|------|--------|
| 208 | ExTime_Zscore (z-score of ExTime within race) | 784.36 |
| 210 | WaterTemp_x_Wave (env cross) | 790.09 |
| 216 | Wave_Squared (nonlinear wave) | **791.35** ★ |

### 学んだこと（次回以降の指針）

1. **LightGBM は単純な単調変換を無視する**: WindSpeed_Squared, WaterTemp_Squared, log1p(Venue_AvgPayout), IsRain_x_Wave は全て trial 216 と完全同点 791.35 を記録 — feature importance が 0 で、モデルが学習に使わなかった。
2. **Wave だけは非線形変換が効く**: Wave_Squared は実際にスコアを押し上げた (+1.26)。波高には明確な閾値効果がある可能性。
3. **環境変数の cross は若干効く**: WaterTemp×Wave (tr 210, +5.73) が session baseline 確立に貢献。
4. **per-lane の積/z-score 変換は破壊的になりやすい**: WinRate_Zscore (tr 209), Course2in×VenueWR (tr 226) は catastrophic 200台に陥った。モデルが B1 過信 + 低オッズ的中に走る。
5. **近時データウィンドウでは 903.42 到達不可**: 2026-04-20 以降データが増えてスコア天井が ~790 に低下。コミット基準（全時ベスト）を更新するには evaluator 側の見直しが必要かもしれない。

### 今回のセッションで試行した全変更
208 ExTime_Zscore 784.36
209 WinRate_Zscore 211.03 (catastrophic)
210 WaterTemp_x_Wave 790.09 (session best #1)
211 Career2vs3_Ratio 784.66
212 WaterTemp_x_WindSpeed 786.66
213 ExTime_CV 776.41
214 Avg_Career2inRate 772.51
215 Course3in_x_Career3in 789.24
216 Wave_Squared 791.35 (session best #2)
217 WindSpeed_Squared 791.35 (ignored)
218 ExTimeSpread_x_Wave 777.26
219 R_x_Wave 789.90
220 VLPBayes_vs_Avg 780.00
221 WaterTemp_Squared 791.35 (ignored)
222 Venue_AvgPayout_Log 791.35 (ignored)
223 IsRain_x_Wave 791.35 (ignored)
224 WaterTemp_x_MonthSin 782.38
225 CourseWin_x_Wave 770.51
226 Course2in_x_VenueWR 214.29 (catastrophic)

### 次回のアイデア（未試行）
- **Wave の他の非線形変換** (sqrt, log, binned) — Wave^2 が唯一効いた理由を深掘り
- **特徴量の削減による正則化** — 約200特徴に対し train 約10万件、ratio 500 は悪くないが過学習気味
- **motor_stats 依存の MotorWinRate 再構築** — 現状ほぼゼロで全く機能していない
- **コミット基準の見直し検討** — 全時ベスト 903.42 は旧データで再現不可能、commit しない日が続く
- **時系列特徴の再試行** — RecentWinRate20 (tr 198) catastrophic だったが、実装を見直せば有効化可能かも

## セッション 2026-04-26（試行 #271-#293、計23試行）
- セッション開始ベスト: 872.30（trial #260: Race_Min_Career2inRate）
- セッション終了ベスト: **888.48**（trial #283: B1_RankScore_vs_AvgOuter）
- 改善幅: **+16.18**
- 終了理由: 直近10試行連続でベスト未更新（#284-#293）

### コミット済み改善（4件）
- #271 Race_Median_Career2inRate → 874.45 (+2.15)
- #278 Race_N_VeryWeakBoats（WR<3.0）→ 876.15 (+1.70)
- #279 Race_N_BottomTier（RankScore=1）→ 886.63 (+10.48) ★大幅改善
- #283 B1_RankScore_vs_AvgOuter → 888.48 (+1.85)

### 学習した知見
- **「弱フィールド密度」シグナル**が有効。Race_N_VeryWeakBoats と Race_N_BottomTier の組み合わせで弱艇カウント（WR・公式階級ベース両軸）が機能。
- **B1の自己除外参照（vs_AvgOuter）パターン**は ExTime と RankScore で機能。WinRate/Career2in/VenueWR/Course_Win/VLPBayes では不発。物理量・順序量に限定される傾向。
- **中央値（Median）アグリゲーション**が Career2inRate で機能。Min/Max が両方効く分布で median は補完情報。

### 効かなかった仮説
- TopTier (RankScore=4) — BottomTier の鏡像だが不発（A1密度はすでに別シグナル経由で捕捉済み？）
- Race_N_NoVenueExp / Race_N_PoorMotors — データ希薄でほぼ全レースゼロ、特徴量として無意味化
- 自己除外パターンの拡張（B6, B2 vs others, Course_Win） — B1 + ExTime/RankScore 限定の現象

### 次回のアイデア（未試行）
- **WR<3.0 と RankScore=1 の積/AND** — 二重弱艇条件の compound signal
- **Race_HasUnanimousFavorite** — B1_Is_Top_WinRate AND N_VeryWeakBoats > 0 の binary
- **B1_Tilt 関連の vs_AvgOuter** — ExTime/RankScore で機能した自己除外パターン
- **Career2in と RankScore の cross interaction** — 例: 高グレード×高Career2in
- **Tilt系 medians/aggregates** — 完全に未開拓
- **Motor_NumRaces 等のモーター使用度** — 現在ほぼ未使用
