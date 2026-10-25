# ボートレースAI 改善タスク一覧

> 詳細仕様は `spec.md` を参照

## 🧭 再開ブロック（最終更新: 2026-10-20・ここだけ読めば再開できる。まず `NOW.md` も読む）
- **⚠ 最優先（10/20）**：毎日のバッチが大きく遅れている（夜バッチ終了 10/19 18:18・10/20 6:07、朝の公開 10/19 18:33）。振り返りも時間切れ・Codexの429で一部失敗。原因未調査。井﨑さんに確認してから調べる（NOW.md 仕事①）。
- **なぜやっているか**：「知識を育てる仕組み」が実は数値要約だけだった。強いモデル（Claude・Codex）が振り返って心得集を育て、各モデルに渡す方式を実験追加し、今まで／Jev／心得集／心得集＋Jev を比較する（井﨑さん承認済み 10/15）。
- **現在地**：A（前提の修理）完了・push済み。10/16朝バッチで効果確認済み（Claude 9/9レース保存、Jev 3アームとも19レース判定・夜の見送り10件も朝に再判定）。B（`playbook.py`）完了。C（`playbook_reflect.py`）完了。朝に組み込んだら予測が2時間遅れたため、夜バッチ（`run_daily.bat`）へ移した（`be3b1ac`、ローカルコミット済み・夜に自動push）。
D（心得集あり版の予測 `playbook_predict.py`）も完了・朝バッチの最後に接続（`5d76326`、ローカルコミット済み）。
I（まとめページ）も実装済み（`797ec78`・`67ee043`）。toto修正 `48cc590`。**これらは 10/18 2:20 の夜間バッチで全部push済み・Actionsビルド成功・公開ページは「まとめ」から開くことを確認済み**。
10/17夜（実行は10/18 2:20〜2:24）の振り返りは5モデルとも成功・タイムアウトなし（対象日 2026-10-18。有効件数 codex1・claude5・gemma_ft2・qwen_claude2・qwen_grok_x1）。
10/18朝：心得集あり版の予測は5モデルとも20/20保存。朝バッチは boatrace.jp の接続不良で大幅に遅れた（公開13:25、外部要因）。
E（Jev4アーム・評価の共通化・画面）完了・ローカルコミット（10/20）。
G（週1見直し）も完了・ローカルコミット（10/20）。
- **次の一歩**：10/21朝バッチ後に「playbook jev」の判定を確認。10/27（月）朝に週1見直しの初回LINEを確認 → F（過去30日検証。始める前に井﨑さんと日程相談）。スマホ幅の表示は未確認。totoの③〜⑤は保留（NOW.md 仕事③）。
- **やらないこと・待つこと**：Gemini・Grok・基本Gemmaに心得集を載せない／実購入・買い目・LINE買い目は変えない／旧反省会と旧教訓は触らない／`generate_grok_predictions.py` の未コミット変更は別件で触らない／途中段階のコードをコミットしない（夜23時のバッチが未pushコミットを自動pushする）。
- **答え待ちの質問**：なし
- **今回触ったファイル**：`playbook.py`、`tests/test_playbook.py`、`playbook_reflect.py`、`tests/test_playbook_reflect.py`、`update_battle_dashboard.py`、`run_daily.bat`、`playbook_predict.py`、`tests/test_playbook_predict.py`、`run_morning.bat`、`.gitignore`、`task.md`、`NOW.md`
- **未コミット / 未push**：コードは全部push済み。task.md・NOW.md（ドキュメントのみ）は未コミット。`generate_grok_predictions.py` は別件で未コミット。
- **待ち・ブロッカー**：なし
- **落とし穴・注意**：Bashは1コマンドずつ／テストは `python -m unittest discover -s tests`／ダッシュボードはローカルビルド不可（Actionsで確認）／スキーマファイルはCodexと共用。

## 2026-10-25 評価基準・Jev再利用設計

- [x] 高配当を実収支から消さず、実収支と再現性ストレスを分けて評価する原則を `docs/betting_evaluation_principles.md` に記録
- [x] 実収支、最大／上位3的中除外、払戻依存率、最大ドローダウン、同一レース比較、95%区間、件数を組み合わせた判定ラベルを設計
- [x] Jevを最終決定者ではなく、候補選択・リスク審査・保留・人への確認を行う二段目の審査役として `docs/jev_decision_gate_design.md` に整理
- [x] Jevへ渡す情報、渡さない情報、監査項目、セキュリティ警告での役割、他アプリへの転用条件を記録
- [x] 新旧Jevを固定版・同一入力・同一質問で並走させるコントロール／チャレンジャー方式と採用条件を設計
- [x] 個人Codex Skill `jev-decision-gate` を作成し、汎用の判断ゲート設計と版比較手順を保存
- [x] `paired_stats.py` に評価計算を共通化し、通常モデル・心得集比較・Jev比較の「最大当たり除外ROI」を同一定義へ統一
- [x] まとめページへ、実投資・実払戻・実収支・大当たり込みROI・最大1件／上位3件除外ROI・最大払戻依存率・最大損失幅・最長連敗・500件までの進捗を表示
- [x] 「黒字・高配当依存」「黒字・再現性を確認中／あり」「赤字・優位未確認」など、実収支と再現性を分けた結論を表示
- [ ] 現行応答の正確なJev版を確認し、`jev-latest`を固定版コントロールへ変更してから新版チャレンジャーを追加する
- [ ] モデル比較／実験ページにも必要に応じてストレス指標とJev版比較を展開する
- **今回の範囲**：評価計算の共通化とまとめページ表示まで。予測、買い目、購入、LINE、日次バッチ、Jev実行条件は変更していない。
- **確認**：Python全144件合格、追加境界テスト合格、`Overview.jsx`単体lint合格、本番ビルド成功。フロント全体lintは既存生成物と`Experiments.jsx`の既存エラーがあるため対象外。
- **次回の実装候補**：現行Jev版の固定 → 新版並走アーム → 同一入力でのシャドー比較。実装開始前に井﨑さんへ確認する。

## 2026-10-15 心得集（プレイブック）による自己改善実験

- 最終更新: 2026-10-16
- 現在のステータス: Phase 2（実装）中。本体・ダッシュボード刷新（I）ともMasaru承認済み（10/15。並びは提案どおり、上位3件の心得本文は公開OK）。A・B完了
- 次回やること: 夜の振り返りと朝の心得集あり版予測の動作確認 → E（採点・評価）。まとめページ刷新（I）はまだ未着手（10/17に井﨑さんが「見やすくなった？」と気にしていた）
- 10/16朝バッチ確認：Claude予測 9/9レース保存（10/6からの停止が解消）。Jev 3アーム（codex_jev・claude_jev・all_models_jev）とも19レースすべてjev判定、夜の「オッズ不足」見送り10件も朝に再判定済み
- 注意：夜23時のバッチ（`main_runner.py`）がローカルの未pushコミットもまとめてpushするため、途中段階のコードはコミットせず、動く単位でコミットする
- push済み：`430cdce`・`c4fd44a`・`1278f2b`・`3697021`（10/16 0:10の夜間バッチが自動でpush）

### A. 前提の修理
- [x] 9/27のローカルLLMフィードバック変更（未コミット）を別コミットで記録（`430cdce`。Grok使用量報告の変更は別件のため対象外で未コミットのまま）
- [x] Claude予測のスキーマエラー（`$schema` 行）を修正（`c4fd44a`）。保存なしの実呼び出しでCLIが受け付けることを確認。朝バッチでの保存は10/16に確認
- [x] 5点不足での全件不採用を、不正レースだけ除外する形に変更（`c4fd44a`）
- [x] Jevの夜間「オッズなし」見送りが朝の判定を塞ぐ問題を修正（`1278f2b`）
- [x] 基本Gemmaの反省会を調査：止まっておらず、毎晩10件ずつ古い順に処理して約3か月遅れ（spec 9章に記録）

### B. 心得集の土台
- [x] `playbook.py`：保存形式、上限、差分（add/update/disable）の検証、注入文の作成、日付版とハッシュ（10/16）
  - 差分は1件ずつ検証し不正な操作だけ拒否。5件超・リスト以外は全面書き直し扱いで全体を拒否
  - 日付版が無い日は前日以前の最新版を使う（未来の版は使わない）。ハッシュは有効項目のid＋本文だけから作る
  - 振り返り役の割り当て `REFLECTOR_ASSIGNMENT`、モデルキーは jev_shadow と同じ（codex / claude / gemma_ft / qwen_claude / qwen_grok_x）
- [x] 時系列ガード（対象日当日以降の結果を拒否）`guard_chronology`
- [x] 単体テスト `tests/test_playbook.py`（28件、全体66件合格）
- [x] `.gitignore` に `daily_data/playbooks/`（公開フォルダ側の別名も）を追加

