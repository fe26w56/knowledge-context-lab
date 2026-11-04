"""Final corrected token-growth fixture: prefix-stable, family-balanced, varied sources."""
from __future__ import annotations
import copy, hashlib, importlib.util, json, random
from pathlib import Path
ROOT=Path(__file__).parent; SEED=20261103
spec=importlib.util.spec_from_file_location("v3",ROOT.parent/"phase2-token-growth-v3"/"author_fixture.py"); V3=importlib.util.module_from_spec(spec); spec.loader.exec_module(V3)
ALL_PROJECTS=["atlas","birch","cobalt","delta","ember","fjord","grove","harbor"]+[x[0] for x in V3.V2.FINAL_TOPICS]

def _digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def base_corpus(): return copy.deepcopy(V3.base_corpus())
def questions(): return V3.questions()
def _scale(project,i): return {"id":f"src-scale-{i:05d}","title":f"{project.title()} scale note {i:05d}","project":project,"status":"current","scope":"shared","owner":"","updated_at":"2026-10-30","body":V3.V2._varied_body(project,i)}
def _family(record, family, ordinal, docs):
 if family=="historical":
  record["status"]="historical"; record["body"] += "\n\n## 旧版条件\nこの版は2025年の旧運用で、現在の条件へ自動適用してはいけない。"
 elif family=="duplicate":
  src=copy.deepcopy(docs[ordinal % 37]); src["id"]=record["id"]; src["title"]=record["title"]; return src
 elif family=="condition":
  record["body"] += "\n\n## 適用条件\n実行地域は西日本、利用ケースは監査用。東日本の通常運用へこの条件を持ち込まない。"
 return record
def generate(size,scenario="mixed",seed=SEED,length_multiplier=1):
 if size<37 or scenario not in {"mixed","unrelated","long"} or length_multiplier<1: raise ValueError("invalid arguments")
 docs=base_corpus(); rng=random.Random(seed+{"mixed":17,"unrelated":31,"long":53}[scenario])
 while len(docs)<size:
  ordinal=len(docs)-37; project=("unrelated-"+str(ordinal%17)) if scenario=="unrelated" else ALL_PROJECTS[ordinal%len(ALL_PROJECTS)]
  record=_scale(project,len(docs)); family=("historical" if ordinal%100<15 else "duplicate" if ordinal%100<30 else "condition" if ordinal%100<60 else "other")
  if scenario=="mixed": record=_family(record,family,ordinal,docs)
  docs.append(record)
 if scenario=="long" and length_multiplier>1:
  for i in range(37):
   for n in range((length_multiplier-1)*30):
    docs[i]["body"] += f"\n\n## 長文補足 {n+1:03d}\n{docs[i]['project']}の独立観測 {n+1:03d}。適用範囲、確認者、期限、失敗時の復旧条件、根拠版を別々に記録し、既存の決定文を変更しない。"
 return docs
def generation_metadata(size,scenario="mixed",seed=SEED,length_multiplier=1):
 d=generate(size,scenario,seed,length_multiplier); added=d[37:]; base_bodies={x["body"] for x in d[:37]}; b=[x["body"] for x in d]; return {"size":size,"scenario":scenario,"seed":seed,"length_multiplier":length_multiplier,"counts":{"sources":len(d),"added":len(added),"historical":sum(x["status"]=="historical" for x in added),"exact_duplicate_records":sum(x["body"] in base_bodies for x in added),"condition_variant_records":sum("## 適用条件" in x["body"] for x in added)},"body_chars":sum(map(len,b))}
def main():
 ROOT.mkdir(parents=True,exist_ok=True); docs=generate(100); dev,final=questions();
 (ROOT/"corpus.json").write_text(json.dumps(docs,ensure_ascii=False,indent=2)+"\n"); (ROOT/"dev.json").write_text(json.dumps(dev,ensure_ascii=False,indent=2)+"\n"); (ROOT/"final.json").write_text(json.dumps(final,ensure_ascii=False,indent=2)+"\n")
 b=[x["body"] for x in docs]; meta={"schema":"phase2-token-growth-freeze-v4","seed":SEED,"authored_diagnostic":True,"independent_benchmark":False,"corpus_count":100,"dev_count":len(dev),"final_count":len(final),"dev_projects":sorted({x["project"] for x in dev}),"final_projects":sorted({x["project"] for x in final}),"min_body_chars":min(map(len,b)),"long_body_count_ge_6000":sum(len(x)>=6000 for x in b),"generation_metadata":{"mixed100":generation_metadata(100),"mixed1000":generation_metadata(1000),"mixed10000":generation_metadata(10000),"unrelated100":generation_metadata(100,"unrelated"),"long100x1":generation_metadata(100,"long",length_multiplier=1),"long100x4":generation_metadata(100,"long",length_multiplier=4),"long100x16":generation_metadata(100,"long",length_multiplier=16)},"files":{n:_digest(ROOT/n) for n in ("author_fixture.py","corpus.json","dev.json","final.json")}}
 (ROOT/"FREEZE.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n")
if __name__=="__main__": main()
