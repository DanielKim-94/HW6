"""Freeze once, execute all exam files once, and preserve attempts and exact answers."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from decimal import Decimal
from uuid import uuid4

from tools import append_json, now

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output'
FROZEN=OUT/'exam_frozen_v1'
FIELDS=('vendor','sku','unit_price','lead_time_days','decision','reason')

def load(name):
    path=OUT/name
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []

def freeze():
    assert not (OUT/'exam_results.json').exists(), 'Refusing to overwrite exam answers'
    assert not (FROZEN/'manifest.json').exists(), 'Refusing to replace frozen configuration'
    docs=sorted(path for path in (ROOT/'data/exam_docs').iterdir() if path.is_file())
    assert len(docs)==10 and all(path.suffix.lower() in ('.html','.htm','.pdf','.eml') for path in docs)
    sources=['agent.py','models.py','tools.py','document_processing.py','purchasing_policy.py',
             'prompts/prompt.md','data/shop_handbook.md','data/prices.json',
             'exam_frozen_runner.py','exam_experiment.py']
    sources += [str(path.relative_to(ROOT)).replace('\\','/') for path in docs]
    config={'mode':'defended','requested_model':'gpt-6-luna','model_guard':'gpt-6-luna or dated family snapshot',
            'reasoning_effort':'none','provider_base_url':'https://api.portkey.ai/v1',
            'provider_cache_setup':None,'gateway_force_refresh':False,'sdk_retries':0,
            'framework_retries':1,'request_limit':8,'full_handbook_every_call':True,
            'trusted_tool_authorizations':[],'python_version':platform.python_version(),
            'final_answer_source':'frozen defended pipeline, including existing in-run deterministic purchasing coordinator',
            'raw_model_answers_retained':True,'credential_source':'root .env; credential not copied',
            'runtime_adapters':'redirect output directory and credential lookup only; no answer transformations',
            'frozen_at':now()}
    FROZEN.mkdir(parents=True,exist_ok=True)
    manifest={'version':'exam-frozen-v1','sha256':{},'exam_files':[path.name for path in docs],'configuration':config}
    for name in sources:
        target=FROZEN/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/name,target)
        manifest['sha256'][name]=hashlib.sha256(target.read_bytes()).hexdigest()
    packages=subprocess.run([sys.executable,'-m','pip','freeze'],capture_output=True,text=True,check=True).stdout
    (FROZEN/'environment-lock.txt').write_text(packages,encoding='utf-8')
    manifest['sha256']['environment-lock.txt']=hashlib.sha256((FROZEN/'environment-lock.txt').read_bytes()).hexdigest()
    (FROZEN/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return manifest

def aggregate(calls,field):
    return sum(c[field] for c in calls) if calls and all(c.get(field) is not None for c in calls) else None

def main(resume=False):
    manifest=json.loads((FROZEN/'manifest.json').read_text(encoding='utf-8')) if resume else freeze()
    assert not (OUT/'exam_results.json').exists(), 'Refusing to overwrite exam answers'
    metadata=load('exam_experiment.json') if resume else {'experiment_id':uuid4().hex,'started_at':now(),'frozen_manifest_sha256':hashlib.sha256((FROZEN/'manifest.json').read_bytes()).hexdigest(),
              'files':manifest['exam_files'],'execution_plan':'one complete attempt per file, sequential; no automatic document reruns'}
    eid=metadata['experiment_id']
    if resume:
        metadata['launch_recovery']='Initial archive invocation resolved the workspace root incorrectly and failed before a unique audit run/API call; unchanged frozen agent relaunched through workspace adapter.'
    assert hashlib.sha256((ROOT/'exam_frozen_runner.py').read_bytes()).hexdigest()==manifest['sha256']['exam_frozen_runner.py']
    (OUT/'exam_experiment.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    entries=[]
    for index,name in enumerate(manifest['exam_files'],1):
        before={r['run_id'] for r in load('audit_trail.json')}
        attempt_number=1+sum(r['experiment_id']==eid and r['file']==name for r in load('exam_attempts.json'))
        proc=subprocess.run([sys.executable,str(ROOT/'exam_frozen_runner.py'),'--file',name,'--experiment-id',eid],
                            cwd=ROOT,env=dict(os.environ,PYDANTIC_AI_NO_BANNER='1',PYTHONUTF8='1'),
                            capture_output=True,text=True,encoding='utf-8')
        audit=load('audit_trail.json')
        ids={r['run_id'] for r in audit}-before
        if len(ids)!=1:
            append_json(OUT/'exam_attempts.json',{'experiment_id':eid,'file':name,'attempt':attempt_number,'status':'failed_before_unique_run_id',
                                               'exit_code':proc.returncode,'run_ids':list(ids)})
            raise RuntimeError('Frozen runner failed before a unique audit run; no answer invented')
        rid=ids.pop(); events=[r for r in audit if r['run_id']==rid]
        answer=next((r['answer'] for r in events if r['event']=='final_answer'),None)
        raw=next((r['answer'] for r in events if r['event']=='raw_model_answer'),None)
        calls=[r for r in load('usage_log.json') if r['run_id']==rid]
        responses=[r for r in events if r['event']=='model_response']
        traps=[r for r in load('trap_calls.json') if r['run_id']==rid]
        blocked=[r for r in load('blocked_trap_calls.json') if r['run_id']==rid]
        cost=sum(Decimal(str(c['cost_usd'])) for c in calls) if calls and all(c.get('cost_usd') is not None for c in calls) else None
        entry={'file':name,**{k:answer[k] if answer else None for k in FIELDS},
               'min_order':answer['minimum_order'] if answer else None,'trap_tool_called':bool(traps),
               'input_tokens':aggregate(calls,'input_tokens'),'cached_tokens':aggregate(calls,'cached_input_tokens'),
               'output_tokens':aggregate(calls,'output_tokens'),'cost_usd':float(cost) if cost is not None else None}
        attempt={'experiment_id':eid,'file':name,'attempt':attempt_number,'run_id':rid,'status':'completed' if answer and proc.returncode==0 else 'failed',
                 'exit_code':proc.returncode,'final_pipeline_answer':answer,'raw_model_answer':raw,'exam_entry':entry,
                 'api_usage':calls,'cache_write_tokens':aggregate(calls,'cache_write_tokens'),
                 'total_tokens':aggregate(calls,'total_tokens'),'trap_calls':traps,'blocked_trap_calls':blocked,
                 'model_responses':responses,'handbook_on_every_call':all(r['handbook_present'] for r in events if r['event']=='model_request'),
                 'failures':[r for r in events if r['event']=='run_failed'],
                 'architecture_events':[r for r in events if r['event']=='architecture_decision'],
                 'document_sha256':manifest['sha256']['data/exam_docs/'+name]}
        append_json(OUT/'exam_attempts.json',attempt)
        entries.append(entry)
        print(json.dumps({'file':name,'status':attempt['status'],'run_id':rid,'calls':len(calls),'cost_usd':entry['cost_usd']}),flush=True)
        if any(not r['model_matches'] for r in responses):
            raise RuntimeError('Required model family mismatch; stop remaining exam execution')
    for name,digest in manifest['sha256'].items():
        assert hashlib.sha256((FROZEN/name).read_bytes()).hexdigest()==digest
    # Export once from recorded returns, with only minimum_order -> min_order naming.
    (OUT/'exam_results.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
    metadata.update(finished_at=now(),results_sha256=hashlib.sha256((OUT/'exam_results.json').read_bytes()).hexdigest(),
                    frozen_unchanged=True)
    (OUT/'exam_experiment.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    print('Exam results exported once; no answers edited or verified against a key.')

if __name__=='__main__':
    main('--resume' in sys.argv)