### C. 振り返り（たすき掛け）
- [x] `playbook_reflect.py`：Claudeが Codex・ローカル3モデルを、Codexが Claude を振り返る（10/17）
  - 材料は前回の振り返り以降の新しい確定結果だけ、新しい順に最大40レース（旧反省会のような遅れの蓄積を防ぐ）。状態は `daily_data/playbooks/reflect_state.json`
  - 振り返りの生出力は `daily_data/playbooks/reflections/<model>/<日付>.json`（非公開）。根拠レースIDは材料にあるものだけ残す
  - 実行：`python playbook_reflect.py`（`--date`・`--models`・`--force`・`--dry-run`）。失敗しても終了コード0（朝バッチを止めない）
- [x] 1モデル1日1回にまとめた呼び出し、失敗時は心得集を変えず前日版を使用
- [x] `changes.jsonl` への変更記録
- [x] 単体テスト `tests/test_playbook_reflect.py`（15件、全体81件合格）
- [x] 本物での試運転（10/17、一時フォルダのみ・本番の心得集には未反映）：Claude→Codex 1件追加、Codex→Claude 5件追加、拒否0。どちらも条件→行動の具体的な心得
- [x] 朝バッチへ組み込み（10/17 `4d493b6`）→ **10/17朝に問題**：Claudeの振り返り3件（codex・gemma_ft・qwen_grok_x）が15分タイムアウト、各モデルの予測と公開が約2時間遅れ（公開12:14）。成功は claude（Codexが5件）と qwen_claude（Claudeが1件）
- [x] 夜バッチへ移動（10/17 Masaru了承「夜バッチへ移す」、`be3b1ac`）：`run_daily.bat` の `main_runner.py` の後で `python playbook_reflect.py --night`（18時以降は翌日、0時過ぎは当日が対象日）。ログ `logs/playbook_reflect.log`。材料は20レースに削減。朝バッチからは削除。全86件合格
- [ ] 10/17夜（23時〜）の夜バッチで振り返りが動いたか確認（`logs/playbook_reflect.log` に5モデル分の結果行、対象日 2026-10-18、タイムアウトの有無）と、10/18朝の公開が元の時刻（10時前）に戻ったか確認

### D. 心得集あり版の予測
- [x] Codex・Claudeの心得集あり版（使った心得IDの出力つき）：新規 `playbook_predict.py`（10/17）。既存の指示文・学習情報をそのまま使い末尾に心得集だけ足す。出力形式は別に持つ（`used_playbook_ids` 追加。共用スキーマファイルは変えない）
- [x] ローカル3モデルの心得集あり版：`predict_gemma_ft.py` の入力作成・呼び出し・解析を使い回し、末尾に心得集を足す。使用IDは本文中のID表記を拾う
  - 出力：`daily_<model>_playbook_predictions.csv`（codex / claude / gemma_ft / qwen_claude / qwen_grok_x）。列接尾辞 CodexPB・ClaudePB・GemmaFTPB・QwenClaudePB・QwenGrokXPB、心得集の版・ハッシュ・件数・使用ID
  - 心得集が空のモデルは予測しない。入力の対象日が今日でなければ予測しない
- [x] 朝バッチへ障害分離して接続：`run_morning.bat` の最後（battle update・CLVの後）で `python playbook_predict.py`。既存の予測・公開を遅らせない（10/17の教訓）。常に終了コード0
- [x] テスト `tests/test_playbook_predict.py`（9件、全体95件合格）
- [ ] `generate_battle_data.py`・`model_performance.py` への登録（採点・画面表示）→ E で行う（既存の公開JSONを変えるため、評価と一緒に）

### E. Jevと評価
- [x] `jev_shadow.py` に4アーム追加（`codex_playbook_raw/jev`・`claude_playbook_raw/jev`）、`jev_pairing_v2` へ版上げ（10/20）
  - 心得集あり版は `PLAYBOOK_SOURCES` に分け、全モデルJev・`jev_backtest.py` の入力には混ぜない。成績・CLVは元モデルと同じものを渡す
  - v1 の記録も同じ実験として再利用・採点（`COMPATIBLE_EXPERIMENT_VERSIONS`）。既存アームの蓄積287件はそのまま
  - 単体アームで元予測が無い時は「判定し直し可」の見送りにする（心得集の予測は朝バッチの最後に出るため）
  - `run_morning.bat` の最後（心得集あり版予測の後）で `jev_shadow.py` を再実行。既存アームは履歴を再利用し追加のAPI呼び出しなし
- [x] ペア・ブートストラップと判定を `paired_stats.py` に共通化（`build_overview.py`・`jev_pairing_performance.py` が使用）。`jev_pairing_performance.json` に `playbook_effect`（同じレースでの「心得集あり−なし」：単体は全買い目、Jevは選んだ1点）
- [x] ダッシュボード：Jevカードに4アーム追加（`ModelDashboard.jsx`）、まとめの結論ボードに「心得集＋Jev」のマスと「Jev同士の差」（`Overview.jsx`）
- [x] テスト `tests/test_jev_playbook.py`（11件、全体121件合格）。本物データで採点集計・dry-run・overview を一時フォルダに出して確認
- [ ] 10/21朝バッチ後に `logs/morning.log` 末尾「playbook jev」で心得集アームが判定されたか（API呼び出し数・エラー0）確認。採点は翌日以降

### F. 過去30日の検証
- [ ] `playbook_backtest.py`（Gitスナップショット、日付順の再現、なし版も再予測、再開可能、`--live`・`--max-days` 必須）
- [ ] パイロット10日→残りを実行し、`reports/playbook_backtest_report.md` を作成

### G. 週1の見直し
- [x] `playbook_weekly_report.py`（月曜朝、LINEとレポート）（10/20）
  - `run_morning.bat` の最初で毎日呼び、月曜だけ作る。同じ日の2回目は送らない（送信記録 `daily_data/playbooks/weekly_state.json`）。AIは呼ばない
  - モデルごとに今週の変更（追加・修正・無効化）、今週・累計の「あり−なし」、心得ごとの使用回数・的中・損益（今週・累計）
  - 見直し候補：累計10回以上使って損益マイナス／作って14日以上使われていない（使った心得IDを答えないローカル3モデルには未使用の印を付けない）
  - レポート `reports/playbook_weekly_<日付>.md` は本文を含むので `.gitignore`。LINEは要約のみ
  - 手動の無効化：`python playbook_weekly_report.py --disable <ID> --reason "<理由>"`（changes.jsonl に reflector=manual で記録、翌日用の版も作る＝翌日の予測から外れる）
  - テスト `tests/test_playbook_weekly_report.py`（8件、全体129件合格）。本物データで試作（LINE送信なし）を確認
- [ ] 10/27（月）朝の初回送信を確認（`logs/morning.log` の「playbook weekly」とLINE）

### I. ダッシュボード（まとめページ）の刷新
- [x] `build_overview.py`：運用チェック・結論ボード・心得集の今・検証結果・全体成績を `overview.json` に集計（テスト7件、`797ec78`、10/17）。結論ボードの「なし／あり」の採点もここで行う（同じレースのみ・ペア・ブートストラップ）
- [x] 朝バッチ（`update_battle_dashboard.py` の公開直前）に組み込み、公開ファイル・`.gitignore` に追加（`67ee043`）。※心得集あり版予測は朝バッチの最後なので、まとめの「心得集あり版の予測」は公開時点で「この後実行」と出ることがある
- [x] `Overview.jsx`（まとめ・初期表示）・`Experiments.jsx`（心得集の効果・Jev・CLV）を新設、`App.jsx` のタブ再編（まとめ／モデル比較／実験／今日の予測／toto）（`67ee043`）
- [x] ローカルの開発サーバーでパソコン幅の表示を確認。esbuild でまとめて構文・import確認
- [ ] スマホ幅の実機確認、Actionsのビルド成功確認（10/17夜のpush後）
- [ ] 実験ページの「日別の推移」グラフ（データがたまってから）

### H. 仕上げ
- [ ] 全単体テスト、code-check、simulation
- [ ] まとめて1回push、GitHub Actions・Pagesを確認

## 2026-10-01 Codex・ClaudeとJevの組合せ実験

