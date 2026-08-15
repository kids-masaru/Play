# toto予測対戦システム — タスク管理

## 最終更新: 2026-06-21

## 現在のステータス
- Phase 1（planning）: **承認済み（2026-06-11）**
- Phase 2（実装）: **T1〜T14 完了**（T8答え合わせ含む）。実機(toto タブ)も確認済み。
- **2026-06-21 UI追加（全回まとめ表）**:
  - 回プルダウンで切替えなくても、結果が出た全回×くじ種別を一覧比較できる「全回まとめ表」を
    `Toto.jsx` に追加（`RoundsTable`）。各セル=「的中数/確定数(%)」、全問的中=🎉、1等配当も併記。
  - 狙い: 「mini-A第1635回 Gemini 100%＝3試合中3的中であって、まだ当せん確定ではない(5問必要)」という
    紛らわしさを一目で解消。プルダウン依存の見づらさ解消（masaru 要望）。push→Actions ビルド success・実機反映済み。
- **2026-06-19 追加対応（W杯期間に結果が出ない問題）**:
  - 原因: 現行回(1634-1636)が全てW杯=国際試合で結果源(jleague_matches.csv)に無く actual="" のまま。
    かつダッシュボードは販売中の現行回しか表示せず、予測した過去回(1635等)が見えなかった。
  - 対応: ①`settle_results.py` に手入力フォールバック(`data/manual_results.json` の match_id→H/D/A)追加。
    ②W杯結果をWeb検索で取得し manual_results.json に記入(1634全13・1635消化9)→ re-settle で的中判定。
    ③`generate_toto_data.py` が全回を `toto_rounds.json` 出力、`Toto.jsx` に回セレクタ追加(過去の答え合わせ閲覧可)。
  - 結果: 1635 Gemini 7/9的中・1634 Gemini 5/13。統計は国際試合のため-(想定内)。
- **2026-06-20 UI拡張（見やすさ・お金の可視化）**:
  - **mini toto(5試合)対応**: 回×くじ種別(toto/mini-A/mini-B)で切替。match_idは試合ベースで統一し
    ユーザー予想がくじ間で引き継がれる。mini-A=toto試合1-5, mini-B=試合6-10。
  - **当せん判定(KujiVerdict)**: 全問正解=当せん/はずれ/まだ可能性あり を あなた/Gemini/統計 別に表示。
  - **収支シミュレーション+ROI**: 1口100円・全問的中で1等当せん金が返る想定。`data/manual_payouts.json`に
    1等当せん金を手入力(第1634回: toto=0キャリーオーバー/mini-A 10,140円/mini-B 67,340円)。
  - **線グラフ化**: 累積収支の推移(右肩下がり)を線で追加。回ごと的中率も棒→線に変更。
  - 残: 6/19-20の未確定試合(1635-4,5,9,10)は試合後に manual_results.json/manual_payouts.json 追記で確定。

## 次回やること
- **T13 スケジューラ登録（要 masaru 実行）**: 管理者PowerShell等で
  `schtasks /Create /TN "Toto_Weekly" /TR "\"<repo>\run_toto_weekly.bat\"" /SC DAILY /ST 10:30 /F`
  （毎日10:30に冪等バッチ。ボート朝9:00と時間をずらす）。登録後 `schtasks /Run /TN "Toto_Weekly"` で初回手動実行可
- **観察ポイント**: `collect_jleague.py` は当年(2026)のJリーグ表をまだ取得できない（サイト未掲載で cols=[0,1]）。
  Jリーグの回・結果が出る時期に再確認。国際試合(W杯)の結果取得源は v1 未対応（statsもskip）＝想定内
- 任意の追加メニュー: 統計モデルを過去複数年でバックテスト→パラメータ調整（LOOKBACK/HOME_BOOST）。数pt改善余地
- 利用可能データ: `jleague_matches.csv`(5,554), `round_*.json`, `gemini_round_*.json`, `settled_*.json`, `toto_info.json`

## タスク一覧

