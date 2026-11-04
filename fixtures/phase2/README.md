# Phase 2 固定評価データ

`corpus.json` と `dev.json` / `final.json` は、取得方式の改善実装を見る前に作成した架空の診断用データです。`FREEZE.json` に作成時刻、件数、SHA-256を保存しています。元の `fixtures/synthetic/` と `runs/synthetic-v1/` は参照しただけで変更していません。

各質問の `request` だけを検索器へ渡します。`expected_quotes`、`condition_quotes`、`obsolete_quotes`、`forbidden_quotes`、`rubric`、IDは採点側です。検索器へ正解や問題IDを渡す処理はありません。`answerable: false` は空結果を正答扱いにせず、情報不足・検索失敗・権限不足を別に記録します。

`dev` は設定選定と改善の診断用、`final` はその後の比較用です。同じチームが作った自作問題であり、独立ベンチマーク、第三者holdout、実運用の品質保証ではありません。結果を見て変更した場合、`final` も未見評価とは扱わず、変更履歴と再評価を記録します。実資料、個人情報、認証情報、実在サービスの根拠は含めません。