- [x] `codex_raw` / `codex_jev` / `claude_raw` / `claude_jev` / `all_models_jev` の5アームを定義
- [x] 単一モデル向けJev質問から購入可否を分離し、候補選択に限定
- [x] 実験ID・版・入力ハッシュを履歴へ保存し、アーム別に同一レースの再課金を防止
- [x] 元モデルの全買い目と先頭1点を残し、Jev選択1点と事後比較できるように実装
- [x] `jev_pairing_performance.py` で確定結果後のROI・最大当たり除外ROI・最大DD集計を実装
- [x] 前日までのJev自身のアーム成績を次回入力へ要約し、当日結果混入を拒否
- [x] 日次バッチへ比較成績更新と公開サマリを追加
- [x] 既存の「モデル比較」ページへJev組合せ5アームの成績カードを追加
- [x] ROI・最大当たり除外ROI・的中率・収支・最大損失幅・採点件数を表示し、0件時は「蓄積中」と明示
- [x] デスクトップ／スマートフォン表示を実画面で確認（カード5件、横はみ出しなし）
- [x] 現在の20レース×5アームでAPIなしドライラン成功（100レコード、エラー0）
- [x] 全31単体テスト、構文確認、フロントエンドlint・本番ビルド、APIキー非混入、内部履歴の公開対象外を確認
- [x] code-checkの全5項目を対話確認し、問題なし
- [x] simulationで正常系・異常系・ロールバック・公開データの安全性を確認
- [x] `05920cb` をmainへ1回だけpushし、GitHub Actions成功・GitHub Pages公開画面を確認
- [x] Dependabot警告2件を修正し、`f9eaeaa` の公開後にopen alert 0件を確認
- [ ] 次回朝バッチでv2初回判定と、翌日以降の確定結果採点を確認
- 実購入・既存買い目・LINE通知は変更しない。Jev単独の買い目生成は本実験に含めない。

## 2026-09-30 Jev購入ゲート（シャドーモード）

- [x] Jevを新規予想家ではなく、既存モデル買い目の二段目審査役として定義
- [x] 実購入・既存買い目・LINE通知を変更しないシャドー処理を実装
- [x] 買い目、モデル間一致、直近実績、CLV、オッズ、データ充足度を構造化して入力
- [x] モデルの長い説明文と選手氏名をJev入力から除外
- [x] オッズなし／予想モデル2件未満をAPI前のハードルールで見送り
- [x] 対象日当日以降の確定結果混入を拒否する時系列ガードを追加
- [x] 同一レース再実行時の判定再利用と二重課金防止を追加
- [x] APIキー未設定・通信失敗時も既存更新を継続する障害分離を追加
- [x] Python構文確認、Jev単体テスト8件、既存を含む全15テストに合格
- [x] 2026-09-30の10レースでAPIなしドライラン成功（オッズ未取得のため全件を安全側で見送り）
- [x] TypeSafe早期アクセス登録と `TYPESAFE_API_KEY` のWindowsユーザー環境設定
- [x] Jev API接続テスト成功（`jev-1.13.0`、買い目・履歴を変更しないprobe）
- [x] simulationで異常系（APIキーなし・通信失敗・過去日・データ不足）、`--skip-jev`による切り戻し、公開JSONへの機密情報非混入を確認
- [x] 2026-09-15〜09-30の各当日朝Gitスナップショットから、未来情報なしの時点保証バックテストを実装
- [x] 旧194件集計は現在ファイルの後日更新混入リスクがあるため参考値へ降格し、確定評価から除外
- [x] 当日朝情報・確定結果・2モデル以上が揃う199レースをJev `jev-1.13.0` で再評価（APIエラー0件）
- [x] 9月16日の前日データ保存と9月22日のスナップショット欠損を検出し、自動補完せず除外
- [x] 現行`action`は199件すべてskipで、購入ゲートとして採用不可と確認
- [x] Jev選択候補は全199件でROI 114.1%（+16,110円）、最多一致候補はROI 98.2%（-2,040円）
- [x] 後半169件ではJev候補ROI 102.8%（+2,650円）だが、最大当たり除外後はROI 91.4%（-8,200円）
- [x] ペア・ブートストラップ95%区間が -25,650円〜+64,350円でゼロをまたぐため、Jev優位は未確定と判定
- [x] 入力ハッシュ・Git commit一致時だけ履歴を再利用し、再実行で199件すべてAPI再呼出しなしを確認
- [x] 時点保証レポート `reports/jev_backtest_git_report.md` と監査用JSONを生成
- [x] 全26単体テスト、構文確認、日付不正・API上限なしの異常系、機密情報非混入に合格
- [x] `daily_data` の別名パス側でもJev内部履歴をGit除外し、公開対象リスト外であることをテスト化
- [ ] 2026-10-01朝バッチ完了後、当日オッズを使った正常系の初回Jev実判定を確認
- [ ] 500〜1,000件の確定判定を蓄積し、現行方式・単純ルール方式と比較
- 現段階ではJev判定を購入へ反映しない。再学習も実施しない。

## 2026-09-27 学習済みローカルLLMの日次フィードバック接続

- [x] 学習Gemma（Gemini先生）へ、前日までの自己成績・直近結果・類似レースを注入
- [x] 学習Qwen（Claude先生）へ同じモデル専用フィードバックを注入
- [x] 学習Qwen（Grok+X先生）へ同じモデル専用フィードバックを注入
- [x] Qwenは切替日の2026-09-07以降だけを自己実績として扱い、旧Gemma時代を除外
- [x] 予測日当日以降の結果を除外する既存の未来情報防止を適用
- [x] 単体テスト4件と実データ読取確認に合格
- [x] code-checkの全5項目を対話確認し、問題なし
- [x] simulationで正常系・異常系・ロールバック・公開データの安全性を確認
- [ ] 次回朝バッチで学習サマリ生成と実予測への反映を確認
- 再学習は未実施。モデル重みは現状のまま維持する。

## 🧭 再開ブロック（最終更新: 2026-09-08・ここだけ読めば再開できる）
- **現在地**: Hugging Face調査を起点に2件を実装し **push済み・GitHub Pagesデプロイ済み**（commit `feac7a3`）。
  ①弟子のsystemプロンプト統一（学習`train_qlora*.py`と推論`Modelfile*`を同一SYSTEMに）
  ②CLV（妙味の先取り）指標を新設（前進型・蓄積式）。今は締切オッズ未取得で全モデル「蓄積中」表示。
  表推論の改善レポートも作成済み（`reports/tabular_reasoning_findings.md`）。
- **次の一歩**（いずれも"待ち"）:
  1. 今夜21:30の `BoatraceAI_Closing`（タスクスケジューラ登録済み）初回実行→数日でCLVが実数化。
     数日後に `dashboard/public/daily_data/clv_summary.json` を確認（口頭では「CLV見せて」でOK）。
  2. **次回リトレ時に** systemプロンプト統一＋表推論レポートの改善（欠損明示・要点の前計算）をセット適用。
- **今回触ったファイル**（すべてpush済み）: `compute_clv.py` / `closing_odds_runner.py` / `run_closing.bat` /
  `run_morning.bat` / `update_battle_dashboard.py` / `gemma_finetune/{train_qlora_qwen.py,train_qlora.py,Modelfile,Modelfile.grokx}` /
  `dashboard/src/ModelDashboard.jsx` / `.gitignore`
- **未コミット / 未push**: `task.md`（本更新）と `reports/tabular_reasoning_findings.md` はローカルのみ
  （docs単独pushしない方針。次のコード変更とまとめる）。他は朝バッチ自動生成データの差分。
- **待ち・ブロッカー**:
  - CLV蓄積待ち（今夜21:30〜数日）。技術的ブロッカーは無し。
  - 次回リトレは「新規確定300〜500件の蓄積」＋「Qwen弟子の2〜3週間戦績」待ち（`gemma_finetune/task.md`参照）。
- **落とし穴・注意**:
  - Modelfileの `ollama create` 再importは**次回リトレ後までやらない**（今やるとsystem無し学習×system有り推論の逆ズレ）。
  - `run_closing.bat` はInteractiveログオン必須。21:30にPCがオフ／ログオフだとその日の締切オッズが飛ぶ（翌日自動再開）。
  - `clv_prediction_log.csv` / `closing_odds_3t.csv` はgitignore（ローカル永続でOK）。
  - 締切オッズbackfillは2026-05-29で停止のため過去CLVは計算不可＝前進型のみ。

## 最終更新: 2026-09-08

## 現在のステータス

- Phase 1（planning）: 完了
- Phase 2（実装）: Claudeのボートレース・toto参加、共通RAG、集計・UI接続まで完了
- Phase 3（code-check）: チェック1〜5完了
- Phase 4（simulation）: PC・スマホ、実予測、障害分離、定期実行接続、本番相当ビルドまで確認完了
- リリース: `68e8885` をmainへpushし、GitHub Actions・GitHub Pages・公開画面を確認済み
- ボートレースは2026-09-01の1レース、totoは第1649回13試合でClaude実予測の保存に成功
- Gemma候補再学習は新規確定300〜500件の蓄積待ち

## 次回やること

1. 次回の自動実行でClaudeの予測・LINE・成績集計が継続更新されることを確認する。
2. Claudeの結果が確定後、「計測前」から成績表示へ切り替わることを確認する。
3. 新規確定300〜500件の蓄積後にGemma候補再学習へ進む。

## Hugging Face知見の反映（2026-09-08・commit feac7a3、push済み・デプロイ済み）

Hugging Face（AIのGitHub的存在）調査から2件を実装。詳細は [[huggingface_clv_and_system_prompt]] メモ参照。
（※ push は朝の自動更新バッチのpushに相乗りして完了済み。）

