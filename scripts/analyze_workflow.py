"""Summarize measured case pairs; resample cases, never individual actors."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import random
import statistics


def bounds(rows):
    if any(r['usage']['cost_lower_nanodollars'] is None for r in rows):
        raise ValueError('unresolved usage: cannot report a complete cost comparison')
    return [sum(r['usage'][key] for r in rows)/1e9 for key in
            ('cost_lower_nanodollars','cost_upper_nanodollars')]


def summarize(rows):
    times=sorted(r['elapsed_seconds'] for r in rows)
    return {'case_arms':len(rows),'distinct_cases':len({r['case'] for r in rows}),'strict_successful_cases':sum(r['quality']['case_pass'] for r in rows),
            'strict_successful_tasks':sum(r['quality']['strict_pass_count'] for r in rows),
            'value_correct_tasks':sum(r['quality']['values_correct_count'] for r in rows),
            'tasks':sum(r['quality']['task_count'] for r in rows),
            'leak_tasks':sum(r['quality']['forbidden_leak_count'] for r in rows),
            'cost_usd_interval':bounds(rows),'case_seconds_sum':sum(r['elapsed_seconds'] for r in rows),
            'median_case_seconds':statistics.median(r['elapsed_seconds'] for r in rows),
            'p95_case_seconds_nearest_rank':times[max(0, math.ceil(.95*len(times))-1)],
            'calls':sum(r['usage']['calls'] for r in rows),
            'input_tokens':sum(r['usage']['totals']['input_tokens'] for r in rows),
            'output_tokens':sum(r['usage']['totals']['output_tokens'] for r in rows),
            'cached_tokens':sum(r['usage']['totals']['cached_tokens'] for r in rows),
            'record_builds':sum(r['record_builds'] for r in rows),
            'record_hits':sum(r['record_hits'] for r in rows),
            'fallback_tasks':sum(r['fallback_tasks'] for r in rows)}


def compare(baseline, candidate):
    from collections import Counter
    if Counter(r['case'] for r in baseline) != Counter(r['case'] for r in candidate):
        raise ValueError('paired comparison requires identical cases and repetition counts')
    task_pairs = None
    if all('tasks' in r['quality'] for r in baseline + candidate):
        left_runs, right_runs = defaultdict(list), defaultdict(list)
        for r in baseline: left_runs[r['case']].append(r)
        for r in candidate: right_runs[r['case']].append(r)
        task_pairs = {'wins': 0, 'losses': 0, 'ties': 0, 'new_field_errors': []}
        for case in sorted(left_runs):
            for repetition, (left_row, right_row) in enumerate(zip(left_runs[case], right_runs[case]), 1):
                left_tasks = {t['task_id']: t for t in left_row['quality']['tasks']}
                right_tasks = {t['task_id']: t for t in right_row['quality']['tasks']}
                if left_tasks.keys() != right_tasks.keys():
                    raise ValueError('paired task identities differ')
                for tid, x in left_tasks.items():
                    y = right_tasks[tid]
                    delta = int(y['strict_pass']) - int(x['strict_pass'])
                    task_pairs['wins' if delta > 0 else 'losses' if delta < 0 else 'ties'] += 1
                    for field, correct in x['field_values'].items():
                        if correct and not y['field_values'][field]:
                            task_pairs['new_field_errors'].append({'case': case, 'repetition': repetition,
                                                                  'task_id': tid, 'field': field})
    def cluster(rows):
        grouped=defaultdict(list)
        for r in rows:grouped[r['case']].append(r)
        result={}
        for case,group in grouped.items():
            costs=bounds(group)
            result[case]={'case':case,'elapsed_seconds':sum(r['elapsed_seconds'] for r in group),
                'usage':{'cost_lower_nanodollars':round(costs[0]*1e9),'cost_upper_nanodollars':round(costs[1]*1e9)},
                'quality':{'strict_pass_count':sum(r['quality']['strict_pass_count'] for r in group),
                           'case_pass':sum(r['quality']['case_pass'] for r in group)}}
        return result
    left=cluster(baseline);right=cluster(candidate)
    common=sorted(left.keys()&right.keys())
    if not common:return None
    a=[left[k] for k in common];b=[right[k] for k in common]
    al,au=bounds(a);bl,bu=bounds(b)
    seconds=lambda rows:sum(r['elapsed_seconds'] for r in rows)
    rng=random.Random(35113);deltas=[];cost_lows=[];cost_highs=[]
    for _ in range(4000):
        sample=rng.choices(common,k=len(common))
        deltas.append(1-seconds([right[k] for k in sample])/seconds([left[k] for k in sample]))
        sal,sau=bounds([left[k] for k in sample]);sbl,sbu=bounds([right[k] for k in sample])
        cost_lows.append(1-sbu/sal);cost_highs.append(1-sbl/sau)
    deltas.sort();cost_lows.sort();cost_highs.sort()
    outcomes={'task_score_wins':0,'task_score_losses':0,'task_score_ties':0,
              'case_pass_wins':0,'case_pass_losses':0,'case_pass_ties':0}
    paired=[]
    for k in common:
        x,y=left[k],right[k]
        delta=y['quality']['strict_pass_count']-x['quality']['strict_pass_count']
        outcomes['task_score_'+('wins' if delta>0 else 'losses' if delta<0 else 'ties')]+=1
        cdelta=int(y['quality']['case_pass'])-int(x['quality']['case_pass'])
        outcomes['case_pass_'+('wins' if cdelta>0 else 'losses' if cdelta<0 else 'ties')]+=1
        paired.append({'case':k,'strict_task_delta':delta,'case_pass_delta':cdelta,
                       'time_saving_fraction':1-y['elapsed_seconds']/x['elapsed_seconds']})
    return {'paired_cases':len(common),'cost_saving_fraction_interval':[1-bu/al,1-bl/au],
            'elapsed_time_saving_fraction':1-seconds(b)/seconds(a),
            'case_bootstrap_time_saving_95_interval':[deltas[100],deltas[3899]],
            'case_bootstrap_cost_saving_95_interval':[cost_lows[100],cost_highs[3899]],
            'paired_outcomes':outcomes,'pairs':paired,
            'paired_tasks':task_pairs,
            'noninferiority_established':False,
            'uncertainty_note':'Exploratory resampling of controlled cases, not a population confidence guarantee; no actor-level pseudo-replication.'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,nargs='+',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();raw={'rows':[]};per_run={}
    for path in a.run:
        source=json.loads((path/'summary.json').read_text())
        if source['status']!='complete':raise ValueError('incomplete run')
        raw['rows'].extend(source['rows'])
        per_run[path.name]={arm:summarize([r for r in source['rows'] if r['arm']==arm])
                            for arm in sorted({r['arm'] for r in source['rows']})}
    groups=defaultdict(list)
    for row in raw['rows']:groups[row['arm']].append(row)
    result={'source_runs':[p.name for p in a.run],'per_run':per_run,'arms':{k:summarize(v) for k,v in groups.items()},'comparisons':{},'strata':{}}
    for baseline in ('full6','full12','handoff6','handoff12','prefix12','cache12'):
        if baseline in groups:
            for candidate in groups:
                if candidate!=baseline:result['comparisons'][baseline+'__'+candidate]=compare(groups[baseline],groups[candidate])
    for dimension in ('length','reuse','update'):
        result['strata'][dimension]={}
        for value in sorted({r['design'][dimension] for r in raw['rows']}):
            result['strata'][dimension][value]={arm:summarize([r for r in rows if r['design'][dimension]==value]) for arm,rows in groups.items()}
    result.update(invoice_measured=False,independent_benchmark=False,production_workflow_measured=False)
    a.output.mkdir(parents=True,exist_ok=False);(a.output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'arms':result['arms'],'comparisons':{k:{n:v for n,v in row.items() if n!='pairs'} for k,row in result['comparisons'].items()}}))


if __name__=='__main__':main()
