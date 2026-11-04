"""Author and freeze the Phase 2 stability diagnostic fixture.

The core records and questions are deterministic. ``seed`` changes only
unrelated distractors; ``order_seed`` changes only record order.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).parent
DATE = "2026-11-03"


def _doc(id_, title, project, body, *, status="current", scope="shared", owner="team"):
    return {"id": id_, "title": title, "project": project, "status": status,
            "scope": scope, "owner": owner, "updated_at": DATE, "body": body}


def _body(title, overview, decision, conditions, evidence, handoff):
    return (f"# {title}\n\n## 概要\n{overview}\n\n## 決定事項\n{decision}\n\n"
            f"## 条件と例外\n{conditions}\n\n## 確認材料\n{evidence}\n\n"
            f"## 引き継ぎ\n{handoff}\n\n## 背景と運用記録\n"
            "この記録は作業の判断と根拠を後から追跡できるよう、対象範囲、確認時点、担当の役割を分けて残している。"
            "記録にない推測を現行の決定として扱わず、対象が別地域、別版、別期間の場合は元資料を追加で確認する。"
            "レビューでは、決定事項だけでなく条件と例外が同時に満たされているかを確認し、確認できなかった項目は未確認として引き継ぐ。\n\n"
            "## 運用上の注意\n"
            "同じ名称の記録が複数ある場合は更新日と状態を照合する。古い記録は変更の経緯を理解するために保存するが、現行の判断へ自動的に混ぜない。"
            "共有範囲が異なる資料を一つの結論へまとめるときは、閲覧権限を越えた内容を引用せず、参照可能な資料の不足を明示する。"
            "数値や期限を引用する際は、適用条件、例外、確認材料の識別子を併記し、次の担当者が同じ箇所を再確認できる状態にする。"
            "判断を更新した場合は更新日と変更理由を残し、前の記録を消さずに履歴として参照できるようにする。\n")
            


CORE = [
    _doc("st-cur-01", "Orion 通知運用", "orion", _body("通知運用", "Orionの障害通知を運用担当が確認する手順です。", "平日昼間の一次通知は10分以内に担当へ転送する。", "夜間は緊急度が高の場合だけ電話を使い、通常の更新は翌営業日にまとめる。緊急度が高でも顧客影響がない場合はチャット通知に留める。", "運用記録2026-10-21で転送時刻を確認した。", "次回訓練では夜間の例外を記録する。")),
    _doc("st-cur-02", "Orion 通知の例外", "orion", _body("例外対応", "同じ通知運用における判断基準を整理しています。", "顧客影響が確認できた障害は電話連絡を開始する。", "顧客影響が未確認なら電話を開始せず、15分ごとに状況を更新する。誤検知は記録だけ残して終了する。", "障害レビュー議事録OR-44に判断例がある。", "影響判定の担当者を次回当番表に追加する。")),
    _doc("st-cur-03", "Orion 通知の網羅表", "orion", _body("通知先一覧", "通知経路を確認するための現行一覧です。", "一次担当は運用チーム、二次担当は信頼性チームとする。", "休日は一次担当の代理を当番表から選ぶ。", "連絡先台帳OR-12を現行版として確認した。", "台帳の更新日を月初に確認する。")),
    _doc("st-cur-04", "Orion 古い通知方針", "orion", _body("旧方針", "過去の通知方針を保存しています。", "2026年6月までは全障害をチャットへ通知していた。", "この方針は2026年7月の現行方針で置き換えられた。", "旧レビューOR-19に記載されている。", "参照時は現行文書と混同しない。"), status="historical"),
    _doc("st-cur-05", "Orion 個人メモ", "orion", _body("個人メモ", "担当者だけが見る補助メモです。", "個別の連絡先はこのメモに記録する。", "所有者以外への共有は禁止する。", "アクセス監査OR-P7で非共有を確認した。", "所有者が月末に更新する。"), scope="private", owner="mika"),
    _doc("st-cur-06", "Orion 別地域の通知", "orion", _body("地域別運用", "欧州リージョンの通知経路を扱います。", "欧州の低緊急度通知は現地業務時間にメールで送る。", "日本リージョンの判断には適用しない。", "地域運用表OR-EU-3で確認した。", "地域境界を変更する場合は承認を取る。")),
    _doc("st-cur-07", "Beryl リリースゲート", "beryl", _body("リリースゲート", "Berylの本番リリース条件です。", "回帰テストが全件成功し、監査ログの保存を確認したら承認する。", "決済変更を含む場合はセキュリティレビューも必須。テストが未完了なら承認してはならない。", "リリース台帳BE-31に成功結果がある。", "次の候補は監査ログ容量を確認する。")),
    _doc("st-cur-08", "Beryl リリース監査", "beryl", _body("監査結果", "直近リリースの監査結果を記録します。", "監査ログは30日保存し、承認者とテスト結果を紐付ける。", "法務保留中の変更は本番へ進めない。緊急修正は事後24時間以内にレビューする。", "監査票BE-A8に承認者欄と保存確認がある。", "法務保留の解除を確認してから候補を更新する。")),
    _doc("st-cur-09", "Beryl カナリア手順", "beryl", _body("カナリア", "段階リリースの実施手順です。", "最初の5%で30分観測し、エラー率が1%未満なら25%へ進める。", "決済変更は5%から増やさず、セキュリティ担当の明示承認を待つ。", "観測票BE-C5に閾値と時刻がある。", "次回はロールバック演習を行う。")),
    _doc("st-cur-10", "Beryl 旧ゲート", "beryl", _body("旧ゲート", "Berylの旧リリース条件です。", "2026年8月以前は手動確認だけで承認していた。", "現行では回帰テストと監査ログが必要で、この記録は履歴としてのみ参照する。", "旧台帳BE-OLDに記載されている。", "現行ゲートと混同しない。"), status="historical"),
    _doc("st-cur-11", "Cedar 価格提案", "cedar", _body("価格提案", "Cedarの料金変更案を検討しています。", "2027年の価格変更は提案段階で、承認済みではない。", "財務レビュー完了と顧客通知の承認が揃うまで実施しない。採用されなかった案は現行価格を変更しない。", "提案書CD-P2に未承認の印がある。", "財務レビューの結果を提案書へ追記する。")),
    _doc("st-cur-12", "Cedar 現行価格", "cedar", _body("現行価格", "現在提供している料金表です。", "標準プランは月額4800円、年額48000円で提供する。", "教育契約は個別見積もりで、標準価格を自動適用しない。", "価格表CD-2026-10の承認欄を確認した。", "価格表の更新日は四半期ごとに見直す。")),
    _doc("st-cur-13", "Dahlia 移行条件", "dahlia", _body("移行条件", "Dahliaデータ移行の判断材料です。", "移行前バックアップ、件数照合、復元テストの3項目が揃えば実行する。", "個人情報を含む場合は暗号化鍵の確認を追加する。復元テスト失敗時は移行を停止する。", "移行記録DA-7に3項目の結果がある。", "担当者は復元ログを保存する。")),
    _doc("st-cur-14", "Dahlia 移行後確認", "dahlia", _body("移行後確認", "移行完了後の検査手順です。", "件数差分が0で、サンプル10件の参照が成功したら完了と記録する。", "差分が1件でもあれば完了扱いにせず、原因調査へ戻る。", "検査票DA-Q3に件数とサンプル結果がある。", "差分調査の担当を割り当てる。")),
    _doc("st-cur-15", "Eagle 会議履歴", "eagle", _body("会議履歴", "Eagleの意思決定履歴です。", "2026-10-18の会議では監視項目を週次で見直すと決めた。", "緊急変更は週次を待たず臨時レビューする。", "議事録EA-18に参加者と決定がある。", "次回会議で監視項目の実績を確認する。")),
    _doc("st-cur-16", "Eagle 古い会議", "eagle", _body("旧会議", "過去のEagle会議記録です。", "2026-08-02は月次レビューを採用していた。", "10月の決定で週次へ変更されたため、現行判断には使わない。", "議事録EA-08に変更経緯がある。", "履歴として保存する。"), status="historical"),
    _doc("st-cur-17", "Fjord 在庫一覧", "fjord", _body("在庫一覧", "Fjord倉庫の現行在庫を確認します。", "青ラベルの予備端末は12台、赤ラベルは7台である。", "棚卸し日が異なる倉庫の数字はこの一覧へ合算しない。", "棚卸し票FJ-11で数量を確認した。", "次回棚卸しで差分を記録する。")),
    _doc("st-cur-18", "Fjord 倉庫条件", "fjord", _body("倉庫条件", "Fjordの出荷判断条件です。", "青ラベルは検品済みなら出荷可能、赤ラベルは責任者確認後のみ出荷する。", "破損記録がある端末はラベルに関係なく出荷停止。", "検品記録FJ-Q4に状態がある。", "破損端末の隔離棚を確認する。")),
    _doc("st-cur-19", "Grove 権限規則", "grove", _body("権限規則", "Groveの共有資料アクセス規則です。", "共有資料はプロジェクトメンバーが閲覧できる。", "個人領域の資料は所有者本人だけが閲覧でき、別担当者へ転載しない。", "アクセス規則GR-2と監査結果を確認した。", "権限変更は管理者レビューを受ける.")),
    _doc("st-cur-20", "Grove 私有領域", "grove", _body("私有領域", "Grove管理者の私有領域に関する記録です。", "監査対象外の個人メモは所有者の作業用として保管する。", "所有者以外の質問には内容を回答せず、共有資料の所在だけ案内する。", "監査ログGR-P9でアクセス拒否を確認した。", "共有化が必要なら所有者が公開版を作る."), scope="private", owner="sora"),
    _doc("st-cur-21", "Harbor 全項目一覧", "harbor", _body("項目一覧", "Harborの現行チェック項目を列挙します。", "確認項目は本人確認、契約番号、連絡先、同意記録の4項目である。", "同意記録がない場合は処理を進めない。", "チェック表HA-4に4項目が列挙されている。", "項目追加はレビュー後に行う。")),
    _doc("st-cur-22", "Iris 不明な申請", "iris", _body("申請照会", "Irisの申請受付についての一般案内です。", "現時点の資料には、照会された特定申請の処理結果は記録されていない。", "推測で完了扱いにせず、受付番号を確認してから調査する。", "検索記録IR-0には該当なしとある。", "受付番号を取得して再照会する。")),
    _doc("st-cur-23", "Jade 分類手順", "jade", _body("分類手順", "Jade問い合わせを分類する手順です。", "請求、障害、要望の3分類を最初に選ぶ。", "複数に該当する場合は障害を優先し、判断理由を記録する。", "分類表JA-3に優先順位がある。", "分類理由の監査欄を埋める。")),
    _doc("st-cur-24", "Kite 横断証跡", "kite", _body("横断証跡", "Kiteの承認と実施を別資料で確認します。", "承認記録KI-A1と実施ログKI-L1の両方が揃った場合だけ完了とする。", "片方だけの場合は完了と回答せず、不足資料を明示する。", "監査台帳KI-9が2つのIDを関連付けている。", "不足時は担当へ照会する.")),
]

# Final-only projects are deliberately disjoint from the development projects.
CORE.extend([
    _doc("st-fin-01", "Atlas 申請条件", "atlas", _body("申請条件", "Atlas申請の開始条件を整理します。", "本人確認、申請番号、承認者記録が揃えば開始する。", "本人確認が欠ける場合は受付を保留する。", "台帳AT-1に3条件がある。", "次回は保留理由を記録する。")),
    _doc("st-fin-02", "Birch 申請例外", "birch", _body("申請例外", "Birchの審査例外を扱います。", "海外申請は追加の住所確認を行う。", "住所確認が失敗した場合は審査を再開しない。", "記録BI-2で確認した。", "再確認の担当を割り当てる。")),
    _doc("st-fin-03", "Cinder 履歴", "cinder", _body("履歴", "Cinderの旧運用を保存します。", "2026年9月までは日次集計だった。", "10月から週次集計に変更され、旧方針は現行判断に使わない。", "記録CI-9に変更日がある。", "旧記録を保管する。"), status="historical"),
    _doc("st-fin-04", "Delta 承認案", "delta", _body("承認案", "Deltaの変更案を管理します。", "新しい上限値は提案中で、承認済みではない。", "監査と利用者通知が終わるまで適用しない。", "提案書DE-4に未承認とある。", "レビュー結果を追記する。")),
    _doc("st-fin-05", "Ember 在庫", "ember", _body("在庫", "Emberの資材在庫を管理します。", "銀ラベルは8個、金ラベルは3個である。", "金ラベルは責任者の確認後だけ払い出す。", "棚卸しEM-8で確認した。", "次回棚卸しを予約する。")),
    _doc("st-fin-06", "Fern 分類", "fern", _body("分類", "Fernの受付分類を定義します。", "技術、請求、契約の3分類を使う。", "複数該当時は契約を優先し、理由を記録する。", "分類表FE-3にある。", "監査欄を更新する。")),
    _doc("st-fin-07", "Glint 共有範囲", "glint", _body("共有範囲", "Glint資料のアクセス範囲です。", "共有フォルダはプロジェクトメンバーが閲覧できる。", "個人メモは所有者以外へ転送しない。", "権限記録GL-7にある。", "公開版を作る場合は所有者が確認する。")),
    _doc("st-fin-08", "Helios 段階導入", "helios", _body("段階導入", "Heliosの段階導入条件です。", "10%を20分観測し、失敗率が2%未満なら50%へ進める。", "課金変更は10%から拡大せず、財務承認を待つ。", "観測表HE-5に閾値がある。", "ロールバックを演習する。")),
    _doc("st-fin-09", "Indigo 証跡", "indigo", _body("証跡", "Indigoの作業完了証跡を確認します。", "承認IDIN-Aと実施IDIN-Lが両方あれば完了とする。", "一方だけなら完了扱いにせず不足を照会する。", "台帳IN-4が関連付けている。", "不足資料を担当へ依頼する。")),
    _doc("st-fin-10", "Juniper 照会", "juniper", _body("照会", "Juniperの受付記録を検索します。", "指定された受付番号の処理結果は現資料に記録されていない。", "推測で完了とせず受付番号を再確認する。", "検索票JU-0は該当なしである。", "番号を取得して再検索する。")),
    _doc("st-fin-11", "Koala 一覧", "koala", _body("一覧", "Koalaの現行確認項目を列挙します。", "氏名、契約ID、連絡先、同意の4項目を確認する。", "同意がない場合は処理を進めない。", "表KO-4に4項目がある。", "項目変更はレビューする。")),
    _doc("st-fin-12", "Lagoon 移行", "lagoon", _body("移行", "Lagoonの移行条件を整理します。", "バックアップ、件数照合、復元確認がすべて成功したら移行する。", "機密データを含む場合は鍵の確認を加える。", "記録LA-6に結果がある。", "復元ログを保管する。")),
])

CASE_DATA = [
    ("dev-01", "current_policy", "orion", "current", ["st-cur-01"], ["平日昼間の一次通知は10分以内に担当へ転送する。"], ["10分以内", "一次通知"], ["電話連絡を開始する"], True, ["平日昼間の一次通知は何分以内に担当へ転送しますか。", "Orionの昼間の一次通知について、転送期限を教えてください。", "通常時間帯の一次通知の目標時間は何分ですか。"]),
    ("dev-02", "conditional_exception", "orion", "current", ["st-cur-01", "st-cur-02"], ["夜間は緊急度が高の場合だけ電話を使い、通常の更新は翌営業日にまとめる。", "顧客影響が確認できた障害は電話連絡を開始する。"], ["電話連絡を開始する", "15分ごと"], [], True, ["Orionで顧客影響の有無により通知をどう分けますか。", "影響が確認済みの場合と未確認の場合の連絡方法を比較してください。", "Orion障害通知の電話開始条件と、未確認時の更新間隔は何ですか。"]),
    ("dev-03", "cross_document", "beryl", "current", ["st-cur-07", "st-cur-08"], ["回帰テストが全件成功し、監査ログの保存を確認したら承認する。", "監査ログは30日保存し、承認者とテスト結果を紐付ける。"], ["監査ログの保存", "30日保存"], ["未完了なら承認してはならない"], True, ["Berylを承認する条件と、監査ログの保存期間を合わせて教えてください。", "回帰テストと監査証跡を使ったBerylのリリース条件は何ですか。", "Berylの承認に必要な検査とログ保存期間を資料横断で答えてください。"]),
    ("dev-04", "history", "eagle", "history", ["st-cur-16", "st-cur-15"], ["2026-08-02は月次レビューを採用していた。", "2026-10-18の会議では監視項目を週次で見直すと決めた。"], ["月次レビュー", "週次へ変更"], [], True, ["Eagleの8月時点のレビュー頻度と、その後の変更を説明してください。", "Eagleでは以前どの頻度でレビューし、いつ週次になりましたか。", "Eagleの過去方針から現行への変更履歴を教えてください。"]),
    ("dev-05", "proposal_not_approved", "cedar", "current", ["st-cur-11", "st-cur-12"], ["2027年の価格変更は提案段階で、承認済みではない。", "標準プランは月額4800円、年額48000円で提供する。"], ["提案段階", "月額4800円"], ["承認済み"], True, ["Cedarの価格変更案は承認済みですか。現行標準価格も答えてください。", "Cedarについて、提案中の価格改定と現在の標準プランを区別してください。", "Cedarの2027年案の状態と、いま適用する標準料金はいくらですか。"]),
    ("dev-06", "all_items", "harbor", "current", ["st-cur-21"], ["確認項目は本人確認、契約番号、連絡先、同意記録の4項目である。"], ["本人確認", "契約番号", "連絡先", "同意記録"], [], True, ["Harborの現行チェック項目をすべて列挙してください。", "Harborで確認する4項目を漏れなく挙げてください。", "Harborの受付チェックリスト全項目は何ですか。"]),
    ("dev-07", "unknown", "iris", "current", [], [], [], ["処理結果"], False, ["Irisの申請は処理済みですか。", "Irisで照会した申請の完了状態を確認してください。", "Irisの特定申請について、結果は記録されていますか。"]),
    ("dev-08", "privacy", "grove", "current", ["st-cur-19"], ["個人領域の資料は所有者本人だけが閲覧でき、別担当者へ転載しない。"], ["所有者本人だけ", "転載しない"], ["個人メモの内容"], True, ["Groveの個人領域を別担当者が閲覧できますか。", "Groveで私有資料を他の担当者へ共有してよいですか。", "Groveの個人領域に対するアクセス境界を説明してください。"]),
    ("final-01", "current_policy", "atlas", "current", ["st-fin-01"], ["本人確認、申請番号、承認者記録が揃えば開始する。"], ["本人確認", "申請番号", "承認者記録"], [], True, ["Atlasの申請を開始するための3条件は何ですか。", "Atlas申請の事前確認をすべて挙げてください。", "Atlasで受付を始める前に揃える記録は何ですか。"]),
    ("final-02", "conditional_exception", "birch", "current", ["st-fin-02"], ["海外申請は追加の住所確認を行う。", "住所確認が失敗した場合は審査を再開しない。"], ["追加の住所確認", "再開しない"], [], True, ["Birchの海外申請と住所確認失敗時の扱いは何ですか。", "Birchで海外案件に加える確認と、失敗時の判断を教えてください。", "Birchの審査例外ではどの条件で止めますか。"]),
    ("final-03", "history", "cinder", "history", ["st-fin-03"], ["2026年9月までは日次集計だった。", "10月から週次集計に変更され、旧方針は現行判断に使わない。"], ["日次集計", "週次集計", "10月"], [], True, ["Cinderの9月までの集計頻度と10月の変更を教えてください。", "Cinderは日次から何に変わりましたか。", "Cinderの履歴上の集計方針を時系列で説明してください。"]),
    ("final-04", "proposal_not_approved", "delta", "current", ["st-fin-04"], ["新しい上限値は提案中で、承認済みではない。", "監査と利用者通知が終わるまで適用しない。"], ["提案中", "適用しない"], ["承認済み"], True, ["Deltaの上限値案は承認済みですか。適用条件も答えてください。", "Deltaの変更案の状態と、実施を待つ条件を説明してください。", "Deltaの新上限は今すぐ使えますか。"]),
    ("final-05", "cross_document", "ember", "current", ["st-fin-05"], ["銀ラベルは8個、金ラベルは3個である。", "金ラベルは責任者の確認後だけ払い出す。"], ["8個", "3個", "責任者の確認後"], [], True, ["Emberのラベル別在庫数と金ラベルの払い出し条件を教えてください。", "Emberで銀と金は何個あり、金はいつ使えますか。", "Emberの棚卸し結果と払い出し規則を合わせて説明してください。"]),
    ("final-06", "all_items", "fern", "current", ["st-fin-06"], ["技術、請求、契約の3分類を使う。"], ["技術", "請求", "契約"], [], True, ["Fernの受付分類をすべて列挙してください。", "Fernで使う3つの分類は何ですか。", "Fernの問い合わせ分類一覧を省略せずに答えてください。"]),
    ("final-07", "privacy", "glint", "current", ["st-fin-07"], ["共有フォルダはプロジェクトメンバーが閲覧できる。"], ["プロジェクトメンバー"], ["個人メモ"], True, ["Glintの共有フォルダは誰が見られますか。", "Glintで共有資料を閲覧できる範囲を教えてください。", "Glintの公開領域のアクセス単位は何ですか。"]),
    ("final-08", "conditional_exception", "helios", "current", ["st-fin-08"], ["10%を20分観測し、失敗率が2%未満なら50%へ進める。", "課金変更は10%から拡大せず、財務承認を待つ。"], ["10%を20分", "2%未満", "50%へ"], [], True, ["Heliosの通常拡大条件と課金変更の例外を説明してください。", "Heliosはいつ50%へ進め、課金変更では何を待ちますか。", "Heliosの段階導入の閾値と制限を教えてください。"]),
    ("final-09", "cross_document", "indigo", "current", ["st-fin-09"], ["承認IDIN-Aと実施IDIN-Lが両方あれば完了とする。"], ["IN-A", "IN-L"], [], True, ["Indigoを完了とするために必要な二つのIDは何ですか。", "Indigoの承認と実施の証跡条件を説明してください。", "Indigoで片方の記録しかない場合、完了扱いできますか。"]),
    ("final-10", "unknown", "juniper", "current", [], [], [], ["処理結果"], False, ["Juniperの受付番号JU-999は完了していますか。", "Juniperで指定された受付の処理結果を確認してください。", "Juniperの受付状態は現資料から分かりますか。"]),
    ("final-11", "history", "cinder", "history", ["st-fin-03"], ["2026年9月までは日次集計だった。", "10月から週次集計に変更され、旧方針は現行判断に使わない。"], ["2026年9月", "日次集計", "週次集計"], [], True, ["Cinderの過去の集計頻度を確認してください。", "Cinderの日次運用から週次運用への変更を説明してください。", "Cinderで現行判断に使わない履歴方針は何でしたか。"]),
    ("final-12", "all_items", "koala", "current", ["st-fin-11"], ["氏名、契約ID、連絡先、同意の4項目を確認する。"], ["氏名", "契約ID", "連絡先", "同意"], [], True, ["Koalaの4つの確認項目を一覧にしてください。", "Koalaの受付チェックリストを全件示してください。", "Koalaで確認する項目を漏れなく教えてください。"]),
]


def _case(row):
    id_, category, project, mode, required, quotes, fragments, forbidden, answerable, variants = row
    return {"id": id_, "category": category, "project": project, "mode": mode,
            "variants": variants, "required_source_ids": required,
            "required_quotes": quotes, "expected_answer_fragments": fragments,
            "forbidden_answer_fragments": forbidden, "answerable": answerable}


def _distractor(i, seed):
    rng = random.Random(seed * 100003 + i)
    project = ["lumen", "maple", "nova", "quartz", "raven", "solace", "terra"][i % 7]
    topics = ["監視メモ", "設備点検", "契約照会", "研修記録", "配送計画", "色校正", "会計整理"]
    topic = topics[(i + rng.randrange(len(topics))) % len(topics)]
    details = [
        "担当者は前回の記録を確認し、次回の確認日を台帳へ記入する。",
        "例外が見つかった場合は処理を止め、責任者へ事実と時刻を共有する。",
        "この資料は対象チームの作業メモであり、他プロジェクトの判断には適用しない。",
        "数値は点検時点の観測値で、別日や別地域の値を合算しない。",
    ]
    body = _body(topic, f"{project}の{topic}に関する作業記録です。", details[i % len(details)],
                 details[(i + 1) % len(details)], f"記録番号{project[:2].upper()}-{i:04d}で確認した。",
                 "次回の担当者は更新日と対象範囲を確認する。")
    status = "historical" if i % 11 == 0 else "current"
    scope = "private" if i % 17 == 0 else "shared"
    owner = "fixture-owner" if scope == "private" else "team"
    return _doc(f"st-noise-{i:05d}", f"{project} {topic} {i:04d}", project, body,
                status=status, scope=scope, owner=owner)


def generate(size=100, seed=20261103, order_seed=None):
    if type(size) is not int or size < len(CORE):
        raise ValueError(f"size must be an integer >= {len(CORE)}")
    docs = list(CORE) + [_distractor(i, seed) for i in range(size - len(CORE))]
    if order_seed is not None:
        random.Random(order_seed).shuffle(docs)
    return docs


def cases():
    return [_case(row) for row in CASE_DATA]


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def freeze():
    corpus = generate(100, seed=20261103)
    dev = [_case(row) for row in CASE_DATA[:8]]
    final = [_case(row) for row in CASE_DATA[8:]]
    _write_json(ROOT / "corpus.json", corpus)
    _write_json(ROOT / "dev.json", dev)
    _write_json(ROOT / "final.json", final)
    hashes = {}
    for name in ("author_fixture.py", "corpus.json", "dev.json", "final.json"):
        hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    freeze_data = {
        "schema": "phase2-stability-freeze-v1",
        "authored_diagnostic": True,
        "not_an_independent_benchmark": True,
        "generator": {"sizes": [100, 1000, 10000], "seed": 20261103, "order_seeds": [1, 2]},
        "counts": {"corpus_100": len(corpus), "dev": len(dev), "final": len(final),
                   "variants": sum(len(x["variants"]) for x in dev + final)},
        "hashes": hashes,
    }
    _write_json(ROOT / "FREEZE.json", freeze_data)


if __name__ == "__main__":
    freeze()