- **systemプロンプト統一**: SFT標準（tulu-3/Nemotron）に倣い、学習(train_qlora*.py)と推論(Modelfile*)を同一SYSTEMに統一。学習/推論のズレを解消。→ **効くのは次回リトレ時**。リトレ後は揃えたModelfileで `ollama create` 再importが必要。
- **CLV指標を新設（前進型）**: 朝→締切オッズの動きで「妙味の先取り」を測るROIとは別軸の指標。`compute_clv.py`（--selftestで検証済）、`closing_odds_runner.py`+`run_closing.bat`（締切オッズ取得）、ModelDashboardにCLVカード。
  - **未完タスク**: `run_closing.bat` を**毎晩21:30 JSTでタスクスケジューラ登録**すると締切オッズが貯まりCLVが「蓄積中」→実数に変わる。登録するまでCLVは全モデル「締切オッズ待ち」表示。
  - コードは push済み・デプロイ済み。残る `task.md` / レポート等のdocsは単独pushせず次のコード変更とまとめる。

## Claude・RAG・Gemma改善タスク（2026-09-01計画）

### A. 共通設計・テスト土台

- [x] 現在のCodex・Gemini・Grok・Gemma・LightGBMの学習方式を調査
- [x] Claude Code CLIのログイン状態、構造化出力、ツール無効化の実行可否を確認
- [x] 後付け予測禁止、自己フィードバック分離、障害分離、Gemma候補評価の方針をユーザー確認
- [x] `spec.md` に機能要件・非機能要件・受け入れ条件を追記
- [x] 共通モデルIDと画面表示名の対応を定義
- [x] ボートレース・toto共通の戦略バージョン記録方式を定義
- [x] 対象日時より後の結果を拒否する時系列ガードとテストを追加
- [x] モデル別フィードバックのデータ契約と入力検証を追加

### B. ボートレースClaude Code参加

- [x] `generate_claude_predictions.py` を追加
- [x] Claude CodeをSonnet相当・非対話・ツール無効・JSON Schema付きで呼び出す
- [x] 当日対象レースを原則1回の呼び出しへまとめる
- [x] 買い目数、形式、重複、対象レース一致を検証してから保存する
- [x] Claude専用の累積予測履歴と実行メタデータを保存する
- [x] 過去日への後付け予測を防ぐ
- [x] 認証切れ、利用上限、タイムアウト、JSON不正時の安全な失敗処理を追加
- [x] `update_battle_dashboard.py` へClaude処理を障害分離して接続

### C. toto Claude Code参加

- [x] `toto/predict_claude.py` を追加
- [x] 販売中かつ未予測の回だけを対象にする
- [x] 1対象回の全試合を原則1回の呼び出しへまとめる
- [x] 試合数、選択値、試合対応、重複・欠損を検証してから保存する
- [x] `claude_round_<回号>.json` と実行メタデータを保存する
- [x] 過去回への後付け予測を防ぐ
- [x] `toto/run_toto_weekly.py` へClaude処理を障害分離して接続

### D. モデル別フィードバックRAG

- [x] 既存Codex学習処理から共通化可能な履歴抽出・集計処理を整理
- [x] 共通の過去レース類似例と、モデル固有の自己評価を分離
- [x] Codexへ共通データ契約を接続し、既存挙動を維持
- [x] ClaudeへClaude自身の確定済み成績・直近ミスを接続
- [x] GeminiへGemini自身の確定済み成績・直近ミスを接続
- [x] GrokへGrok自身の確定済み成績・直近ミスを接続
- [x] totoのCodex・Claude・Geminiにも同じ分離原則を適用
- [x] 履歴0件、少数、十分な件数の各ケースをテスト
- [x] 他モデルの自己評価が混入しないことをテスト
- [x] 利用履歴件数、生成日時、戦略バージョンを出力へ記録

### E. 集計・LINE・ダッシュボード

- [x] ボートレース対戦データとモデル成績集計へClaudeを追加
- [x] LINEモデルランキングへClaudeを同一条件で追加
- [x] LINE・ダッシュボードから基本Gemmaを除外する既存方針を維持
- [x] モデル比較、ランキング、比較グラフ、過去成績へClaudeを追加
- [x] Claudeアイコンを既存のブランド表現へ統一
- [x] totoの予測比較、成績、試合詳細、シミュレーションへClaudeを追加
- [x] Claude追加後のPC・スマホ表示を確認
- [x] Claude失敗時にも他モデル・LINE・公開JSONが更新されることを確認

### F. 検証・本運用開始

- [x] Python構文・対象単体テスト・データ整合性テストを実行
- [x] JSX/ESLintと本番相当Viteビルドを実行
- [x] ボートレースClaudeの実対象日スモークテスト
- [x] toto Claudeの販売中対象回スモークテスト
- [x] 後付け予測が生成されていないことを確認
- [x] Claude失敗を模した障害分離テスト
- [x] 対象コードと必要生成物だけを選別してコミット
- [x] まとまった1回のpushでGitHub Actions・GitHub Pages反映を確認
- [x] 次回未予測分から本運用を開始

### G. Gemma候補再学習（新規確定300〜500件蓄積後）

- [ ] 新規確定予測数をモデル・教師系統別に集計
- [ ] 300〜500件以上の条件を満たすまで再学習を保留
- [ ] 教師データの期間、重複除去、リーク防止、件数を固定して記録
- [ ] 現行モデルを上書きせず、日付・データ版付きの候補モデルを作成
- [ ] 現行モデルと候補を同じ未学習評価セットで比較
- [ ] 的中率、ROI、最大ドローダウン、欠損率、JSON失敗率を評価
- [ ] 採用基準を満たす候補だけ本番へ切り替え
- [ ] 不採用時は現行モデルを維持し、比較結果を保存

---

## Phase 1: オッズデータ取得 + 期待値フィルタ

### 1-1. オッズスクレイピング関数の実装 ✅
- [x] `collect_race_data.py` に `scrape_odds_3t(jcd, rno, date_str)` を追加
  - boatrace.jp の3連単オッズページをパースする
  - 120通りの組み合わせ → `[race_id, date, venue, rno, combination, odds]` 形式で返却
  - `ODDS_3T_HEADERS` 定数を定義
- [x] 手動テスト: 特定の日付・会場・レースでオッズが正しく取得できることを確認
  - daily_data/daily_odds_3t.csv に18,000行超のデータが実際に取得済み（本番動作で確認）

### 1-2. 夜間バッチへのオッズ収集統合 ✅
- [x] `local_collect_race_data.py` に Job 3（当日確定オッズ収集）を追加
  - 結果取得と同タイミング（18時以降の夜間バッチ）
  - `daily_data/daily_odds_3t.csv` に保存
  - レジューム対応（既に取得済みの会場はスキップ）
- [x] `main_runner.py` は変更不要（`local_collect_race_data.main()` 内で実行されるため）

### 1-3. 朝バッチスクリプト morning_odds_runner.py を新規作成 ✅
- [x] `morning_odds_runner.py` を新規作成
  - Job A: 当日レースの前売りオッズを取得 → `daily_data/daily_odds_3t.csv` に追記
  - Job B: LightGBM確率 × 実オッズ → EV算出
  - Job C: EV > 1.0 の買い目のみでAI予測を実行 → `daily_predictions.csv` 更新
  - Job D: LINE通知（EVベース推奨買い目を送信）
- [x] タスクスケジューラに朝9時のバッチを登録する手順をREADMEに記載（README.md参照）

### 1-4. AI予測パイプラインへのEV統合 ✅
- [x] `local_ai_pipeline.py` に仮想EV推定（LightGBM確率ベース簡易3連単候補）を追加
- [x] 夜間バッチのプロンプトに有力3連単候補（確率順）を注入

### 1-5. ROI計算へのオッズ統合 ✅
- [x] `generate_dashboard_data.py` の `calculate_roi()` を改修
  - `daily_odds_3t.csv` から事前オッズを参照
  - `recent_races` に `pre_odds` と `ev_category` フィールドを追加
- [x] ダッシュボードJSON出力の拡張

### 1-6. AI予測プロンプトの改善 ✅
- [x] `expert_knowledge.json` にEV関連ルールを追加
  - `ev_threshold` パターン
  - `odds_value_zone` パターン
  - `ev_weighted_selection` パターン
- [x] `local_ai_pipeline.py` のプロンプトに「オッズ意識」を組み込み

### 1-7. LINE通知の拡張 ✅
- [x] `main_runner.py` の通知テンプレートにEV情報を追加
  - 推奨買い目の横にEV値を表示（朝バッチ適用後）
  - 朝9時EV強化版の案内を追加

### 1-8. retrain_model.py のデータマージ対応 ✅
- [x] `retrain_model.py` の Step 1 に `daily_odds_3t.csv` → `past_data/past_odds_3t.csv` のマージを追加

---

## Phase 2: 2着・3着予測 → 3連単確率推定