### Phase 2-A: データ基盤
- [x] T1. Jリーグのデータ源を確定（J.League Data Site）し、結果スクレイパー作成（`collect_jleague.py`）。1X2導出OK
- [x] T2. 過去シーズンをバックフィル → `toto/data/jleague_matches.csv`（2021-2025 J1/J2/J3 = 5,554試合）
- [x] T3. toto公式から回号・対象試合・締切を取得（`fetch_toto_round.py`）。
  Yahoo schedule で候補回号 → store.toto-dream.com 詳細ページを read_html。
  販売中を自動検知し `data/round_<回号>.json` 保存（toto/mini-A/mini-B/goal3、締切・試合一覧）

### Phase 2-B: 予測
- [x] T4. 統計モデル（ポアソン/直近フォーム）で 1X2 確率（`predict_stats.py`）。2025バックテスト 47.5%(baseline 42.9%)・logloss 1.069。**予測力あり確認**
- [x] T5. Gemini 予測（推論＋H/D/A）（`predict_gemini.py`）。
  round_*.json の全ユニーク試合（toto/mini/goal3 和集合）を予測。Jリーグ対戦は predict_stats の
  P(H/D/A)＋直近フォームを材料に注入、代表/海外は一般知識で推論。`gemini_round_<回号>.json` 出力。
  `--dry-run` でAPI無し検証（両分岐OK）／応答パーサ単体テスト済み。**ライブAPI実行のみ未（要 GEMINI_API_KEY）**

### Phase 2-C: フロント（既存ダッシュボードにタブ追加）
- [x] T6. `Toto.jsx` を Battle.jsx 雛形から作成。1試合カードに 統計/Gemini予想・自信度・推論(開閉)、
  ユーザーは H/D/A をタップで即保存。進捗(n/13)と「Geminiとの一致率」を即時表示。esbuildで構文検証OK
- [x] T7. `totoStore.js`（battleStore と同方針、保存先 `users/{uid}/toto/{match_id}`、合言葉はボートと共用）
- [x] T8. 答え合わせ・的中率比較（統計/Gemini/ユーザー）。settle結果を toto_info.json に取り込み、
  Toto.jsx で結果バッジ・的中マーク(✓/✗)・3者の的中率サマリを表示
- [x] T9. App.jsx に「toto」タブ追加（import + タブボタン + `{page==='toto' && <Toto/>}`）

### Phase 2-D: 自動化・公開
- [x] T10.(最小版) `generate_toto_data.py`: round_*.json + gemini_round_*.json を結合し
  `dashboard/public/daily_data/toto_info.json` 生成（締切が最も近い販売中の回を既定表示）。
  ※ 結果反映(答え合わせ)部分は T8/T11 と合わせて拡張予定
- [x] T11. 結果取得→答え合わせ（`settle_results.py`）。jleague_matches.csv から (date,home,away) で実結果を引き、
  統計/Gemini の的中を判定 → `settled_<回号>.json`。国際試合は結果源なしで actual="" のまま（v1想定内）
- [x] T12. 週次オーケストレーション（`run_toto_weekly.py` + `run_toto_weekly.bat`）。
  collect→fetch→(未予測のみ)gemini→settle→generate→push の冪等バッチ。--no-push/--skip-gemini/--force-predict。
  通しテスト OK（exit 0、12秒）
- [x] T13. タスクスケジューラ `Toto_Weekly` 登録済み（毎日10:30・Ready）。settled_*.json が10:30更新で稼働確認。
- [x] T14.(toto分) push → GitHub Actions ビルド success → toto タブ実機確認済み（2026-06-13）

