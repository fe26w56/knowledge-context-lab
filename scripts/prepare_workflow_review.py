"""Build arm-label-hidden semantic review packets after measured execution."""
import argparse
import hashlib
import json
from pathlib import Path


def load(p):return json.loads(Path(p).read_text())


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--fixture',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();meta=load(a.run/'metadata.json');summary=load(a.run/'summary.json')
    if summary['status']!='complete':raise ValueError('incomplete measured run')
    a.output.mkdir(parents=True,exist_ok=False);mapping=[];packets={}
    for row in summary['rows']:
        case,arm=row['case'],row['arm'];base=a.fixture/meta['split']/case
        ep,gold=load(base/'episode.json'),load(base/'gold.json')
        source_by_id={s['source_id']:s for s in ep['sources']}
        result=load(a.run/case/arm/'workflow/result.json')
        for w in ep['waves']:
            for task in w['tasks']:
                tid=task['task_id'];answer=result['results'][tid]
                review_id=hashlib.sha256((a.run.name+'/'+case+'/'+arm+'/'+tid).encode()).hexdigest()[:20]
                mapping.append({'review_id':review_id,'case':case,'arm':arm,'task_id':tid})
                fields={}
                for name,rule in gold['tasks'][tid]['fields'].items():
                    expected=rule['expected']
                    if rule.get('dynamic'):
                        incoming=answer['payload']['predecessor_handoffs']
                        expected=(incoming[-1]['fields'].get(rule['dynamic']['field'],{}) or {}).get('value') if incoming else None
                    fields[name]={'expected':expected,'actual':answer['output']['fields'][name],
                                  'canonical_support':rule['exact_quotes'],'dynamic_actual_handoff':bool(rule.get('dynamic'))}
                quoted_ids={c['source_id'] for f in answer['output']['fields'].values() for c in f['citations']}
                packet={'review_id':review_id,'request':task['request'],'actor':task['actor'],'as_of':w['as_of'],
                    'output_spec':task['output_spec'],'fields':fields,'needs_more':answer['output']['needs_more'],
                    'actual_predecessor_handoffs':answer['payload']['predecessor_handoffs'],
                    'supplied_quoted_sources':[s for s in answer['payload']['sources'] if s['source_id'] in quoted_ids],
                    'forbidden_codes':gold['tasks'][tid]['forbidden_claims'],
                    'mechanical_grade':next(t for t in row['quality']['tasks'] if t['task_id']==tid)}
                # Remove join labels from the review-facing mechanical grade.
                packet['mechanical_grade']=dict(packet['mechanical_grade']);packet['mechanical_grade'].pop('task_id',None)
                packets.setdefault(case,[]).append(packet)
    for case,rows in packets.items():
        rows.sort(key=lambda r:r['review_id']);(a.output/(case+'.json')).write_text(json.dumps(rows,indent=2)+'\n')
    (a.output/'mapping.json').write_text(json.dumps(mapping,indent=2)+'\n')
    (a.output/'README.md').write_text('Arm labels are hidden in case packets; context size may still reveal a method. Expected values and canonical support are OFFLINE review inputs, never model/retriever inputs. Review quote entailment, states, unknowns, direct handoff and privacy separately. A mechanical pass is not a semantic review. Save one judgment and rationale per review_id; do not modify responses.\n')
    print(json.dumps({'tasks':len(mapping),'cases':len(packets)}))


if __name__=='__main__':main()