### 2-1. 学習データの拡張 ✅
- [x] `build_features.py` に `Target_2nd`, `Target_3rd` の抽出ロジックを追加
  - 結果データ `Result` 列（例: "1-3-5"）から2着・3着を分離
  - `extract_2nd_place()`, `extract_3rd_place()` を実装
- [x] `ml_features.csv` の出力カラムに追加

### 2-2. 2着・3着モデルの訓練 ✅
- [x] `retrain_model.py` を拡張して3モデル訓練に対応
  - `lgb_model_1st.txt` — 1着予測（既存）
  - `lgb_model_2nd.txt` — 2着予測（新規）
  - `lgb_model_3rd.txt` — 3着予測（新規）
  - `train_single_model()`, `evaluate_old_single_model()` に共通化
  - `_update_model_if_better()` ヘルパー追加
- [x] 各モデルのA/Bテストを独立実行

### 2-3. 3連単確率の推定ロジック ✅
- [x] `local_ai_pipeline.py` に3連単確率推定関数を追加
  - `estimate_trifecta_probs(probs_1st, probs_2nd, probs_3rd)` → 上位N通りの確率
  - 条件付き確率の近似: `P(i-j-k) ≈ P_1st(i) × P_2nd(j|i≠j) × P_3rd(k|i≠k,j≠k)` を正規化
  - `predict_with_model()` 共通関数を追加
  - `load_lgb_model_2nd()`, `load_lgb_model_3rd()` を追加
- [x] AIプロンプトに上位確率の組み合わせを提示（3モデル統合版）
  - 2着/3着モデル未整備時は1着モデルのみの簡易版にフォールバック

### 2-4. EVとの統合（Phase 1完了後） ✅
- [x] `morning_odds_runner.py` で3モデル統合確率 × 実オッズ = 真のEVを算出
  - `estimate_trifecta_probs()` を利用した高精度EV算出
  - 2着/3着モデル未整備時は従来の1着モデルのみの簡易確率にフォールバック
- [x] EV > 1.0 の買い目のみを推奨リストに含める

---

## Phase 3: 教訓の条件別分類

### 3-1. 反省データの拡張 ✅
- [x] `daily_reflections.csv` に `Venue`, `Weather`, `WindLevel` カラムを追加
  - 既存データとの後方互換: カラムが存在しなければ自動追加
- [x] `local_ai_pipeline.py` の `run_reflection()` で教訓保存時に条件情報を付与
  - `daily_raw_beforeinfo.csv` から天候・風速データを取得して紐付け
  - `classify_wind_level()` で風速を3段階に分類（calm/moderate/strong）
  - 反省プロンプトにも天候・風情報を追加（より具体的な教訓を引き出す）

### 3-2. 条件フィルタ付き教訓注入 ✅
- [x] `get_relevant_lessons(venue, weather, wind_level)` を新規追加
  - 同会場の教訓: +3点
  - 似た天候の教訓: +2点
  - 似た風レベルの教訓: +1点
  - スコア順 → 日付新しい順でソートし上位5件を返却
- [x] `run_predictions()` の教訓注入をレースごとの条件付き取得に変更
- [x] `morning_odds_runner.py` の教訓注入も条件フィルタ付きに変更
- [x] 旧 `get_recent_lessons()` は後方互換のため維持

---

## Phase 4: SQLite移行 + モーター特徴量

### 4-1. データベース層の構築 ✅
- [x] `database.py` を新規作成
  - SQLiteスキーマ定義（8テーブル: races, results, beforeinfo, odds, player_stats, predictions, reflections, motor_stats）
  - インデックス定義（Date, RaceID等のキーカラム）
  - WALモード + NORMAL同期で読み書き性能最適化
  - テーブル別CRUD関数（insert_races, get_races_by_date 等）
  - `query_df()` — SQLクエリ → DataFrame 変換
  - `migrate_csv_to_db()` — 既存CSV一括マイグレーション
  - `python database.py` でスタンドアロン実行可能
- [x] 既存CSVデータとの互換: CSV書き込み維持 + DB同時書き込み（デュアルライト方式）

### 4-2. 全スクリプトのDB対応 ✅
- [x] `local_collect_race_data.py` — Job 4（モーター成績取得）追加 + `_sync_csv_to_db()` で全daily CSVをDB同期
- [x] `local_ai_pipeline.py` — 予測・反省保存時にDB同時書き込み
- [x] `retrain_model.py` — daily→past マージ時にDB同時INSERT
- [x] `generate_dashboard_data.py` — `import database` 追加（将来のDB読み込み対応準備）
- [x] `build_features.py` — DB優先読み込み、CSVフォールバック付き

### 4-3. モーター特徴量の追加 ✅
- [x] `collect_race_data.py` に `scrape_motor_stats(jcd, date_str)` を実装
  - URL: `https://www.boatrace.jp/owpc/pc/race/motorlist?jcd={jcd}&hd={date_str}`
  - 各モーターの勝率・2連率・3連率を取得
  - `MOTOR_STATS_HEADERS` 定数を追加
- [x] `local_collect_race_data.py` に Job 4（モーター成績収集）を追加
  - 翌日開催会場のモーター成績をDB直接保存
  - 最新日付チェックでスキップ対応
- [x] `build_features.py` に `B{n}_MotorWinRate`, `B{n}_Motor2inRate` を追加
  - DB内のmotor_statsテーブルから会場×モーター番号でマッチング
  - モーターデータ未整備時は0埋め（既存動作に影響なし）

---

## Phase 5: ダッシュボードUI改善

### 5-1. 集計データの拡張 ✅
- [x] `generate_dashboard_data.py` に場所別(`venue_stats`)・レース番号別(`race_stats`)の集計を追加
- [x] EV分布データ(`ev_stats`)の追加
- [x] AI推奨理由の抽出(`parse_reasoning()`)を追加
- [x] Payout安全化（文字列/空値ガード、ゼロ除算ガード）

### 5-2. フロントエンド改善 ✅
- [x] `dashboard/src/App.jsx` に場所別勝率チャート（Venue Hit Rate）を追加
- [x] EV分布チャート（EV Distribution ROI）を追加
- [x] レース番号別分析チャート（Race Number Analysis: Hit Rate + ROI 二軸）を追加
- [x] AI推奨理由サマリー表示（トグル開閉式）
- [x] モバイルレスポンシブ対応（768px + 480px ブレイクポイント）

---

## 実施順序

```
Phase 1（オッズ+EV）   ✅ 完了
  ↓
Phase 2（2着3着予測）   ✅ 完了
  ↓
Phase 3（教訓分類）     ✅ 完了
  ↓
Phase 4（SQLite移行）   ✅ 完了
  ↓
Phase 5（UI改善）       ✅ 完了
```

## 備考

- DeepSeek-R1:14b → Gemma4:e2b に移行済み（2026-04-16）
- 各Phase完了時にダッシュボードでROI変化を確認し、効果測定を行う
- Phase間で依存関係があるもの（例: Phase 2-4はPhase 1のオッズデータに依存）は前Phaseの完了を待つ

---

## Phase 6: コアモデルの根本的修正

> 詳細仕様は `spec.md` の「Phase 6」を参照

### 背景

コードレビュー（2026-04-16）で判明した3つの根本問題に対処する。
問題: ①データリーク（ランダム分割）、②クラス不均衡未対応、③3連単確率の正規化バグ

### 6-1. 時系列分割への変更（最優先）

- [ ] `retrain_model.py` の `train_single_model()` を時系列分割に変更
  - `train_test_split()` を削除
  - `time_series_split(df, feature_cols, target_col, val_days=60)` を実装
  - Dateカラムを `_get_feature_and_target()` 内で保持するよう変更
  - A/Bテストも同じ時系列分割で評価
- [ ] 変更後の精度数値を記録（ベースライン比較用）

### 6-2. クラス不均衡補正

- [ ] `retrain_model.py` の LightGBM params に `is_unbalance: True` を追加
- [ ] 変更前後で2〜6号艇の的中率を比較記録

### 6-3. 条件付き確率の正規化修正

- [ ] `local_ai_pipeline.py` の `estimate_trifecta_probs()` に正規化処理を追加
  - 各条件付き確率が「除外インデックスを除く合計=1」になるよう正規化
  - `_normalize_excluding(probs, exclude_indices)` ヘルパーを実装
- [ ] 同じ修正を `auto_research/experiment.py` の `estimate_trifecta_probs()` にも適用

---

## Phase 7: 特徴量エンジニアリングの強化

> 詳細仕様は `spec.md` の「Phase 7」を参照

**※ 組み合わせや閾値の最適化は `auto_research/` の自己改善ループが自動実施。**
**人手では「新しいデータソース接続」と「基盤コード整備」のみ行う。**

### 7-1. 選手の短期調子指標（直近勝率）

