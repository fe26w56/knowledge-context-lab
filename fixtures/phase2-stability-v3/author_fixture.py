"""Synthetic source-only generator for stability-v2; no questions or gold live here."""
from __future__ import annotations
import random
from pathlib import Path

ROOT = Path(__file__).parent
DATE = "2026-11-03"

def source(id_, title, project, body, *, status="current", scope="shared", owner="team"):
    return {"id": id_, "title": title, "project": project, "status": status,
            "scope": scope, "owner": owner, "updated_at": DATE, "body": body}

def document(project, title, overview, decision, conditions, evidence, handoff, *, status="current", scope="shared", owner="team"):
    body = (f"# {title}\n\n## {overview}\n"
            f"### 決定\n{decision}\n\n### 適用条件\n{conditions}\n\n"
            f"### 確認材料\n{evidence}\n\n### 引き継ぎ\n{handoff}\n\n"
            "## 運用背景\nこの記録は判断の対象、適用期間、確認担当を分けて残すためのものです。"
            "別地域や別版の記録を混ぜず、更新時には変更理由と確認時点を追記します。"
            "未確認の事項は推測で補わず、次の担当者が再確認できるよう不足資料を明示します。"
            "レビュー時には決定だけを抜き出さず、適用条件、例外、確認材料、引き継ぎの順に読み、対象範囲が一致しているかを確認します。"
            "同じ名称の記録が複数ある場合は状態と更新日を照合し、古い記録は変更の経緯として残しますが現行の判断へ自動的に混ぜません。"
            "数値や期限を引用する場合は、単位、適用地域、確認時点を併記し、別の条件の数字を合算しないようにします。"
            "権限の異なる資料を参照するときは、閲覧できない内容を推測せず、共有された資料だけで答えられる範囲と不足を明示します。"
            "更新後は変更前の記録を削除せず、確認者と確認日を残して次のレビューで追跡できるようにします。\n")
            
    return source(f"sv2-{project}-core", title, project, body, status=status, scope=scope, owner=owner)

CORE = [
 document("amber","Amber 入館手順","入館受付","本人確認後に受付票へ時刻を記入する。","訪問者が未登録なら担当者の同伴が必要。夜間は受付を停止する。","入館台帳AM-17に時刻と担当者がある。","次回は未登録者の同伴記録を確認する。"),
 document("birch","Birch 配送条件","配送判断","冷蔵品は4時間以内に受け渡す。","気温が25度を超える日は保冷箱を追加し、破損品は配送しない。","配送票BI-22に温度記録がある。","温度計の校正日を確認する。"),
 document("cobalt","Cobalt 監査履歴","集計履歴","2026年7月までは月次、8月から隔週に変更した。","旧月次記録は変更経緯の確認にのみ使い、現行集計には混ぜない。","監査票CO-08に変更日がある。","次回の隔週結果を保存する。",status="historical"),
 document("dune","Dune 価格案","価格提案","追加席の料金は検討中で、適用は未承認である。","法務確認と顧客通知が完了するまで現行価格を変更しない。","提案書DU-5に未承認と記載されている。","法務回答を提案書へ追記する。"),
 document("elm","Elm 在庫記録","在庫一覧","白箱は9個、黒箱は4個である。","黒箱は責任者の署名後だけ払い出す。破損品は色に関係なく隔離する。","棚卸票EL-4に数量と状態がある。","隔離棚を次回点検する。"),
 document("frost","Frost 問合せ分類","分類規則","操作、契約、請求の3分類を使う。","複数該当時は契約を優先し、理由を記録する。","分類表FR-3に優先順位がある。","理由欄の監査を行う。"),
 document("grove2","Grove2 共有範囲","閲覧規則","共有資料は登録メンバーが閲覧できる。","個人メモは所有者のみが閲覧し、他人へ転載しない。","権限記録GR2-6に監査結果がある。","公開版が必要なら所有者が作成する。"),
 document("helium","Helium 段階投入","導入手順","15%を25分観測し、失敗率が3%未満なら40%へ進める。","請求変更は15%から広げず、財務担当の承認を待つ。","観測票HE-9に閾値と時刻がある。","ロールバック演習を実施する。"),
 document("indigo2","Indigo2 完了証跡","完了判定","承認番号IX-Aと実施番号IX-Lの両方が揃えば完了とする。","片方だけなら完了にせず、不足番号を照会する。","台帳IX-2が二つの番号を関連付けている。","不足資料を担当へ依頼する。"),
 document("jade2","Jade2 受付照会","受付記録","照会された受付の結果は現資料に記録されていない。","推測で完了とせず、受付番号を再確認する。","検索票JA2-0は該当なしである。","番号取得後に再検索する。"),
 document("kestrel","Kestrel 項目表","確認一覧","氏名、注文ID、連絡先、同意欄の4項目を確認する。","同意欄が空なら処理を進めない。","表KE-4に4項目が列挙されている。","項目変更はレビューする。"),
 document("lumen2","Lumen2 移行","移行条件","バックアップ、件数照合、復元確認が成功したら移行する。","機密データなら鍵の確認を追加し、復元失敗時は停止する。","移行票LU2-7に結果がある。","復元ログを保管する。"),
 document("moss","Moss 通知","通知判断","昼間の一次通知は12分以内に担当へ転送する。","夜間は重大度が高い場合だけ電話し、影響未確認なら20分ごとに更新する。","通知票MO-12に時刻がある。","夜間訓練で例外を確認する。"),
 document("nova2","Nova2 リリース","承認条件","統合試験成功と監査ログ保存を確認して承認する。","個人情報変更は追加レビューが必須で、試験未完了なら承認しない。","台帳NO2-3に試験結果がある。","追加レビュー担当を決める。"),
 document("opal","Opal 会議履歴","会議記録","2026年9月の会議で監視を月次から週次へ変えた。","緊急変更は週次を待たず臨時レビューする。","議事録OP-9に参加者と決定がある。","次回に実績を確認する。"),
 document("pearl","Pearl 連絡先","連絡規則","一次担当は窓口チーム、二次担当は品質チームとする。","休日は当番表の代理を選ぶ。","台帳PE-2が連絡先を更新している。","月初に当番表を確認する。"),
 document("quill","Quill 私有記録","私有領域","管理者の作業メモは所有者の作業用に保管する。","所有者以外へ内容を回答せず、共有版の所在だけ案内する。","監査票QU-8に拒否記録がある。","共有化は所有者が判断する。",scope="private",owner="owner-q"),
 document("river","River 旧運用","旧手順","2026年5月までは全件をメール通知していた。","6月の現行手順で置換され、旧手順は履歴としてのみ参照する。","旧票RI-5に変更経緯がある。","現行手順と混同しない。",status="historical"),
 document("sable","Sable 証跡横断","横断確認","承認記録SA-Aと実行ログSA-Lが揃った場合だけ完了とする。","一方だけなら不足資料を明示する。","台帳SA-1が二つを関連付ける。","担当へ不足を照会する。"),
 document("tulip","Tulip 地域条件","地域運用","北部地域の低緊急度通知は現地時間のメールで送る。","南部地域の判断には適用せず、地域台帳を確認する。","表TU-Nに地域条件がある。","境界変更は承認を取る。"),
 document("umber","Umber 返品","返品条件","未開封品は購入後14日以内なら返品を受け付ける。","開封済みは対象外で、初期不良は期間外でも調査する。","返品票UM-14に状態と日付がある。","初期不良の調査番号を記録する。"),
 document("violet","Violet 保管","保管規則","試験資料は施錠棚へ90日保管する。","機密資料は別鍵を使い、保管期限を延長する場合は責任者が承認する。","保管台帳VI-90に期限がある。","期限前に廃棄承認を確認する。"),
]

