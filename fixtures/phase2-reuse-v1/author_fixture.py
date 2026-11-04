"""Source-first synthetic reuse diagnostic. No questions or gold are embedded."""
from __future__ import annotations
import hashlib, json, random
from pathlib import Path
ROOT=Path(__file__).parent

def source(id_, title, topic_id, project, version, body, *, scope='shared', owner='team', status='current'):
    return {'id':id_,'title':title,'body':body,'scope':scope,'owner':owner,
            'properties':{'topic_id':topic_id,'project':project,'version':version,'status':status}}

def body(title, decision, condition, exception, evidence, update):
    return (f'# {title}\n\n## 決定記録\n### 決定\n{decision}\n\n### 適用条件\n{condition}\n\n'
            f'### 例外\n{exception}\n\n### 根拠\n{evidence}\n\n### 更新時の扱い\n{update}\n\n'
            '## 背景\nこの記録は確認済みの判断を再利用するため、対象、期間、責任者、参照時点を分けて保存する。'
            '同名の古い版や提案版を現行の決定と混ぜず、条件と例外を省略しない。レビューでは本文の範囲を確認し、'
            '未確認の内容を推測で補わず、次の担当者が同じ範囲を再確認できるよう更新理由と担当を残す。\n')

CORE=[
 source('rv-sh-01','発送ルール 決定','発送ルール','reuse-dev','v3',body('発送ルール','通常便は受付日の翌営業日に発送する。','平日15時までの確定注文に適用する。','冷蔵品は保冷便へ切り替え、土日確定分は月曜扱いとする。','レビュー票SH-3と出荷ログで確認した。','締切時刻を変更する場合は新しい版を作り旧版を履歴化する。')),
 source('rv-sh-02','発送ルール 根拠','発送ルール','reuse-dev','v3',body('発送ルール根拠','翌営業日発送の判断は在庫照合完了を前提にする。','在庫照合番号が付いた注文だけ対象とする。','照合不一致は発送せず担当へ戻す。','照合票SH-Iと倉庫記録で確認した。','照合項目を増やす場合は根拠範囲を更新する。')),
 source('rv-sh-03','返品窓口','返品窓口','reuse-dev','v2',body('返品窓口','未使用品は到着後14日以内に受付する。','注文番号と未使用状態を確認する。','開封済みは通常受付せず初期不良窓口へ案内する。','返品票SH-Rで確認した。','期間変更は承認記録を追記する。')),
 source('rv-sh-04','監査頻度','監査頻度','reuse-dev','v1',body('監査頻度','月次監査を毎月第1営業日に実施する。','対象月の全ログが揃った場合に開始する。','重大障害は月次を待たず臨時監査とする。','監査記録SH-Aで確認した。','頻度変更は次版へ分離する。')),
 source('rv-sh-05','価格提案','価格提案','reuse-dev','v1',body('価格提案','追加料金案は提案中で、現行価格を変更しない。','法務と顧客通知の承認後に再評価する。','承認前の適用は禁止する。','提案票SH-Pに未承認とある。','承認状態を更新してから版を変える。')),
 source('rv-sh-06','個人メモ','個人メモ','reuse-dev','v1',body('個人メモ','所有者だけが個人メモを閲覧できる。','所有者本人の作業に限る。','非所有者には内容を回答せず共有版の所在だけ案内する。','権限監査SH-PRで確認した。','公開版は所有者が別途作成する。'),scope='private',owner='dev-owner'),
 source('rv-sh-07','未レビュー手順','未レビュー手順','reuse-dev','draft',body('未レビュー手順','この手順はレビュー前で、運用決定として扱わない。','レビュー承認と根拠確認が必要である。','承認前に実施しない。','草稿台帳SH-Dに未レビューとある。','レビュー後に版を確定する。'),status='proposal'),
 source('rv-sh-08','旧発送方針','旧発送方針','reuse-dev','v1',body('旧発送方針','旧版では当日発送を採用していた。','2026年6月までの履歴に限る。','現行の翌営業日発送には適用しない。','履歴票SH-OLDで確認した。','履歴として保存し現行へ混ぜない。'),status='historical'),
 source('rv-sh-09','受入検査 判定','受入検査','reuse-dev','v1',body('受入検査','検査合格後に受入番号を発行する。','全項目の測定値が記録されていること。','測定漏れは合格にせず再検査へ戻す。','検査票SH-Qで確認した。','測定項目を変更する場合は版を更新する。')),
 source('rv-sh-10','受入検査 記録','受入検査','reuse-dev','v1',body('受入検査記録','受入番号は検査票と納品記録の両方へ記載する。','納品記録の照合が完了している場合に適用する。','番号不一致は受入を保留し担当へ戻す。','照合票SH-Q2で確認した。','照合項目を追加する場合はレビューする。')),
 source('rv-fi-01','承認門','承認門','reuse-final','v2',body('承認門','統合試験成功と監査ログ保存後に承認する。','全件成功と保存確認が必要である。','試験未完了なら承認しない。','承認票FI-1で確認した。','試験項目変更は新版にする。')),
 source('rv-fi-02','段階投入','段階投入','reuse-final','v2',body('段階投入','10%を20分観測し失敗率2%未満で50%へ進める。','通常機能に適用する。','課金変更は10%から拡大せず財務承認を待つ。','観測票FI-2で確認した。','閾値変更は再承認する。')),
 source('rv-fi-03','在庫色','在庫色','reuse-final','v1',body('在庫色','銀箱は8個、金箱は3個である。','棚卸日当日の倉庫在庫に適用する。','金箱は責任者署名後だけ払い出す。','棚卸票FI-3で確認した。','数量訂正は差分理由を残す。')),
 source('rv-fi-04','問合せ分類','問合せ分類','reuse-final','v1',body('問合せ分類','技術、契約、請求の3分類を使う。','最初の受付時に1分類を選ぶ。','複数該当時は契約を優先する。','分類表FI-4で確認した。','分類追加はレビューする。')),
 source('rv-fi-05','共有資料','共有資料','reuse-final','v1',body('共有資料','登録メンバーが共有資料を閲覧できる。','プロジェクト登録が有効であること。','私有メモは所有者以外へ共有しない。','権限票FI-5で確認した。','メンバー変更は監査する。')),
 source('rv-fi-06','受付一覧','受付一覧','reuse-final','v1',body('受付一覧','氏名、契約ID、連絡先、同意の4項目を確認する。','同意欄が埋まっている場合に進める。','同意なしは保留する。','一覧票FI-6で確認した。','項目追加は版を更新する。')),
 source('rv-fi-07','不明受付','不明受付','reuse-final','v1',body('不明受付','照会された受付結果は現資料に記録されていない。','受付番号の再確認が必要である。','推測で完了扱いしない。','検索票FI-7は該当なしである。','番号取得後に再検索する。')),
 source('rv-fi-08','地域通知','地域通知','reuse-final','v1',body('地域通知','北部の低緊急度通知は現地時間のメールで送る。','北部地域の低緊急度に限る。','南部には適用せず地域台帳を確認する。','地域票FI-8で確認した。','境界変更は承認する。')),
 source('rv-fi-09','証跡完了','証跡完了','reuse-final','v1',body('証跡完了','承認IDと実施IDの両方が揃えば完了とする。','両IDが同じ案件に紐づくこと。','片方だけなら完了にしない。','台帳FI-9で確認した。','不足資料を照会する。')),
 source('rv-fi-10','保管期限','保管期限','reuse-final','v1',body('保管期限','試験資料を施錠棚へ90日保管する。','通常資料に適用する。','機密資料は別鍵を使い延長には責任者承認が必要。','保管票FI-10で確認した。','廃棄前に承認を確認する。')),
 source('rv-fi-11','会議頻度','会議頻度','reuse-final','v1',body('会議頻度','監視会議を毎週金曜に行う。','通常週の報告が揃った場合に開催する。','重大障害は臨時会議を開き週次を待たない。','議事録FI-11で確認した。','開催曜日変更は新版にする。')),
 source('rv-fi-12','契約更新','契約更新','reuse-final','v1',body('契約更新','更新案内は満了日の30日前に送る。','連絡先が有効な契約に適用する。','連絡先不明は案内を送らず担当へ戻す。','契約票FI-12で確認した。','連絡先訂正を先に記録する。')),
 source('rv-fi-13','私有承認メモ','私有承認メモ','reuse-final','v1',body('私有承認メモ','所有者だけが承認メモを閲覧できる。','所有者本人の確認に限る。','非所有者には内容を回答せず共有版の所在だけ案内する。','権限票FI-13で確認した。','公開版は所有者が作成する。'),scope='private',owner='final-owner'),
 source('rv-fi-14','引渡判定','引渡判定','reuse-final','v1',body('引渡判定','検品合格後に引渡番号を発行する。','検品票に全測定値があること。','測定漏れは引渡を保留する。','検品票FI-14で確認した。','測定項目変更は新版にする。')),
 source('rv-fi-15','引渡記録','引渡判定','reuse-final','v1',body('引渡記録','引渡番号を受領記録へ記載する。','受領者の署名がある場合に確定する。','番号不一致は担当へ戻す。','受領票FI-15で確認した。','署名欄変更はレビューする。')),
]

