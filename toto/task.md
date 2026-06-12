# toto予測対戦システム — タスク管理

## 最終更新: 2026-06-13

## 現在のステータス
- Phase 1（planning）: **承認済み（2026-06-11）**
- Phase 2（実装）: **T1〜T7・T9 完了 + T10最小版**。T5ライブAPIは実行済(1635)。
  次は **push→Actionsビルドで実機確認（T14の一部）**、その後 T8（答え合わせ）・T11〜T13（自動化）

## 次回やること
- **実機確認**: フロント変更をコミット→push→GitHub Actions ビルド→ https://kids-masaru.github.io/Play/ の
  「toto」タブを開いて確認（ローカルビルド不可 [[windows_build_impossible]]）。表示データは
  `dashboard/public/daily_data/toto_info.json`（`generate_toto_data.py` 生成、現在 第1635回）
- T8: `settle_results.py`（試合結果取得→H/D/A確定→統計/Gemini/ユーザーの的中率比較）。
  ※ 現在の1635回は W杯で試合が 6/17〜 のため結果はまだ無い。J.League データ源は collect_jleague.py 流用可だが
    国際試合の結果源は別途必要（後述）
- T11〜T13: 週次オーケストレーション（fetch→predict_stats→predict_gemini→generate→push）+ バッチ + タスクスケジューラ
- 利用可能データ: `jleague_matches.csv`(5,554), `round_*.json`, `gemini_round_*.json`, `toto_info.json`

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
- [ ] T8. 答え合わせ・的中率比較（統計/Gemini/ユーザー）。`settle_results.py`
- [x] T9. App.jsx に「toto」タブ追加（import + タブボタン + `{page==='toto' && <Toto/>}`）

### Phase 2-D: 自動化・公開
- [x] T10.(最小版) `generate_toto_data.py`: round_*.json + gemini_round_*.json を結合し
  `dashboard/public/daily_data/toto_info.json` 生成（締切が最も近い販売中の回を既定表示）。
  ※ 結果反映(答え合わせ)部分は T8/T11 と合わせて拡張予定
- [ ] T11. 結果取得→答え合わせ（`settle_results.py`）
- [ ] T12. 週次オーケストレーション（`run_toto_weekly.py` + `run_toto_weekly.bat`）
- [ ] T13. タスクスケジューラ登録（週次フル自動）
- [ ] T14. push → Actions ビルド確認 → 公開動作確認

## 作業ログ
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
