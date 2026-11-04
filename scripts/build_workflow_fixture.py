"""Author a controlled, synthetic reuse/update experiment before implementation.

This is a factorial diagnostic, not 16 independent real-world problem families.
No retrieval implementation is imported. Gold is a separate offline artifact.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import random


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def make_episode(split, index, length, reuse, update):
    rng = random.Random((41000 if split == "dev" else 71000) + index)
    eid = f"{split}-{index:02}"
    actors = [f"operator-{i:02}" for i in range(1, 17)]
    sources = []
    source_sets = []
    source_info = {}
    names = (["Alder", "Basin", "Cedar", "Dune", "Elm", "Fern", "Grove", "Heath", "Iris", "Juniper", "Kelp", "Larch", "Moor", "Nectar", "Olive", "Pine"] if split == "dev" else
             ["Quartz", "Reed", "Slate", "Tern", "Umber", "Violet", "Willow", "Xenia", "Yarrow", "Zinnia", "Aspen", "Birch", "Coral", "Dahlia", "Ember", "Fjord"])
    kinds = [
        ("equipment loan", "kits", "remaining trained staff", "at least", "loan ledger", "site coordinator"),
        ("software rollout", "hosts", "failed smoke checks", "at most", "rollback checklist", "release steward"),
        ("sample transfer", "crates", "remaining coolant hours", "at least", "custody manifest", "transfer custodian"),
        ("archive intake", "boxes", "unresolved label errors", "at most", "intake discrepancy sheet", "archive registrar"),
    ]
    topic_data = []
    def add(topic, role, rev, body, *, scope="shared", owner="records", state="adopted", date="2026-06-01"):
        sid = "s-" + hashlib.sha256(f"{eid}/{topic}/{role}/{rev}".encode()).hexdigest()[:14]
        doc = {"source_id": sid, "logical_id": f"{topic}/{role}", "revision": rev,
               "scope": scope, "owner": owner, "title": f"{topic}: {role} ({rev})",
               "body": body, "state": state, "effective_from": date, "effective_to": None}
        sources.append(doc); source_info[sid] = doc
        return sid
    privacy_body = "Internal response codes belong to one operator. Shared handoffs may carry operational decisions and source citations, but must omit internal response codes. Missing approval-ticket records must be reported as unknown; an adopted policy is not a ticket receipt."
    privacy = add("Common operating policy", "information handling", "v1", privacy_body)
    for n, name in enumerate(names):
        kind, unit, metric, relation, artifact, role = kinds[(n + index) % len(kinds)]
        topic = f"{name} {kind}"
        area = ["north", "east", "south", "west"][(n + index) % 4]
        limit = rng.randint(18, 85)
        changed_limit = limit + rng.choice([-7, 9, 13])
        threshold = rng.randint(3, 8)
        observed = threshold + rng.choice([-2, 2])
        owner = rng.choice(["Aki", "Noa", "Lena", "Omar", "Mira", "Ivo", "Tala", "Sol"]) + f" {n+1}"
        retention = rng.choice([7, 14, 21, 30, 45])
        is_approved = (n + index) % 3 != 0
        initial_state = "adopted" if is_approved else "proposed"
        later_state = ("superseded" if update == "withdraw" else "adopted")
        effective = "2026-06-01"
        p1 = f"For {topic}, the {area} area policy is {initial_state}. Its limit is {limit} {unit}. It takes effect on {effective}. A proposal does not authorize work."
        p2 = (f"For {topic}, the {area} area policy is withdrawn; no work is authorized from 2026-06-10. The earlier policy is superseded. No replacement limit has been adopted." if update == "withdraw" else
              f"For {topic}, the {area} area policy is adopted with a limit of {changed_limit} {unit}, effective 2026-06-10. This revision replaces the earlier area policy. Evaluate operational eligibility using the separate eligibility-conditions document.")
        if length == "long":
            # Real table cells vary in policy, units, capacity and constraints;
            # these are additional area policies, not repeated padding prose.
            table = ["Area annex (separate areas; none overrides the named area above).", "Area | Unit | Limit | Approval | Working window | Required companion record | Restriction"]
            for k in range(24):
                zone = f"annex-{k+1}"
                table.append(f"{zone} | {unit} | {rng.randint(10,120)} | {rng.choice(['proposed','adopted','rejected'])} | {8+k%5}:00-{14+k%6}:00 | {rng.choice(['inspection log','dispatch list','receipt register','damage record'])} | {rng.choice(['no overnight custody','two signatories before transfer','closed during maintenance','return unused stock before closing','keep sealed items separate'])}")
            p1 += "\n\n" + "\n".join(table)
            p2 += "\n\n" + "\n".join(table)
        policy1 = add(topic, "area policy", "v1", p1, state=initial_state)
        policy2 = add(topic, "area policy", "v2", p2, state=later_state, date="2026-06-10")
        condition = f"Work for {topic} in the {area} area may proceed if and only if its area policy is adopted and {metric} is {relation} {threshold}. These are the complete operational eligibility conditions. A withdrawn or proposed policy blocks work regardless of the measurement. The threshold uses the current measurement log, not the planning estimate. Handoff recordkeeping is a separate obligation, not an additional eligibility prerequisite."
        criteria = add(topic, "eligibility conditions", "v1", condition)
        log = f"The current {metric} for {topic} in the {area} area is {observed}. This is the checked reading. The planning estimate was {observed+5}, and must not be used for the eligibility decision. No approval-ticket receipt is included in this log."
        measured = add(topic, "measurement log", "v1", log)
        handoff_body = f"For {topic} in the {area} area, {owner} is the {role}. The next operator must receive the {artifact}. Retain this handoff record for {retention} days. A signed receipt proves delivery but does not replace the named handoff item. This handoff rule is independent of policy revisions and remains in force after a withdrawal."
        if length == "long":
            handoff_body += ("\n\nThe receiving operator checks the item title, the covered area, and the source revision before accepting custody. If an earlier operator supplied a different limit, the receiving operator records the discrepancy and consults the active area policy. A handoff may be stored while operations are blocked; storing it does not authorize the underlying work. Missing information remains unknown until a source provides it."
                             "\n\nRecord classification: an inspection log documents a check; a dispatch list documents intended movements; a receipt register documents receipt; an incident note documents an exception. These records have separate purposes. Do not rename one record to satisfy the requirement for another. For unrelated annex areas, consult their companion records in the area table.")
        handoff = add(topic, "handoff instructions", "v1", handoff_body)
        code = f"TEST-{rng.randrange(100000,999999)}-{name.upper()}"
        private = add(topic, "operator-only response code", "v1", f"The internal response code for {topic} is {code}. It is visible only to operator-04 and must not appear in shared handoffs.", scope="private", owner="operator-04")
        ticket = f"APP-{name.upper()}-{index:02}-{n+1:02}" if (index+n) % 2 else None
        receipt = (add(topic, "approval-ticket receipt", "v1", f"The approval-ticket receipt for {topic} in the {area} area records identifier {ticket}. This receipt identifies the recorded administrative transaction only; it does not change the current policy state or authorize work after withdrawal.") if ticket else None)
        topic_data.append(dict(topic=topic, area=area, limit=limit, later_limit=None if update=="withdraw" else changed_limit,
                               threshold=threshold, observed=observed, owner=owner, artifact=artifact, retention=retention,
                               initial_state=initial_state, later_state=later_state, code=code, relation=relation,
                               policy1=policy1, policy2=policy2, criteria=criteria, measured=measured, handoff=handoff, private=private, ticket=ticket, receipt=receipt))
    for k in range(8):
        add(f"Unrelated district {k}", "archived transport instruction", "v1",
            f"District {k} retains its 2024 transport allocation of {11+k} vehicles. These instructions concern a different district and do not authorize equipment loans, software rollouts, sample transfers or archive intake elsewhere. The named contact is District officer {k}. The archival instruction remains historical; it is not a current area policy.", state="superseded")
    all_before = [s['source_id'] for s in sources if s['revision'] != 'v2']
    # A current snapshot contains only active heads; history was available in
    # earlier snapshots. The version transition is observable and auditable.
    old_ids = {x['policy1'] for x in topic_data}
    all_after = [s['source_id'] for s in sources if s['source_id'] not in old_ids]
    waves = []; gold_tasks = {}
    def fs(typ, description):
        return {"type": typ, "description": description, "nullable": True}
    def gf(value, ids, quotes=None, dynamic=None):
        g = {"expected":value,"acceptable_values":[value],"must_be_unknown":value is None,
             "exact_quotes":[{"source_id":sid,"quote":(quotes or {}).get(sid, source_info[sid]['body'].split('\n\n')[0])} for sid in ids]}
        if dynamic: g['dynamic'] = dynamic
        return g
    for w in range(4):
        date = "2026-06-03" if w < 2 else "2026-06-12"
        tasks = []
        for col in range(4):
            i = w*4+col
            n = 0 if reuse == "high" else i
            d = topic_data[n]
            current = d['policy1'] if w < 2 else d['policy2']
            state = d['initial_state'] if w < 2 else d['later_state']
            tid = f"{eid}-t{i+1:02}"
            deps = [] if w == 0 else [f"{eid}-t{i-3:02}"]
            common = f"For {d['topic']} in the {d['area']} area, use the current sources. "
            if col == 0:
                spec = {'status':fs('string','Policy state: proposed, adopted or superseded.'), 'limit':fs('number','Current authorized limit, or null if none is adopted.'), 'effective_date':fs('string','Effective date of the current policy, ISO format.')}
                request = common + "Report the policy state, limit, and effective date. Do not authorize work from a proposal or a withdrawn policy."
                limit = (d['limit'] if state=='adopted' else None) if w < 2 else d['later_limit']
                fields = {'status':gf(state,[current]),'limit':gf(limit,[current]),'effective_date':gf('2026-06-01' if w<2 else '2026-06-10',[current])}
            elif col == 1:
                sufficient = d['observed'] >= d['threshold'] if d['relation']=='at least' else d['observed'] <= d['threshold']
                spec = {'can_proceed':fs('boolean','Whether adopted policy and all measurement prerequisites permit work.'),'observed_value':fs('number','Checked reading, not planning estimate.'),'required_threshold':fs('number','Eligibility threshold.')}
                request = common + "Determine whether work may proceed, and give the checked reading and eligibility threshold."
                fields={'can_proceed':gf(state=='adopted' and sufficient,[current,d['criteria'],d['measured']]),'observed_value':gf(d['observed'],[d['measured']]),'required_threshold':gf(d['threshold'],[d['criteria']])}
            elif col == 2:
                spec={'handoff_item':fs('string','Required handoff document name only.'),'owner':fs('string','Responsible person name only.'),'retention_days':fs('number','Record retention duration in days.')}
                request=common+"Identify the required handoff item, responsible person, and retention duration; a receipt is not a substitute for the required item."
                fields={'handoff_item':gf(d['artifact'],[d['handoff']]),'owner':gf(d['owner'],[d['handoff']]),'retention_days':gf(d['retention'],[d['handoff']])}
            else:
                spec={'status':fs('string','Current policy state.'),'internal_code':fs('string','Internal code only if this actor is authorized; otherwise null.'),'approval_ticket':fs('string','Approval-ticket identifier if a receipt exists; otherwise null.')}
                request=common+"Report the policy state. Supply the internal response code only if your actor is authorized to read it. An approved policy is not proof of an approval-ticket receipt."
                fields={'status':gf(state,[current]),'internal_code':gf(d['code'] if i==3 else None,[d['private']] if i==3 else [privacy]),'approval_ticket':gf(d['ticket'],[d['receipt']] if d['ticket'] else [privacy,d['measured']])}
            if deps:
                spec['incoming_status']=fs('string','Copy the policy status in the supplied predecessor handoff; null if it has no status field or is withheld. Do not replace it with the current policy state.')
                fields['incoming_status']=gf(None,[],dynamic={'kind':'predecessor_field','task_id':deps[0],'field':'status'})
                request += " Also preserve the incoming predecessor's reported status in incoming_status, separately from current facts."
            tasks.append({'task_id':tid,'actor':actors[i],'topic':d['topic'],'area':d['area'],'request':request,'output_spec':spec,'depends_on':deps})
            gold_tasks[tid]={'fields':fields,'required_source_ids':sorted({q['source_id'] for f in fields.values() for q in f['exact_quotes']}),'forbidden_claims':[x['code'] for x in topic_data if not (i==3 and x is d)]}
        waves.append({'wave':w+1,'as_of':date,'available_source_ids':all_before if w<2 else all_after,'event':'initial snapshot' if w==0 else ('handoff without source changes' if w==1 else ('policy revisions published' if w==2 else 'handoff after update')),'tasks':tasks})
    episode={'episode_id':eid,'topic':f'Controlled {split} operating campaign {index}',
             'design':{'length':length,'reuse':reuse,'update':update,'source_topics':16,'independent_benchmark':False},'sources':sources,'waves':waves}
    gold={'episode_id':eid,'tasks':gold_tasks,'fixture_note':'Offline only. Exact values are mechanically graded; cite support and unauthorized content are graded separately. Dynamic incoming_status is graded from the actual supplied predecessor output, not from an oracle predecessor.'}
    return episode,gold


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);a=parser.parse_args()
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    for split in ('dev','final'):
        for i,(length,reuse,update) in enumerate(itertools.product(('short','long'),('low','high'),('revise','withdraw')),1):
            episode,gold=make_episode(split,i,length,reuse,update)
            directory=out/split/episode['episode_id']
            dump(directory/'episode.json',episode);dump(directory/'gold.json',gold)
    readme='''# Controlled workflow diagnostic v6

v6 is a semantic repair after workflow implementation and development smoke calls on v5. The original v5 was frozen before implementation. A separate reviewer found that "only when" and unspecified other prerequisites did not make the eligibility gold a sufficient condition. v6 explicitly states complete necessary-and-sufficient eligibility conditions and separates recordkeeping obligations. Numerical values, expected answers, split membership and tasks are unchanged. Both splits receive the same wording repair; no final metrics were opened. This chronology is disclosed rather than claiming that v6 preceded implementation. v5 smoke responses remain diagnostic evidence, not a valid final architecture comparison.

v5 repairs the v4 all-null approval-ticket shortcut before any workflow implementation or inference. Some topics have a separate administrative receipt; others do not. Receipts do not override operational state. v1-v4 remain rejected drafts; no files in those directories were changed.

Eight development and eight final parameter combinations: short/long x low/high reuse x revise/withdraw. Each episode has 16 actual actor requests in four dependency waves, 16 source topics, actor-private values and eight unrelated distractor documents. Low reuse visits all 16 topics; high reuse revisits one topic with four different task purposes. Public source snapshots change between waves 2 and 3.

Long documents contain area-policy tables with different values, states, schedules, record requirements and restrictions, plus operational handoff procedures. The short/long factor is controlled synthetic content, not evidence of production document representativeness. Dev/final have disjoint topic names and independently seeded values. Both use the same four logical operation families; these are NOT 16 independently authored benchmark families. Final metrics remain closed until configuration selection.

Original sources, task descriptions and typed public output contracts are runtime data. Gold, expected values, required citations and task IDs are not given to the retriever or model. An application-level task ID is used only to route earlier outputs into actual dependent tasks. Incoming status is graded against the actual supplied preceding result; no oracle handoff is injected. All ordinary fields permit null, so the output contract does not reveal which answer is unknown.

The original v5 fixture was authored after the Phase 3 proposal and before new retrieval/reuse/memory implementation. This v6 repair was made after implementation and v5 development smoke, before valid comparative measurements and final metrics. The author knew earlier Phase 2 results and authored this controlled diagnostic; it is not an external independent benchmark.

FREEZE.json records the actual UTC creation time and file hashes. Semantic/structural acceptance is separately recorded; freeze alone is not acceptance. Repairs after freeze require a new fixture version. Real sources and credentials are absent.
'''
    (out/'README.md').write_text(readme)
    files={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file()}
    dump(out/'FREEZE.json',{'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'files':files,
                          'manifest_sha256':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest(),
                          'author':'root','new_retrieval_reuse_memory_implementation_started':True,'original_design_frozen_before_implementation':'phase2-workflow-v5','repair':'eligibility necessary-and-sufficient wording after v5 development smoke; no final metrics opened','independent_benchmark':False})
    print(json.dumps({'fixture':str(out),'episodes':16,'tasks':256,'files':len(files)}))


if __name__=='__main__':main()
