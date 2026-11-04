"""Audit stability rows by actual request mode, with no model quality inference."""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--fixture', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--plot', action='store_true')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    cases={c['id']:c for c in json.loads((a.fixture/'final.json').read_text())}
    rows=[json.loads(x) for x in (a.run/'rows.jsonl').read_text().splitlines()]
    groups=defaultdict(list)
    for r in rows:
        r['mode']=cases[r['intent_id']]['mode']
        groups[(r['method'],r['size'],'all' if r['mode']=='all' else 'non_all')].append(r)
    tokens=[]
    for (method,size,mode),g in sorted(groups.items()):
        t=sorted(r['input_reference_tokens'] for r in g)
        tokens.append(dict(method=method,size=size,mode_group=mode,
                           unique_intents=len({r['intent_id'] for r in g}),rows=len(g),
                           median=statistics.median(t),p95=t[math.ceil(len(t)*.95)-1],
                           overflow_rows=sum(r['budget_exceeded'] for r in g)))
    quality={};invariance={}
    for method in sorted({r['method'] for r in rows}):
        g=[r for r in rows if r['method']==method and r['answerable']]
        ids=sorted({r['intent_id'] for r in g})
        quality[method]={'passed_intents':[i for i in ids if all(r['complete_evidence'] for r in g if r['intent_id']==i)],'total_intents':len(ids)}
        hashes=defaultdict(set)
        for r in rows:
            if r['method']==method:hashes[(r['intent_id'],r['variant'],r['size'])].add(r['payload_sha256'])
        invariance[method]={'groups':len(hashes),'invariant':sum(len(h)==1 for h in hashes.values()),
                            'failed_groups':[list(k) for k,v in hashes.items() if len(v)>1]}
    summary={'run':str(a.run),'rows':len(rows),'raw_sha256':hashlib.sha256((a.run/'rows.jsonl').read_bytes()).hexdigest(),
             'mode_counts':{m:sum(c['mode']==m for c in cases.values()) for m in ['current','history','all']},
             'tokens':tokens,'all_conditions_evidence':quality,'order_invariance':invariance,
             'private_exposure':sum(r['private_exposure'] for r in rows),
             'stale_exposure':sum(r['stale_exposure'] for r in rows),
             'limitations':['Raw 10/11 includes inaccessible private-gold defect final-10; do not relabel as 100%.',
                            'No model was called at 1,000 or 10,000 documents in this stability experiment.',
                            'Supersedes audit-v2 mode table: category all_items is not equivalent to request mode all.']}
    (a.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    if a.plot:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig,ax=plt.subplots(1,2,figsize=(10,4),layout='constrained')
        labels={'legacy':'Sections 2k','canonical_8000':'Sections 8k','parent8000':'Parent sections 8k','fullproject':'Project full text'}
        for method,label in labels.items():
            g=[x for x in tokens if x['method']==method and x['mode_group']=='non_all']
            ax[0].plot([x['size'] for x in g],[x['median'] for x in g],marker='o',label=label)
        g=[x for x in tokens if x['method']=='legacy' and x['mode_group']=='all']
        ax[1].plot([x['size'] for x in g],[x['median'] for x in g],marker='o',label='Exhaustive requests (all methods)')
        for axis in ax:
            axis.set(xscale='log',yscale='log',xlabel='Documents in corpus',ylabel='Median reference input tokens')
            axis.grid(alpha=.2);axis.legend(fontsize=8)
        ax[0].set_title('Current / history: 10 intents')
        ax[1].set_title('Exhaustive: 2 intents')
        fig.suptitle('Token limits and exhaustive coverage have different growth costs')
        fig.savefig(a.output/'tokens.png',dpi=170);fig.savefig(a.output/'tokens.svg')
    print(json.dumps({'rows':len(rows),'mode_counts':summary['mode_counts'],'quality':quality},ensure_ascii=False))


if __name__=='__main__':main()
