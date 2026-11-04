# Phase 2 release candidate fixture

完全架空の診断fixture。独立ベンチマークではない。改善実装を見る前に40問と文書群を固定し、`FREEZE.json`にSHA256を記録した。`expected_source_ids`は採点側のメタデータで、検索requestには渡さない。文書は現行・旧版・提案、近似複製、private、長表、複数資料を含む。再生成は`PYTHONPATH=src .venv/bin/python scripts/create_release_fixture.py`だが、固定後の既存ファイルを上書きしないこと。
