# Notion Hub の接続と複数環境での同期

開発版 `0.7.0rc4.dev1` は、各 bot が受領した版から Notion の変更を取り込みます。共有サーバーは Notion に接続し、各 bot は専用の資格情報で接続して手元に本文を保存します。

実 Notion で合成テストページを2件使い、旧版の5クライアント・新版の6クライアントに差分を、未読の5クライアントに全文を配信しました。16件すべてで最終本文と読者別ハッシュが一致しました。2回の部分更新、子ページ探索、受領通知の応答喪失後の再起動復旧も確認しました。共有サーバーとクライアントは同じ Mac 上で HTTP 通信し、共有サーバーから Notion へは実際に HTTPS 接続しています。別マシン間の HTTPS 配置と長期常駐は未検証です。

## 1. Notion の接続設定

1. Notion 左側の **設定 → 接続** を開きます。新規作成の入口がなければ、設定で **開発者モード** を有効にし、サイドバーの開発者項目を開きます。
2. **新しい接続 / New connection** を選びます。名前は `Agent Hub Sync`、ワークスペースは Agent Hub があるものにします。認証方式が表示される場合は **API token**（内部接続）を選びます。作成時には Notion の開発者規約への同意が必要です。
3. コンテンツの読み取り・挿入・更新を許可します。細かな権限が表示される版では、ページタイトルを設定するためのプロパティ挿入も必要です。ユーザー情報・メールアドレスの権限は不要です。
4. 接続の **Content access → Edit access** で Agent Hub だけを選び、保存します。この入口がない表示では、Agent Hub ページの **右上の ••• → その他 / More → 接続 → 接続を追加** から `Agent Hub Sync` を追加します。表示によっては「その他」を挟まず「接続」が見えます。
5. 次のコマンドをターミナルで実行します。非表示の入力待ちになってから、接続の **Configuration → API token** 右端のコピーアイコンを押し、ターミナルへ貼り付けて Enter を押します。トークンをコマンド本文やチャットへ書かないでください。

```bash
python scripts/setup_notion_token.py --file /secure/private/notion-token
```

保存先はリポジトリの外の専用ディレクトリを指定します。既存ファイルは上書きしません。接続作成の入口がない場合、ワークスペース所有者の権限を確認します。