def _noise(i,seed):
    r=random.Random(seed*99991+i); projects=['reuse-dev','reuse-final'][i%2]; topic=f'補助作業-{i:04d}'
    return source(f'rv-noise-{i:05d}',topic,topic,projects,'n1',body(topic,'台帳を更新する。','対象範囲を確認する。','別案件へ適用しない。',f'補助票-{r.randrange(10000)}で確認した。','次回担当へ引き継ぐ。'))

def generate(size=100,seed=20261103,order_seed=None):
    if type(size) is not int or size<len(CORE): raise ValueError(f'size must be >= {len(CORE)}')
    docs=list(CORE)+[_noise(i,seed) for i in range(size-len(CORE))]
    if order_seed is not None: random.Random(order_seed).shuffle(docs)
    return docs

def review_manifest(docs):
    items=[]
    for d in docs:
        approved=d['properties']['status']!='proposal'
        start=d['body'].find('## 決定記録'); end=d['body'].find('## 背景')
        items.append({'source_id':d['id'],'source_version':d['properties']['version'],
                      'body_sha256':hashlib.sha256(d['body'].encode()).hexdigest(),
                      'start':start,'end':end,'topic_id':d['properties']['topic_id'],
                      'scope':d['scope'],'reviewed':approved,'review_state':'synthetic_reviewed' if approved else 'needs_review'})
    return {'schema':'phase2-reuse-review-manifest-v1','synthetic_review_consent':True,
            'review_scope':'record content may be reviewed across current, proposal, historical, and private scopes; adoption is separate from review',
            'items':items}

if __name__=='__main__':
    docs=generate(); (ROOT/'corpus.json').write_text(json.dumps(docs,ensure_ascii=False,indent=2)+'\n')
    manifest=review_manifest(docs); (ROOT/'review_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    hashes={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ('corpus.json','review_manifest.json')}
    (ROOT/'stage1_hashes.json').write_text(json.dumps({'schema':'phase2-reuse-stage1-hashes-v1','hashes':hashes},indent=2)+'\n')