- [ ] `build_features.py` に短期勝率の計算ロジックを追加
  - `past_race_data.csv` + `past_history_results.csv` を Date ソートして結合
  - 各選手・各レースの時点で「直近30日の1着率」「直近7日の1着率」を算出
  - カラム名: `B{n}_WinRate_30d`, `B{n}_WinRate_7d`, `B{n}_Top3Rate_30d`
  - 注意: **当日以降のデータを参照しないこと**（未来リーク禁止）

### 7-2. 選手×会場の相性

- [ ] `build_features.py` に選手×会場別成績を追加
  - 過去データから「選手ID × 会場」の通算1着率を算出
  - カラム名: `B{n}_VenueWinRate`
  - 最低出走数（例: 5走以上）を条件に設定。不足時はリーグ平均で補完

### 7-3. 展示タイムの変化量

- [ ] `build_features.py` に展示タイム変化量を追加
  - 直近3走の平均展示タイムとの差分を特徴量化
  - カラム名: `B{n}_ExTime_Delta`
  - 同会場・同コースの直近値を使用するのが理想（データ量に依存）

### 7-4. モーターの使用期間

- [ ] `build_features.py` にモーター使用開始からの累計出走数を追加
  - `past_race_data.csv` から モーター番号 × 会場 で出走数を集計
  - カラム名: `B{n}_MotorAge_Races`

---

## Phase 8: LLMプロンプトの最適化

> 詳細仕様は `spec.md` の「Phase 8」を参照

### 8-1. Temperature変更（即実施可能・低リスク）

- [ ] `local_ai_pipeline.py` の `call_deepseek()` の temperature を `0.7 → 0.3` に変更
- [ ] `morning_odds_runner.py` の Ollama 呼び出し箇所も同様に変更
- [ ] 変更後1週間の予測傾向を確認（特定組み合わせへの偏りが減るか）

### 8-2. Chain-of-Thoughtプロンプトの追加

- [ ] `local_ai_pipeline.py` の予測プロンプトを5ステップの推論形式に変更
  - ステップ1: 1号艇の支配力評価
  - ステップ2: 最大脅威艇の特定
  - ステップ3: 気象・外乱要因の評価
  - ステップ4: 教訓の適用
  - ステップ5: EV上位から最終推奨決定
- [ ] `morning_odds_runner.py` も同様のステップ形式に変更

### 8-3. 教訓活用プロンプトの改善

- [ ] 教訓注入部分のプロンプトを「今回のレースへの関連理由を明示させる」形式に変更
  - 両ファイル（`local_ai_pipeline.py`, `morning_odds_runner.py`）が対象

---

## 実施順序（推奨）

```
Phase 6-1（時系列分割）      ← 最優先。精度評価の信頼性を確立
  ↓
Phase 6-2（クラス不均衡）    ← 6-1と同時着手可能
  ↓
Phase 6-3（確率正規化）      ← 6-1と同時着手可能
  ↓
Phase 8-1（Temperature）    ← 軽微なので6と並行実施可能
  ↓
Phase 7（特徴量強化）        ← 自己改善ループで並行進行
  ↓
Phase 8-2/8-3（CoT）        ← Phase 6完了後に効果測定してから実施
```

## 現在のステータス（2026-04-16）

- Phase 1〜5: ✅ 完了
- Gemma4:e2b への LLM 切り替え: ✅ 完了
- auto_research 自己改善ループ構築: ✅ 完了（ベースライン: ROI 659.95%）
- Phase 6〜8: 📋 計画策定完了・実施待ち

---

# 🔧 運用トラブル対応（2026-04-17〜2026-04-18）

## 最終更新: 2026-04-21 10:45

## 現在のステータス

**運用トラブル対応すべて完了。予測パイプラインの全層接続をコード検証＋実機シミュレーションで確認済み。models と build_features の不整合も手動 retrain で解消、健全な状態。**

### 予測対戦拡張（2026-07-24）
- [x] Grok API を予測対戦の任意参加者として追加（APIキー未設定時は他の処理を継続）
- [x] Grokの買い目・推論を対戦画面に表示
- [ ] `XAI_API_KEY` 設定後、初回の実API予測を実行して確認
- [ ] Gemini先生・Claude先生の新規1000件データで再学習（既存モデルは保持）
- [ ] Gemma 4 E2Bの最小QLoRAメモリテスト（6GB VRAM）
残課題はバリデーション窓シフト問題の検討のみ（急がず数日様子見）。

## 判明した真因（2026-04-18）

- GitHub Actions は全 green（壊れていなかった）
- `main_runner.py` の `push_to_github()` で `files_to_add` が `dashboard_data.json` と `loop_results.json` の2つだけ
- 実際には毎夜更新される `daily_odds_3t.csv` など他のCSVが add 対象外だった
- `dashboard_data.json` に差分がない日があると `git commit` が "nothing to commit" で失敗 → push もスキップ
- 結果として 2026-04-16 以降、夜バッチの更新が GitHub に反映されていなかった

## 次回やること（再開時の第一歩）

1. **04/22 以降の 3am ループ + 5am LINE通知が安定稼働するか見守り**（数日）
   - `auto_research/loop_log.txt` と LINE 着信を毎朝チェック
2. **バリデーション窓シフト問題の対処を判断**（下記「新規発覚」参照）
   - 案A: バリデーション期間を固定（evaluator.py か experiment.py 改修）
   - 案B: 実行開始時に無改造ベースラインを走らせて改善幅で評価
3. **（必要なら）別件で未コミットのファイルを整理**
   - `main_runner.py` + `utils/` — ことちゃんRAG連携（masaru さんの別作業）
   - `dashboard/package*.json` — Vite 8→7 ダウングレード（戻すか残すか要判断）

## 再開時のシステム現状（重要）

- **予測パイプラインの全層接続は検証済み（2026-04-21）**
  - 層1 データ → 層2 build_features → 層3 retrain/experiment → 層4 predict → LLM → LINE すべて接続
  - `past_data/ml_features.csv`（113,120行、187特徴量）と `models/lgb_model_*.txt` は完全一致状態
  - 実機シミュレーション: 大村 12R（04/20）で 1号艇 P=0.584 など合理的な確率が出力された
- **自動実行スケジュール**
  - 03:00 `BoatRaceAI_SelfImproveLoop` → `run_loop.bat` → claude 自己改善ループ
  - 05:00 `BoatRaceAI_NotifyResult` → `python notify_loop_result.py` → LINE サマリー通知（二重化保険）
  - 夜バッチ `run_daily.bat` → main_runner.py → 自動 commit & push
  - 朝バッチ `run_morning.bat` → morning_odds_runner.py → EV予測 & LINE
- **現在のベストスコア: 903.42**（exp #153、commit `6ef8d9a`）
- **但しバリデーション窓シフトにより現データでの評価は 212.39** → 同コードでも日によってスコアがブレる問題あり

## 新規発覚（2026-04-20 のループ結果より）

**バリデーション窓シフト問題**: 新レースデータが毎日DBに追加されることで評価の「最新30日窓」が前進し、同じコードでもスコアが日によって大きくブレる。例: 04/19 時点でのベスト 903.42 が、04/20 時点で同コード再実行すると 212.39。これはコード劣化ではなく評価データの入替による現象。loop の「ベスト超え」判定が成立しにくくなっている。

## 今回の調査で判明した事実（再発防止メモ）

### ① 3時のタスクが届かなかった一次原因
- `auto_research/run_loop.bat` の **`cd /d` が効いていなかった**
  - 原因: bat ファイルが UTF-8 保存 + 内部に日本語コメントがあり、cmd が parse を誤る
  - 修正済: `cd /d "%~dp0.."` に変更（bat自身の位置基準）

### ② LINE 通知が届かなかった二次原因
- `auto_research/notify_loop_result.py` の `print(msg)` が **絵文字（🤖📊等）を cp932 で出力できず UnicodeEncodeError で死亡**
- LINE送信は print の後に実行されるため到達できていなかった
- 修正済: `sys.stdout.reconfigure(encoding="utf-8")` と `safe_print()` ラッパーを追加

### ③ ダッシュボード結果ページが見れない真因
- **ローカル dist/ が 2026-03-29 で停止、GitHub Pages デプロイが 2026-03-19 で停止**
- Windows + Node v24 + rollup/rolldown ネイティブバイナリの組み合わせで `npm run build` が **exit 0xC0000409（STACK_BUFFER_OVERRUN）で無言クラッシュ**
  - Vite 8/7 どちらでも同じ、ソース最小化しても再現
  - **このマシンでのローカルビルドは事実上不可能**
- 正しい解決策は GitHub Actions（Ubuntu）でビルド → Pagesデプロイさせること
  - でも Actions が 3/19 から動いていない → 原因調査が次のステップ

### ④ ローカル閲覧の暫定手段
- `cd dashboard && npm run dev` でローカル dev サーバーは正常起動可能
- ブラウザで `http://localhost:5173/Play/` にアクセスすれば最新ソースで表示できる

## タスク一覧