def _noise(i, seed):
    import copy
    r = random.Random(seed * 100003 + i)
    source_projects = sorted({s["project"] for s in CORE})
    project = source_projects[i % len(source_projects)] if i % 5 else f"unrelated-{i % 17}"
    if i % 11 == 0:
        original = CORE[(i // 11) % len(CORE)]
        item = copy.deepcopy(original)
        item["id"] = f"duplicate-{i:05d}"
        return item
    tasks = ["会議室の点検", "研修会場の予約", "配送車の清掃", "試験装置の校正", "照明の交換", "棚ラベルの更新", "来客用備品の貸出", "清掃記録の確認", "机の配置変更", "演習環境の停止", "プリンターの整備", "倉庫通路の確認"]
    task = r.choice(tasks)
    site = r.choice(["東棟", "西棟", "試験室", "倉庫", "別館", "研修棟"])
    days = r.randint(1, 28)
    number = r.randint(100, 999)
    body = (f"# {project} {task}の記録 {number}\n\n"
            f"## {site}での{task}\n### 手順\n毎月{days}日に担当者が対象設備を確認し、記録番号{number}へ結果を残す。\n\n"
            f"### 条件\nこの記録は{site}の{task}だけに適用する。他の受付、料金、配送判断や全体方針の変更を承認するものではない。\n\n"
            f"### 例外\n担当者が不在なら実施を保留し、代理担当の確認を待つ。\n\n"
            f"## 記録の照合\n確認時刻、設備番号、未完了項目を記録する。次回確認日は翌月{days}日。根拠は作業票{number}である。\n")
    return source(f"noise-{i:05d}", f"{project} {site} {task}", project, body,
                  status="historical" if i % 7 == 0 else "current",
                  scope="private" if i % 13 == 0 else "shared", owner="noise-owner")

def generate(size=100, seed=20261103, order_seed=None):
    if type(size) is not int or size < len(CORE): raise ValueError(f"size must be >= {len(CORE)}")
    docs=list(CORE)+[_noise(i,seed) for i in range(size-len(CORE))]
    if order_seed is not None: random.Random(order_seed).shuffle(docs)
    return docs

if __name__ == "__main__":
    import json
    (ROOT/"corpus.json").write_text(json.dumps(generate(),ensure_ascii=False,indent=2)+"\n")
