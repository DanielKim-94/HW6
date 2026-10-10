"""Rerun only files without an accepted answer; retain failed exports and attempts."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from decimal import Decimal

from exam_experiment import ROOT, OUT, FROZEN, FIELDS, load, aggregate
from tools import append_json, now

def main():
    metadata=load('exam_experiment.json'); eid=metadata['experiment_id']
    manifest=json.loads((FROZEN/'manifest.json').read_text(encoding='utf-8'))
    attempts=[r for r in load('exam_attempts.json') if r['experiment_id']==eid]
    complete={r['file']:r for r in attempts if r['status']=='completed'}
    pending=[name for name in metadata['files'] if name not in complete]
    assert pending, 'No failed document needs rerunning; refusing to change accepted answers'
    history=OUT/f'exam_results_before_rerun_{len(attempts)}.json'
    assert not history.exists()
    shutil.copyfile(OUT/'exam_results.json',history)
    history_hash=hashlib.sha256(history.read_bytes()).hexdigest()
    assert history_hash==metadata['results_sha256']
    for name in pending:
        for source,digest in manifest['sha256'].items():
            assert hashlib.sha256((FROZEN/source).read_bytes()).hexdigest()==digest
        before={r['run_id'] for r in load('audit_trail.json')}
        relative='--relative-doc' in sys.argv
        runner=ROOT/('exam_relative_runner.py' if relative else 'exam_frozen_runner.py')
        proc=subprocess.run([sys.executable,str(runner),'--file',name,'--experiment-id',eid],
                            cwd=ROOT,env=dict(os.environ,PYDANTIC_AI_NO_BANNER='1',PYTHONUTF8='1'),
                            capture_output=True,text=True,encoding='utf-8')
        audit=load('audit_trail.json'); ids={r['run_id'] for r in audit}-before
        assert len(ids)==1
        rid=ids.pop(); events=[r for r in audit if r['run_id']==rid]
        answer=next((r['answer'] for r in events if r['event']=='final_answer'),None)
        raw=next((r['answer'] for r in events if r['event']=='raw_model_answer'),None)
        calls=[r for r in load('usage_log.json') if r['run_id']==rid]
        traps=[r for r in load('trap_calls.json') if r['run_id']==rid]
        blocked=[r for r in load('blocked_trap_calls.json') if r['run_id']==rid]
        responses=[r for r in events if r['event']=='model_response']
        cost=sum(Decimal(str(c['cost_usd'])) for c in calls) if calls and all(c.get('cost_usd') is not None for c in calls) else None
        entry={'file':name,**{k:answer[k] if answer else None for k in FIELDS},
               'min_order':answer['minimum_order'] if answer else None,'trap_tool_called':bool(traps),
               'input_tokens':aggregate(calls,'input_tokens'),'cached_tokens':aggregate(calls,'cached_input_tokens'),
               'output_tokens':aggregate(calls,'output_tokens'),'cost_usd':float(cost) if cost is not None else None}
        number=1+sum(r['file']==name for r in attempts)
        attempt={'experiment_id':eid,'file':name,'attempt':number,'run_id':rid,
                 'status':'completed' if answer and proc.returncode==0 else 'failed','exit_code':proc.returncode,
                 'final_pipeline_answer':answer,'raw_model_answer':raw,'exam_entry':entry,'api_usage':calls,
                 'cache_write_tokens':aggregate(calls,'cache_write_tokens'),'total_tokens':aggregate(calls,'total_tokens'),
                 'trap_calls':traps,'blocked_trap_calls':blocked,'model_responses':responses,
                 'handbook_on_every_call':all(r['handbook_present'] for r in events if r['event']=='model_request'),
                 'failures':[r for r in events if r['event']=='run_failed'],
                 'architecture_events':[r for r in events if r['event']=='architecture_decision'],
                 'document_sha256':manifest['sha256']['data/exam_docs/'+name],
                 'rerun_reason':'previous attempt produced no accepted answer; identical frozen agent; equivalent relative document reference' if relative else 'previous attempt produced no accepted answer; identical frozen configuration',
                 'runner_sha256':hashlib.sha256(runner.read_bytes()).hexdigest(),
                 'document_reference_form':'relative' if relative else 'absolute'}
        append_json(OUT/'exam_attempts.json',attempt)
        attempts.append(attempt)
        print(json.dumps({'file':name,'attempt':number,'status':attempt['status'],'run_id':rid,'cost_usd':entry['cost_usd']}),flush=True)
        if any(not r['model_matches'] for r in responses):
            raise RuntimeError('Stop: required model family mismatch')
    complete={r['file']:r for r in attempts if r['status']=='completed'}
    latest={r['file']:r for r in attempts if 'exam_entry' in r}
    results=[(complete.get(name) or latest[name])['exam_entry'] for name in metadata['files']]
    # Only previously failed files may receive a newly accepted return; accepted rows stay identical.
    old=load(history.name)
    for entry in results:
        if entry['file'] not in pending:
            assert entry==next(r for r in old if r['file']==entry['file'])
    (OUT/'exam_results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    metadata.setdefault('export_history',[]).append({'file':history.name,'sha256':history_hash,'reason':'preserved incomplete export before full failed-document rerun'})
    metadata.update(finished_at=now(),results_sha256=hashlib.sha256((OUT/'exam_results.json').read_bytes()).hexdigest(),
                    selected_run_ids={name:row['run_id'] for name,row in complete.items()})
    (OUT/'exam_experiment.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')

if __name__=='__main__':
    main()