- [x] A. `notify_loop_result.py` の UnicodeEncodeError 対策
- [x] B. 手動で LINE テスト送信（24試行サマリー）
- [-] C. ローカル dashboard rebuild（**Windows環境で実行不能と判明 → スキップ**）
- [x] D. `run_loop.bat` の堅牢化 ✅ 2026-04-18 完了
  - `pause` を削除、leading space を除去
  - `claude` と `notify_loop_result.py` の ERRORLEVEL を個別にログ
  - `cwd=%CD%` を開始ログに含めて cwd 問題の診断用情報を残す
  - `PYTHONIOENCODING=utf-8` 設定
- [x] E. **GitHub Pages 再デプロイ（最優先）** ✅ 2026-04-18 完了
  - 真因: Actions ではなくローカルpush不足だった
  - 1fa8fea で 04/18 の dashboard データを push → Actions が正常発火、27秒で green
- [x] 優先2. `main_runner.py` の `push_to_github()` 修正 ✅ 2026-04-18 完了（13b04ce）
  - `files_to_add` を8ファイルに拡張
  - `check=True` 外し、"nothing to commit" を吸収
  - push は commit 結果に関係なく必ず試行
- [x] 優先3. `run_morning.bat` にログ出力を追加 ✅ 2026-04-18 完了
  - stdout/stderr を `logs/morning.log` に追記、開始/終了タイムスタンプ + `ERRORLEVEL` を記録
  - `PYTHONIOENCODING=utf-8` 設定、`.gitignore` に `logs/` を追加
- [x] F. タスクスケジューラ設定見直し ✅ 2026-04-21 完了
  - `BoatRaceAI_SelfImproveLoop` を「ユーザーのログオン状態にかかわらず実行」に変更（masaru さん GUI 操作）
  - 04/21 3am で自動起動を確認、claude は正常完走
- [x] G. LINE通知の独立タスク化 ✅ 2026-04-21 完了（追加対応）
  - 04/21 3am 実行で `notify_loop_result.py` が run_loop.bat 内で発火せず LINE 未着
  - 手動で `python auto_research/notify_loop_result.py` を実行してサマリー送信成功
  - run_loop.bat の notify 呼び出しがタスクスケジューラ経由で不安定なため、独立タスク `BoatRaceAI_NotifyResult` を毎日 5:00 実行で新規作成
  - masaru さん GUI 作業で作成＋テスト成功
- [x] H. 予測パイプラインの全層接続検証 ✅ 2026-04-21 完了
  - Explore agent でコード上の接続をファイル名・行番号で検証（全 ✅ OK）
  - 実機シミュレーションで 1 レース分の予測を通し、確率が正常に出ることを確認
  - 軽微な不整合（`Venue_HighPayoutRate` の有無）を検出
- [x] I. models と build_features の不整合を解消 ✅ 2026-04-21 完了
  - `python retrain_model.py` を手動実行
  - モデル特徴量 188 → 187 に再学習、ml_features.csv と完全一致
  - 旧モデルは `*_backup.txt` に自動退避
  - 1着精度 73.06% / 2着精度 34.96% / 3着精度 27.94%

## 修正したファイル（未コミット分）

- `dashboard/package.json` + `dashboard/package-lock.json` — Vite 8.0.0 → 7.3.2、@vitejs/plugin-react 6 → 4 にダウングレード（ビルドクラッシュ調査の過程で変更、戻しても可）

## コミット済み（運用トラブル対応シリーズ）

- `1fa8fea` Auto-update dashboard data: 2026-04-18 11:30:00（daily_data 反映）
- `13b04ce` fix: 夜バッチのGitHub同期を複数ファイル対応＋commit失敗を吸収
- `bf36d71` fix: バッチスクリプトのログ出力とUTF-8対応を強化
- `724567f` feat: 自己改善ループに停止条件を追加（50試行/3時間/連続10回未更新）
- `37f5baa`〜`6ef8d9a` auto_research ループの自動改善（686.09 → 903.42）
- `32f2a39` chore: 自己改善ループの実験ログ追加と朝バッチ反映（2026-04-20）
- `cd0ae5a` docs: task.md を 2026-04-21 時点の運用トラブル対応完了状態に更新

## 作業ログ

### 2026-04-17
- 朝の LINE 通知が届かなかった件を調査開始
- タスクスケジューラ BoatRaceAI_SelfImproveLoop は 3:00:01 に起動していたが exit code 1 で失敗
- `loop_log.txt` が生成されていなかったため bat の初期段階で失敗と判明
- bat の日本語+UTF-8 問題を発見、`%~dp0..` 基準に修正
- 手動実行で claude ループが正常動作（24試行、3件コミット、ベスト 659.95 → 686.09）
- LINE通知が来ない原因を追跡 → `notify_loop_result.py` の print が UnicodeEncodeError で死亡と特定
- `safe_print` で修正、手動で LINE 送信成功（14:58）
- ダッシュボード問題: ローカル build が Windows ネイティブバイナリクラッシュで実行不能と判明
- 対応を GitHub Actions 経由に方針転換、ユーザーからの Actions スクショ待ちで中断

### 2026-04-18
- LINE試験メッセージの着信をユーザーが確認
- GitHub Actions スクショを受領 → **全 green、最新 Auto-update は 04/16 01:08 で停止**と判明
- 真因特定: `main_runner.py` の `push_to_github()` で `files_to_add` が2ファイルだけ → 差分なしで commit 失敗 → push スキップ
- 優先1実行: daily_data/ と dashboard/public/daily_data/ を手動 add → commit `1fa8fea` → push → Actions 27秒で green、ダッシュボード復旧
- 優先2実行: `main_runner.py` の `push_to_github()` を修正（add 対象を8ファイルに拡張＋commit失敗吸収＋push必須化）→ commit `13b04ce` push 済み
- 優先3実行: `run_morning.bat` にログ出力追加（`logs/morning.log`）、`PYTHONIOENCODING=utf-8` 設定、`.gitignore` に `logs/` 追加
- 優先4実行: `run_loop.bat` から `pause` 削除、leading space 除去、`claude`/`notify` の ERRORLEVEL を個別ログ、cwd を開始ログに含める

### 2026-04-19
- 朝の時点でループがまだ動いており、Max プラン契約確認 → 追加料金は発生しないが週次枠消費の懸念あり
- `program.md` に停止条件（50試行/3時間/連続10回未更新）を追加 → commit `724567f` push
- ループ中のコミット（`37f5baa`, `9ac41b1`, `0243367`, `6ef8d9a`）が実は未 push だったため、このとき一緒に origin に上がった（ベスト 903.42）
- ユーザーが手動でループ停止 → build_features.py の失敗実験残骸を revert、残りを commit `32f2a39` push

### 2026-04-20
- 3am 自動実行が新 program.md で走行 → **停止条件 #3 発動で正常終了**
- cwd も正しく記録された（昨日の run_loop.bat 改修が効いた証拠）
- バリデーション窓シフト問題が浮上（ベースライン 212.39、過去ベスト 903.42 との乖離）

### 2026-04-21
- 深夜にタスクスケジューラ「ログオン状態にかかわらず実行」設定変更 完了（masaru さん GUI 作業）
- 04/21 3:00 に自動起動、10試行（#188〜#197）で停止条件 #3 発動、03:41 終了
- しかし LINE が来ず → loop_log.txt に `loop end` / `notify done` のエントリが無い → run_loop.bat が notify に到達する前に途中終了している判明
- `notify_loop_result.py` を手動実行して今朝分のサマリーを LINE 送信成功
- 再発防止として独立タスク `BoatRaceAI_NotifyResult`（毎日 5:00）を作成、テスト実行で LINE 到達を確認
- これで run_loop.bat が途中死しても 5:00 に必ずサマリーが届く体制に
- ユーザーから「予測パイプラインが本当に繋がっているか」懸念 → 全層の接続をコード検証＋実機シミュレーションで確認（全 ✅）
- 検証中に models と build_features.py の軽微な不整合（Venue_HighPayoutRate）を発見 → `python retrain_model.py` 手動実行で解消
- 再学習結果: 1着 73.06% / 2着 34.96% / 3着 27.94%、backup 自動生成、ml_features 完全一致

### 2026-08-03
- Codexを7番目の予測対戦参加者として追加
- ChatGPTログイン済みCodex CLIを使い、当日レースを1回にまとめて5点予測する処理を実装
- `daily_codex_predictions.csv`、当日レースJSON、全期間サマリーを接続
- 対戦画面・モデル別ダッシュボード・的中率/収支推移・過去レース表へCodexを追加
- 当日20レースの実予測を生成し、全行5点・JSON反映20件を確認
- Python構文・JSX構文は合格。Viteは2,409モジュール変換後の成果物書出し段階で無言終了する既知のローカル環境問題が継続

