"""Freeze v3: 100 records exactly, varied documents, explicit growth families."""
from __future__ import annotations
import hashlib, importlib.util, json, random
from pathlib import Path
ROOT=Path(__file__).parent; SEED=20261103; PROJECTS=["atlas","birch","cobalt","delta","ember","fjord","grove","harbor"]
def _load():
 p=ROOT.parent/"phase2-token-growth-v2"/"author_fixture.py"; s=importlib.util.spec_from_file_location("v2",p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
V2=_load()
def _digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def base_corpus():
 old=V2.base_corpus(); keep=old[:19]+[d for d in old if d["id"].startswith("src-final-")]
 assert len(keep)==37
 docs=[dict(d) for d in keep]
 for i in (2, 8, 20):
  docs[i]["body"] += "\n" + "\n".join(f"## 独立観測 {n:03d}\n{docs[i]['project']}の観測 {n:03d} は、適用範囲、確認者、期限、失敗時の復旧条件を別々に記録する。" for n in range(1, 130))
 return docs
def questions(): return V2.questions()
def _new(project,i,body_suffix=""):
 return {"id":f"src-scale-{i:05d}","title":f"{project.title()} scale note {i:05d}","project":project,"status":"current","scope":"shared","owner":"","updated_at":"2026-10-30","body":V2._varied_body(project,i,body_suffix)}
def generate(size,scenario="mixed",seed=SEED,length_multiplier=1):
 if size<37 or scenario not in {"mixed","unrelated","long"} or length_multiplier<1: raise ValueError("invalid args")
 docs=base_corpus(); rng=random.Random(seed+size+{"mixed":17,"unrelated":31,"long":53}[scenario])
 while len(docs)<size:
  i=len(docs); project=("unrelated-"+str(rng.randrange(20))) if scenario=="unrelated" else PROJECTS[rng.randrange(len(PROJECTS))]; docs.append(_new(project,i))
 if scenario=="mixed" and size>=100:
  filler=list(range(37,size)); dup=filler[:15]; hist=filler[15:30]; cond=filler[30:60]
  for j in dup: docs[j]["body"]=docs[3]["body"]
  for j in hist: docs[j]["status"]="historical"; docs[j]["body"]=docs[3]["body"].replace("2026","2025")
  for j in cond: docs[j]["body"] += "\n\n## 適用条件\n実行地域は東日本、版条件は候補B。対象が異なる場合はこの資料を根拠にしない。"
 if scenario=="long" and length_multiplier>1:
  for i in range(min(12,len(docs))):
   for n in range(length_multiplier-1): docs[i]["body"] += f"\n\n## 長文補足 {n+1:03d}\n{docs[i]['project']}の運用観察{n+1:03d}。リスク、承認、失敗時の復旧、期限、参照版を独立した観測として記録し、前の観測を上書きしない。"
 return docs
def generation_metadata(size,scenario="mixed",seed=SEED,length_multiplier=1):
 d=generate(size,scenario,seed,length_multiplier); b=[x["body"] for x in d]; return {"size":size,"scenario":scenario,"seed":seed,"length_multiplier":length_multiplier,"counts":{"sources":len(d),"historical":sum(x["status"]=="historical" for x in d),"exact_duplicate_body_groups":sum(b.count(x)>1 for x in set(b)),"condition_variant_records":sum("## 適用条件" in x["body"] for x in d)},"body_chars":sum(map(len,b))}
def main():
 ROOT.mkdir(parents=True,exist_ok=True); docs=generate(100); dev,final=questions();
 (ROOT/"corpus.json").write_text(json.dumps(docs,ensure_ascii=False,indent=2)+"\n"); (ROOT/"dev.json").write_text(json.dumps(dev,ensure_ascii=False,indent=2)+"\n"); (ROOT/"final.json").write_text(json.dumps(final,ensure_ascii=False,indent=2)+"\n")
 b=[x["body"] for x in docs]; meta={"schema":"phase2-token-growth-freeze-v3","seed":SEED,"authored_diagnostic":True,"independent_benchmark":False,"corpus_count":100,"dev_count":len(dev),"final_count":len(final),"dev_projects":sorted({x["project"] for x in dev}),"final_projects":sorted({x["project"] for x in final}),"min_body_chars":min(map(len,b)),"long_body_count_ge_6000":sum(len(x)>=6000 for x in b),"generation_metadata":{"mixed100":generation_metadata(100),"mixed1000":generation_metadata(1000),"mixed10000":generation_metadata(10000),"unrelated100":generation_metadata(100,"unrelated")},"files":{n:_digest(ROOT/n) for n in ("author_fixture.py","corpus.json","dev.json","final.json")}}
 (ROOT/"FREEZE.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n")
if __name__=="__main__": main()