### Phase 2-E: 結果反映＆UI拡張（2026-06-19〜20）
- [x] T15. 国際試合(W杯)結果の手入力フォールバック（`settle_results.py` + `data/manual_results.json`）。Web検索で実結果記入。
- [x] T16. 全回×くじ種別を `toto_rounds.json` 出力 + `Toto.jsx` に回・種別セレクタ（過去回/ mini toto 閲覧可）。
- [x] T17. mini toto(5試合)対応。match_idを試合ベースで統一（くじ間でユーザー予想を引き継ぎ）。
- [x] T18. 当せん判定(全問正解=当せん) + 収支シミュレーション(投資/払戻/ROI, `data/manual_payouts.json`の1等当せん金)。
- [x] T19. 累積収支の線グラフ追加・回ごと的中率を線グラフ化（スマホ見やすさ重視）。
- [ ] T20. 残: 未確定試合の結果＆1等当せん金を試合後に manual_results.json / manual_payouts.json へ追記。
       Jリーグ回が始まれば統計モデルも稼働（国際試合は v1 対象外）。

### Phase 2-F: 全回まとめ表（2026-06-21）
- [x] T21. `Toto.jsx` に全回まとめ表（`RoundsTable`）追加。結果が出た全回×くじ種別を一覧化
  （セル=的中/確定(%)、🎉=全問的中＝当せん、CO/未取得を区別した1等配当）。
  プルダウンの上に常設し、回切替なしで横断比較できるように。esbuild構文チェックOK・push→Actions success。

## 作業ログ
### 2026-08-15（第1645回の統計・Gemini欠損調査）
- 統計モデル自体と履歴5,554試合は正常。dry-runで第1645回13試合中8試合に統計確率を生成できることを確認。
- 残り5試合はtoto側の正式名と履歴側の略称（例: ガンバ大阪/Ｇ大阪、横浜Ｆ・マリノス/横浜FM）が単純部分一致せず、同一チーム判定に失敗。
- `gemini_round_1645.json` は未生成。毎日10:30の `Toto_Weekly` は成功扱いだが、Gemini失敗を許容してCodex・公開処理を続ける設計。
- 原因は `run_toto_weekly.bat` が優先する `.venv` に `google.generativeai` が未導入であること。起動前の `ModuleNotFoundError` でGeminiだけ実行不能。
- [x] チーム名エイリアスとUnicode幅正規化を追加し、第1645回の統計予測を13試合へ拡大した。
- [x] 統計表示をAI予測データから独立させ、Gemini未生成でも表示生成時に直接補完するよう変更した。
- [x] `.venv` に `google-generativeai 0.8.5` を導入し、不完全予測の本番採用防止・部分成功の再利用を実装した。
- [x] Gemini/Codex予測失敗をexit 1で通知し、`logs/toto_weekly.log`へ終了コードを残すようにした。
- [ ] 第1645回Gemini実予測は無料枠20件/日へ到達したため未完了。次回枠で未予測分のみ再試行する。

### 2026-06-13 (夕: 自動化 T11/T12 + T8答え合わせ + push)
- T11 `settle_results.py`: jleague_matches.csv から実結果(H/D/A)を引き統計/Geminiの的中判定→settled_*.json。
  検証: 国際1635=0件(正常)、合成過去J1=4/4確定・統計3/4/Gemini判定OK
- T8: settle結果を generate_toto_data が toto_info.json に取り込み(各試合 result, summary)。
  Toto.jsx に結果バッジ・的中マーク(✓/✗)・あなた/Gemini/統計の的中率サマリ追加。回選択は販売中優先→無ければ最新
- T12 `run_toto_weekly.py` + `run_toto_weekly.bat`: collect→fetch→未予測のみgemini→settle→generate→push の冪等バッチ。
  通しテスト(--no-push --skip-gemini)で exit 0。1634は締切超過で販売中から自動除外を確認
- 観察: collect_jleague 2026 は現状サイトに表が無く0件(allow_failで続行)。Jリーグ回の時期に要再確認
- push→Actions success（toto タブ実機OK）。残: T13 schtasks 登録(masaru)

### 2026-06-13 (午後: フロント T6/T7/T9 + T10最小)
- T10最小: `generate_toto_data.py`。round + gemini を (date,home,away) で結合、toto(13)主軸で
  `dashboard/public/daily_data/toto_info.json` 出力。第1635回で生成（Gemini13/統計0=国際試合）