### 2026-08-04
- Codex予測へ自動フィードバック学習を追加
- 予測日より前の過去結果だけを使用する未来情報混入防止を実装
- 過去22,085レースから各当日レースに近い60件を抽出し、艇番別勝率・頻出結果・実例をプロンプトへ追加
- Codex自身の確定済み成績（的中率・ROI・1着艇の見落とし傾向）を翌日以降の予測材料へ追加
- Codex固有成績が200件未満の間は参考値として扱う過学習防止を追加
- モデル別ダッシュボードのCodexタブへ学習件数表示を追加
- 新方式で2026-08-04の19レースを再予測し、全件5点・統合JSON反映を確認
- toto予測対戦にCodexを追加（第1予測回から統計・Gemini・Codex・ユーザーを比較）
- toto Codexは回ごとに全試合を1回で一括予測し、ChatGPT認証のCodex CLIを利用するためAPIキー不要
- 過去に確定したCodexの的中率・選択別精度・直近のミスを次回予測に反映（対象回以降の結果は除外）
- toto週次更新を「答え合わせ → Gemini/Codex予測 → 表示データ生成」順に変更
- 2026-08-04時点で第1645回は販売開始前（2026-08-08開始）のため、過去回への後付け予測は行わず次回更新から開始する方針とした
- 週次バッチも販売中（締切が今日以降）の回のみ予測するガードを追加し、既存の過去回にCodex予測が後付けされないことを確認
- ボートレースのモデル別ダッシュボードを全面リデザイン（視認性・情報階層・モバイル対応を改善）
- 7日/30日/全期間の切替が実際のモデル別集計に反映されていなかった問題を修正（ブラウザ確認で全期間913件 → 直近7日69件を確認）
- デスクトップ/モバイル表示、Codexタブ、totoのCodex列・未生成案内をブラウザで確認、コンソールエラー0件

### 2026-08-14
- モデル別ダッシュボードからDetを非表示化（予測データ・LightGBM週次学習処理は復元可能な状態で保持）
- 推移指標をROI・収支・的中率・的中件数・的中金額の5種類へ拡張
- 全教師・全モデルを同じ期間、同じ累積基準で1枚に重ねる比較グラフを追加
- 選択モデルの個別グラフも5指標の切替へ連動するよう変更
- 比較期間の終端を確定結果の最終日に統一し、モデル間で期間基準がずれないよう修正
- `ModelDashboard.jsx` 単体lint合格、本番ビルドは一時出力先で成功（2,409モジュール）
- 実データで全5指標・全7モデル・Det非表示をブラウザ確認し、コンソール警告/エラー0件
- 自動実行状況を確認：朝バッチは2026-08-14 09:00成功、日次バッチは2026-08-13 23:00成功、未実行0件
- 学習方式を再確認：Detは月曜週次再学習、Codexは毎予測時に確定済み結果を参照、学習Gemma3種は教師データ作成時の固定学習で日次再学習なし

### 2026-08-15
- 累積では必ず右肩上がりになる「的中件数」「的中金額」を、日別実績の棒グラフへ変更
- 全モデル比較は各日のモデル別棒グラフ、選択モデルは1日1本の棒グラフで表示
- 予測がある日の0件/0円と、予測自体がない日を区別して集計
- ROI・収支・的中率は従来どおり累積推移を維持
- 単体lint・本番ビルド成功。実データで全期間/30日表示と両日別指標を確認し、ブラウザ警告/エラー0件
- 全モデル比較を主表示とし、その下の選択モデル個別グラフ・会場別的中率を非表示化
- toto第1645回の欠損を調査。統計予測は13試合中8試合あり、残り5試合は「Ｇ大阪/ガンバ大阪」等のチーム名表記ゆれで照合失敗
- toto Gemini欠損の原因を特定。`Toto_Weekly` が使う `.venv` に `google.generativeai` が無く、Geminiだけ起動前に失敗していた
- toto自動タスクは内部エラーを許容して全体を成功終了するため、タスク結果0でもGemini成功を保証しないことを確認
- totoのチーム名エイリアスとUnicode幅正規化を追加し、第1645回の統計表示を8/13から13/13へ改善
- 統計表示をAI予測ファイルから独立させ、Gemini未生成でも表示データ生成時に13試合分を算出するよう変更
- `.venv` に `google-generativeai 0.8.5` を導入。Geminiの部分成功再利用、不完全ファイルの本番採用防止、失敗時exit 1を実装
- toto日次バッチへ実行ログと終了コード伝播を追加。正常系exit 0、Gemini無料枠超過の異常系exit 1を実機確認
- Gemini実予測は当日の無料枠20件を消費済みのため第1645回を完了できず、次回以降は未予測分だけ再試行する
- Vite設定のES Modules互換性を修正し、検証モードの本番バンドル（2,409モジュール）成功を確認

### 2026-08-23
- 成績画面を白・グレー基調のシンプルな「モデル比較」へ再設計し、初期期間を直近7日に変更
- 7日・30日・全期間について、全モデル合計とモデル別の収支、ROI、的中率、対象数、最大ドローダウン、前期間比を共通計算
- 「通常予測」を実体が分かる「基本Gemma」へ改称し、Detを比較画面・今日の予測・過去成績から非表示化
- 累積で必ず増える的中件数・的中金額のグラフを廃止し、「累積収支」と「7日移動ROI」の比較へ集約
- 今日の予測の過去成績へ7日・30日・全期間の切替を追加し、横並びの比較表を中心に整理
- LINE通常通知を個別買い目・答え合わせから、直近7日の全モデル合計とモデル別ランキングへ変更
- 朝バッチの個別買い目LINEを停止（開催なし・エラーなどの運用通知は継続）
- 自動学習の範囲を再確認し、毎週月曜の対象は基本予測内LightGBMのみ、他モデルは自動再学習未接続と画面へ明記
- Det除外、全モデル合算、LINE文字数、Python構文、ESLint、本番相当Viteビルドを確認
- ローカルブラウザ接続が利用できなかったため、今回の実画面目視確認は未実施
- PC・スマホ両対応のレスポンシブUIを追加。モデル比較表はスマホでモデル別カードへ変換
- スマホの比較グラフは全モデル合計または選択モデルに絞り、凡例と折れ線の混雑を解消
- 今日の予測はPCで3列・スマホで1列、toto試合カードはPCで2列・スマホで1列に最適化
- ナビゲーション、期間切替、見出し、入力欄、表の罫線、チャートツールチップを白基調へ統一
- レスポンシブ変更後のESLintと本番相当Viteビルド（2,409モジュール）に合格

### 2026-08-26
- 基本Gemmaをダッシュボードの順位・全モデル合計・比較グラフから除外
- LINE通知と既存の予測処理は変更せず、ダッシュボード専用集計を共通JSON内に追加

### 2026-08-29
- ボートレースLINEのモデル別表示を2行へ整理し、収支の次の行に的中率と「前7日比」を表示。モデル別ROI・レース数を削除
- ダッシュボード冒頭へ「今いちばん良い」「上向き候補」「全体の様子」を追加し、初期グラフを7日移動ROIへ変更
- 比較グラフをランキングより先に配置し、累積収支・7日移動ROI・日別収支・損失幅の4種類へ整理
- モデル別ランキングをアイコン付き2段カードへ変更。収支・前期間比と、ROI・的中率・最大損失幅だけに情報を絞った
- 全モデル合計はROI・的中率・最大損失幅を横並び、総投資を下段へ変更。「画面の見方」「自動学習の現状」は画面から削除
- toto第1646回は公式toto結果一覧にも存在せず、取得漏れではないことを確認
- toto公式結果ページから試合結果・1〜3等配当を自動取得する処理を追加し、週次バッチへ接続
- 保存済み6回（1634〜1637・1645・1647）の公式結果を補完。確定済みビューの配当未取得を0件にした
- Python構文、ESLint、ローカル開発サーバー応答、データ整合性を確認。ブラウザ未接続のため実画面目視は未実施
- Vite本番ビルドは既知のローカル環境問題により2,409モジュール変換後に無言終了（開発サーバーとESLintは正常）
- Geminiアイコンが星座記号、Claudeアイコンが単なる文字に見える問題を修正。GeminiはGoogle四色のG＋輝き、Claudeはオレンジの放射状マークへ変更
- LINEのモデル比較・全モデル合計からも基本Gemmaを除外し、ダッシュボードと同じ6モデルへ統一

### 2026-09-01

- 現行の学習方式を再調査し、CodexはRAG型、Gemini・Grokは自己フィードバック未接続、Gemmaは固定推論、LightGBMは週次再学習であることを整理
- Claude Code CLIがClaude Max認証で利用可能であり、ツール無効・非対話・構造化JSON出力に対応できることを確認
- ユーザーと、Claudeのボートレース・toto参加、後付け予測禁止、自己フィードバック分離、障害分離、Gemma候補評価の条件を合意
- `spec.md` にClaude参加・共通フィードバックRAG・Gemma再学習の機能要件、非機能要件、受け入れ条件、実施順序を追記
- 本ファイルへPhase 2の実装タスクと次回着手点を追記
- Phase 1の文書化まで完了。コード実装はユーザーの再承認待ち
