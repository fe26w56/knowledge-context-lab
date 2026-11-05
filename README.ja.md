# Knowledge Context Lab

AIエージェントに渡す根拠を、原文・版・条件・例外とともに保つローカルPythonライブラリです。開発プレビュー 0.7.0rc4.dev1、MITライセンス。

## Notion Hub 開発プレビュー（0.7.0rc4.dev1）

`[hub]` 追加機能には、永続ディスクを使う Linux/macOS の単一ホスト向け共有 HTTP hub、bot クライアント、Notion 操作用の保護付き処理を含みます。dev1 wheel またはチェックアウトから `python -m pip install '.[hub]'` で導入し、bot ごとに接続資格情報と reader ID を分けます。

[Notion Hub 運用ガイド](docs/notion-hub-operations.md) · [dev1 wheel](releases/0.7.0rc4.dev1/knowledge_context_lab-0.7.0rc4.dev1-py3-none-any.whl)

同じNotion接続でも、AIごと・ページごとに最後に受領した版を保存します。未読なら全文、既読ならそのAIが受け取った版からの差分を返します。エージェントが受領を確定するまで既読版は進みません。MCPホストがPythonを起動し、受領履歴を永続ディスクに持ちます。[設定と使用例](docs/workspace-handoff.md#agent-facing-mcp) · [インストール用wheel](releases/0.7.0rc4.dev0/knowledge_context_lab-0.7.0rc4.dev0-py3-none-any.whl)

既知のテーマに対して確認済み原文範囲を返し、関連資料の訂正・追加を検知したfresh snapshotでは古い内容を返さず再確認待ちにします。この検索方式は、利用者が指定したテーマと確認済みの原文範囲を使います。

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python scripts/demo_reviewed_context.py
```

架空データの登録→確認→原文引用→訂正による失効を実行します。モデルAPIは呼びません。

自作の最終12意図×3反復では、全文方式と確認済み原文範囲方式の両方が36/36で必要事項への回答または適切な不明判定を満たし、実API入力は24,801→21,969（11.4%減）でした。引用ID方式は2回答で必須事項を省いたため、標準には採用していません。誤答確率の統計的低下や、人手確認込みの総費用削減を保証する結果ではありません。

他テーマの資料が100→1万件に増えても、固定テーマの参照入力中央値は382トークンで一定でした。この性質は同topic全文にもあり、DBの効果ではありません。同テーマ内に資料が増えれば再確認と入力増加が必要です。

[結果と再現方法](docs/phase-2-reuse-findings.md) · [利用ガイド](docs/reviewed-context-guide.md) · [英語README](README.md) · [公開内容の範囲](docs/publication-scope.md)