- T7: `dashboard/src/totoStore.js`。battleStore と同方針だが保存先を `users/{uid}/toto/{match_id}` に分離。
  合言葉(uid)・hashPassphrase 等は battleStore のものを import して共用（ボートでログイン済みなら toto も同期）
- T6: `dashboard/src/Toto.jsx`。1試合カード = 対戦/日時 + 統計モデル予想(P表示) + Gemini予想(自信度) +
  Gemini推論(開閉) + H/D/A タップ即保存。上部に締切カウントダウン、進捗(n/13)と Gemini一致率サマリ。
  結果比較は T8 で対応予定の旨を明記
- T9: `App.jsx` に「toto」タブ追加（Battle と並列）
- 検証: ローカルフルビルドは [[windows_build_impossible]] で不可のため、vite 同梱 esbuild で3ファイルの
  JSX構文チェック（exit 0、import解決OK）。実機確認は push→GitHub Actions ビルド後に行う

### 2026-06-13 (午前: T5)
- T5実装: `predict_gemini.py`。既存 `generate_gemini_predictions.py`（ボート）と同方式（env の GEMINI_API_KEY 依存、
  未設定ならエラー案内。.env は読まない）。プロンプトは1試合1コールで [推論]/[予想(H/D/A)]/[自信度] を要求。
  - Jリーグ対戦: `predict_stats.StatsModel` を流用し P(H/D/A)＋直近フォーム(勝分負)を context 注入。
    チーム名は normalize_team()（完全一致→双方向部分一致）で toto表記→Jリーグ表記に対応
  - 代表/海外（履歴なし）: 一般知識で推論する context に切替（現在のW杯2026回がこれ）
  - 検証: 1635回 dry-run（13試合・stats無）、合成J1 round dry-run（stats有・名古屋/福岡等の名前正規化OK）、
    parse_response 単体テストOK。**ライブAPIのみ未実行**（Claude は API キーに触れないため masaru 実行）
  - 副次修正: stdout の cp932 対策を `reconfigure` 方式へ（predict_gemini が predict_stats を import すると
    旧 `TextIOWrapper(sys.stdout.buffer)` 二重適用で stdout が閉じる不具合の解消。predict_stats も同様に変更）

### 2026-06-12
- T3完了: `fetch_toto_round.py` 作成。
  - 候補回号: Yahoo `toto.yahoo.co.jp/schedule/toto`（静的HTML、`第NNNN回` を抽出。回号==公式 holdCntId）
  - 詳細: store.toto-dream.com `PGSPIN00001DisptotoLotInfo.form?holdCntId=<回号>`（UTF-8、pandas.read_html）。
    くじ種別ごとに「タイトル→販売日程→試合一覧(N×7)→売上→払戻」。未販売回は `指定試合` 不在で判定
  - 締切=販売終了日セルの「ネット決済 HH:MM」、開催日 `MM/DD` は販売年から年補完（年跨ぎ対応）
  - 自動検知: 直近6回を確認し販売中(`販売開始<=today<=販売終了`)を `data/round_<回号>.json` 保存
  - 検証: 第1634/1635/1636回が販売中として取得OK（現在W杯2026期間で対象は国際試合）

### 2026-06-11
- planning 起動。AskUserQuestion で方針確定：
  - 既存ダッシュボードにタブ追加 / Jリーグ中心 / 統計＋Geminiの2者 / 週次フル自動
- spec.md・task.md を作成 → masaru 承認
- T1完了: J.League Data Site (data.j-league.or.jp/SFMS01) を採用。`collect_jleague.py` 作成。
  encoding補正(apparent_encoding)で文字化け解消、スコア→1X2(H/D/A)導出を確認
- T2完了: 2021-2025 J1/J2/J3 を一括収集 → `data/jleague_matches.csv` 5,554試合。
  分布 H40.2%/A33.1%/D26.6%（ホームアドバンテージ確認）
