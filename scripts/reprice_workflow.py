"""Recalculate rate-card estimates from saved requests; never change raw runs."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from context_lab.workflow_api import nominal_cost_bounds
from context_lab.workflow_eval import usage_summary


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();original=a.run/'summary.json';result=deepcopy(json.loads(original.read_text()))
    if result['status']!='complete':raise ValueError('incomplete run')
    hashes={}
    for row in result['rows']:
        attempts=[]
        for path in sorted((a.run/row['case']/row['arm']/'api').glob('attempt-*.json')):
            if path.name.endswith('.pending.json'):raise ValueError('unsettled request')
            attempt=json.loads(path.read_text());request=attempt['request']
            if request['model']!='gpt-6-luna' or 'prompt_cache_options' in request or any(not isinstance(m['content'],str) for m in request['input']):
                raise ValueError('request is outside the documented-default recalculation')
            attempt['nominal_cost_bounds']=nominal_cost_bounds(attempt['usage'],write_ttl='30m')
            attempts.append(attempt);hashes[str(path.relative_to(a.run))]=hashlib.sha256(path.read_bytes()).hexdigest()
        row['usage']=usage_summary(attempts)
    result['recalculation']={'original_run':a.run.name,'original_summary_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),
        'pricing_snapshot':'phase2-workflow-pricing-v3','reason':'Official guide specifies default write TTL 30m. Saved requests have no TTL or breakpoint overrides. Provider reports write counts; rates are now inferable despite absent lifetime split.',
        'original_responses_and_estimates_unchanged':True,'invoice_measured':False,'attempt_sha256':hashes}
    a.output.mkdir(parents=True,exist_ok=False);(a.output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'case_arms':len(result['rows']),'attempts':len(hashes),'originals_unchanged':True}))


if __name__=='__main__':main()