公式資料: [接続の作成](https://www.notion.com/help/create-integrations-with-the-notion-api)、[ページへの接続追加](https://www.notion.com/help/add-and-manage-connections-with-the-api)、[Markdown API](https://developers.notion.com/guides/data-apis/working-with-markdown-content)。画面名は Notion の表示言語や更新状況で異なります。

## 2. 共有サーバー

Python 3.11 以上の Linux または macOS と永続ディスクを用意します。1 つのプロセスで稼働させます。サーバーレスの一時ディスクや複数台からの共有 SQLite は対象外です。

```bash
python -m pip install -e '.[tokens,hub]'
context-lab-hub init \
  --directory /secure/private/hub \
  --token-file /secure/private/notion-token \
  --root 00000000-0000-4000-8000-000000000001 \
  --url https://hub.example.com/mcp \
  --bots 16
context-lab-hub serve --config /secure/private/hub/server.json
```

`--root` は実際の Agent Hub のページ UUID に置き換えます。複数指定できます。`--url` は実際に運用する HTTPS エンドポイントです。ローカル確認だけなら `http://127.0.0.1:8765/mcp` を使えます。

作成される `server.json` は Notion トークンの保存先、bot ごとの認証ハッシュ、読者 ID、許可するルートを保持します。`bot-01/client.json` などは各 bot 専用の接続資格情報です。サーバー設定と各 bot フォルダは 0700、設定ファイルは 0600 にします。秘密の設定を GitHub に置かないでください。

書き込み権限は初期値 `false` です。運用者が対象 bot の `write` を `true` にし、必要なら `roots` を検証用ページ配下に絞ります。設定変更はサービス再起動で反映されます。資格情報を別の bot と共用すると受領状態も共用されるため、実行環境ごとに別の reader を割り当てます。

外部接続では、既存の HTTPS リバースプロキシからこのプロセスへ転送します。公開 URL の Host を維持し、Authorization ヘッダーや本文をログへ保存しない設定にします。プロセスは既定で loopback の 8765 番だけに bind します。マシン用 Bearer 認証であり、OAuth の認可画面は提供しません。

## 3. 各 bot 側

各環境へ、その bot 専用フォルダだけを安全に渡します。Notion トークンはサーバーだけが保持します。各環境も Python 3.11 以上と同じソース版の `[hub]` 追加依存を使います。

```bash
# その場で配下を発見して保存
context-lab-bot --config /secure/private/bot-01/client.json sync

# 担当ページだけを定期確認。--page は複数指定できる
context-lab-bot --config /secure/private/bot-01/client.json watch --interval 60 \
  --page 00000000-0000-4000-8000-000000000002

# AI クライアントの stdio MCP コマンドとして登録
context-lab-bot --config /secure/private/bot-01/client.json mcp
```

MCP の例:

```json
{
  "mcpServers": {
    "agent-hub": {
      "command": "/absolute/path/to/venv/bin/context-lab-bot",
      "args": ["--config", "/secure/private/bot-01/client.json", "mcp"]
    }
  }
}
```

bot 用ツールは `discover`、`sync_page`、`get_page`、`sync_hub`、`create_page`、`replace_text`、`write_status` です。差分を復元して SQLite へ保存してからサーバーへ受領を通知します。保存前に落ちた場合は再取得、保存後の応答喪失は受領通知を再試行します。欠損・破損した手元の本文は全文から復旧します。

`sync_page` は差分を返し、変更がない場合は全文を返しません。`sync_hub` は件数と変更ページ ID を返します。新しい会話やモデルの文脈が消えた後は `get_page` で必要な本文を読みます。**ディスクへの保存完了は、AI がその内容を記憶していることを意味しません。**

## 4. 書き込みと競合

`get_page` の `sha256` を `replace_text.expected_sha256` に渡し、一度だけ現れる原文を指定します。`request_id` は書き込みごとに生成し、再送では同じ ID を使います。同じ ID に別の内容を載せると拒否されます。

- `completed`: API の結果と本文の読み戻しを確認しました。
- `rejected`: 書き込み前の検査で拒否しました。最新版と権限を確認します。
- `uncertain`: 実行された可能性があります。`write_status` と Notion の原ページを確認し、別 ID で同じ内容を自動送信しません。取得できたページ ID は記録されます。

Notion は書き込みを保存した後に 503 を返すことがあります。この実装は書き込みの盲目的な再送をしません。HTTP 応答を受け取る前に停止した場合、作成されたページ ID も不明なことがあります。原ページとその親を確認して解決します。[Notion の再試行仕様](https://developers.notion.com/reference/request-limits)

サーバー自身の書き込みは直列化します。Notion のブラウザや別の接続からも編集できるため、部分更新には `get_page` で読んだ最新版のハッシュと、返された Markdown の原文をそのまま使います。保存後、指定箇所以外も含めて本文を照合します。

作成時には親・タイトル・アクセス範囲を確認します。Notion がタイトルと同じ先頭見出しをページ名へ移した場合や、単純な段落内の単語中のアンダースコアをエスケープした場合は、読み戻した本文からハッシュを計算します。確認できる変換に該当しない差異は `uncertain` になります。

## 5. 運用と検証範囲

子ページ、ネストしたブロック内の子ページ、所有する子データベースの行を探索します。単なるリンク・メンション・別の場所から同期されたブロックを、探索範囲を広げる入口には使いません。各本文の取得前に親子関係を再確認します。不完全 Markdown、401/403/429/5xx、壊れたページネーションは成功した削除通知と区別します。

Notion の全ページを毎回同期する場合、API 呼び出しは文書数と階層の深さに応じて増えます。読み取りを 1 接続あたり約 2.5 リクエスト/秒に調整しています。大量資料での常時全件ポーリングの費用・待ち時間は未測定です。まず bot に必要なルートと対象ページに絞り、全文同期の間隔を調整してください。

`watch --page` は、指定したページだけのアクセス権と更新を毎回確認します。管理者が新しいページを探すときは `discover` を使います。引数なしの `watch` は、各周期でルート全体を探索して既知ページも照合します。

サーバーの `server-state/` と各 bot の `state/` を永続ディスクへ置きます。SQLite のコピーはプロセス停止中か SQLite の backup API で取得します。サーバー側の状態を戻す場合は bot 側の同期を再開して全文から再照合できます。クライアント状態を失った場合も新規 snapshot を要求します。

ローカル再現:

```bash
python -m unittest discover -s tests -p 'test_notion_hub.py'
python -m unittest discover -s tests -p 'test_bot_receiver.py'
python -m unittest discover -s tests -p 'test_hub_service.py'
```

これらの自動テストは合成の gateway を使い、認証エラー・権限取消・破損・再試行などを再現します。次の受入試験は実際の Notion トークンを使い、専用のテストページで探索、編集、配信、復旧を確認します。

実 Notion の受入試験用コマンド:

```bash
python scripts/accept_notion_hub.py \
  --token-file /secure/private/notion-token \
  --root 00000000-0000-4000-8000-000000000001 \
  --output /secure/private/acceptance-first-run
```

これは指定ルートの下に合成のテストページを2件作成します。既存資料の本文は置換せず、作成したページだけを部分更新します。5体が旧版、6体が新版、5体が未読の状態を実際の保存内容で確認したうえで、16体すべての本文と読者ごとの整合性ハッシュを検査します。テスト用の子ページ探索と、受領通知の応答喪失後の再起動復旧も確認します。

出力先はリポジトリ外の新しい非公開ディレクトリを指定します。書き込みの前後を `mutations.json` に記録し、結果は `receipt.json` に保存します。`uncertain` や途中終了の場合は、記録された request ID・ページ ID と Notion の状態を確認してください。別の出力先を指定して最初から自動再実行すると、ページを重複作成する可能性があります。

最初のテストページ作成だけで止まり、ログに作成先のページ ID がある場合は、新しい出力先と `--recover-first-create /secure/private/acceptance-first-run/mutations.json` を指定できます。記録されたページの親・タイトル・本文を照合できた場合だけ、そのページを引き継いで続けます。

このコマンドの一連の処理は、合成 gateway と実 HTTP クライアントを使う `tests.test_accept_notion_hub` で確認しています。その成功は実 Notion の受入試験成功を意味しません。
