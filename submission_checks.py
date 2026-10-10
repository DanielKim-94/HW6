"""Check layout, preserved run evidence, offline portability and public-file secrets."""
import base64
from collections import defaultdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess

from bs4 import BeautifulSoup
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output'

def load(name):
    return json.loads((OUT/name).read_text(encoding='utf-8'))

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    required=['agent.py','tools.py','models.py','document_processing.py','purchasing_policy.py','undefended.py',
              'prompts/prompt.md','requirements.txt','requirements-lock.txt','requirements-red-team.txt',
              'AI_prompts.md','README.md','.env.example','.gitignore',
              'data/shop_handbook.md','data/prices.json','data/practice_key.json']
    required+=['output/'+name for name in ('handbook_estimate.md','harness.md','trap_calls.json','usage_log.json','audit_trail.json',
        'cache_test.json','cache_test.md','attack_results.json','attack_results.md','defense_results.json','defense_results.md',
        'red_team.md','red_team_results.json','exam_results.json','exam_results.md','exam_attempts.json','hw6_report.html','hw6_visual_review.json')]
    assert all((ROOT/name).is_file() for name in required)
    counts={name:len([p for p in (ROOT/'data'/name).iterdir() if p.is_file()]) for name in ('practice_docs','exam_docs','my_attacks')}
    assert counts=={'practice_docs':12,'exam_docs':10,'my_attacks':2},counts
    data_paths=sorted(str(p.relative_to(ROOT)).replace('\\','/') for p in (ROOT/'data').rglob('*') if p.is_file())
    audit=load('audit_trail.json'); usage=load('usage_log.json'); traps=load('trap_calls.json')
    by_run=defaultdict(list); usage_runs=defaultdict(list)
    for event in audit: by_run[event['run_id']].append(event)
    for call in usage: usage_runs[call['run_id']].append(call)
    rates=json.loads((ROOT/'data/prices.json').read_text(encoding='utf-8'))['gpt-6-luna']
    def verify_run(rid,answer,expected_usage=None):
        events=by_run[rid]
        final=next(r['answer'] for r in events if r['event']=='final_answer')
        assert final==answer
        requests=[r for r in events if r['event']=='model_request']
        responses=[r for r in events if r['event']=='model_response']
        assert requests and all(r['handbook_present'] for r in requests)
        assert responses and all(r['model_matches'] for r in responses)
        calls=usage_runs[rid]
        assert calls
        if expected_usage is not None: assert calls==expected_usage
        for call in calls:
            assert any(r['response_id']==call['response_id'] for r in responses)
            if call.get('cost_usd') is not None:
                i,c,w,o=(call[k] for k in ('input_tokens','cached_input_tokens','cache_write_tokens','output_tokens'))
                assert i-c-w>=0
                cost=(Decimal(i-c-w)*Decimal(str(rates['input_per_1m']))+Decimal(c)*Decimal(str(rates['cached_input_per_1m']))+
                      Decimal(w)*Decimal(str(rates['cache_write_per_1m']))+Decimal(o)*Decimal(str(rates['output_per_1m'])))/1_000_000
                assert cost==Decimal(str(call['cost_usd']))
        return len(calls)
    checked={}
    eid=load('attack_experiment_latest.json')['experiment_id']
    baseline={r['document']:r for r in load('attack_results.json') if r['experiment_id']==eid and r['status']=='completed'}
    assert len(baseline)==12
    checked['practice_baseline']=sum(verify_run(r['run_id'],r['answer'],r['api_usage']) for r in baseline.values())
    defense_ids=load('defense_summary.json')['final_run_ids']
    defended={r['run_id']:r for r in load('defense_results.json')}
    checked['practice_final_defended']=sum(verify_run(rid,defended[rid]['answer'],defended[rid]['api_usage']) for rid in defense_ids.values())
    assert len(defense_ids)==12
    red_eid=load('red_team_latest.json')['experiment_id']
    red=[r for r in load('red_team_results.json') if r['experiment_id']==red_eid]
    assert len(red)==4
    checked['original_red_team']=sum(verify_run(r['run_id'],r['answer'],r['api_usage']) for r in red)
    exam_meta=load('exam_experiment.json'); exam=load('exam_results.json')
    assert digest(OUT/'exam_results.json')==exam_meta['results_sha256']
    completed={r['file']:r for r in load('exam_attempts.json') if r['experiment_id']==exam_meta['experiment_id'] and r['status']=='completed'}
    assert len(exam)==len(completed)==10
    for row in exam:
        record=completed[row['file']]
        assert row==record['exam_entry']
        assert row['trap_tool_called']==any(t['run_id']==record['run_id'] for t in traps)
        for field,source in [('input_tokens','input_tokens'),('cached_tokens','cached_input_tokens'),('output_tokens','output_tokens')]:
            assert row[field]==sum(c[source] for c in record['api_usage'])
        assert Decimal(str(row['cost_usd']))==sum(Decimal(str(c['cost_usd'])) for c in record['api_usage'])
    checked['exam_selected_complete']=sum(verify_run(r['run_id'],r['final_pipeline_answer'],r['api_usage']) for r in completed.values())
    cache_eid=load('cache_experiment_latest.json')['experiment_id']
    cache_calls=[r for r in load('cache_test.json') if r.get('experiment_id')==cache_eid and r.get('http_status')==200]
    assert len(cache_calls)==48
    assert all(r['gateway_cache_status']=='REFRESH' for r in cache_calls)
    for r in cache_calls:
        match=next(c for c in usage_runs[r['run_id']] if c['call_index']==r['call_index'])
        assert all(r[k]==match[k] for k in ('response_id','input_tokens','output_tokens','cached_input_tokens','cache_write_tokens','cost_usd'))
        if r['setup']=='no_cached_input_requested': assert r['cached_input_tokens']==r['cache_write_tokens']==0
    checked['controlled_cache_calls']=48
    snapshots={}
    for name in ('baseline_v1','defended_v1','exam_frozen_v1'):
        snapshot=OUT/name; manifest=json.loads((snapshot/'manifest.json').read_text(encoding='utf-8'))
        for source,value in manifest['sha256'].items(): assert digest(snapshot/source)==value,(name,source)
        snapshots[name]='all recorded source hashes unchanged'
    final_manifest=json.loads((OUT/'exam_frozen_v1/manifest.json').read_text(encoding='utf-8'))
    for name in ('agent.py','tools.py','models.py','document_processing.py','purchasing_policy.py','prompts/prompt.md'):
        assert digest(ROOT/name)==final_manifest['sha256'][name]
    html=(OUT/'hw6_report.html').read_text(encoding='utf-8'); soup=BeautifulSoup(html,'html.parser')
    assert not soup.find_all(['script','link','iframe','object','embed'])
    for element in soup.find_all(True):
        for attr in ('src','href','srcset','action','poster'):
            if element.get(attr): assert element[attr].startswith(('data:','#'))
    assert not re.search(r'@import|url\(',soup.style.string)
    review=load('hw6_visual_review.json')
    assert review['reviewed_report_sha256']==digest(OUT/'hw6_report.html')
    for link in soup.select('a[download]'):
        content=base64.b64decode(link['href'].split(',',1)[1])
        if link['download'] in ('a_collapsed_appendix.html','b_covered_freeze.pdf'):
            assert content==(ROOT/'data/my_attacks'/link['download']).read_bytes()
        else:
            assert json.loads(content)['exam_results']==exam
    # Scan the exact Git staging list, not the virtual environment or parent secret file.
    staged=subprocess.run(['git','ls-files','--cached','-z'],cwd=ROOT,capture_output=True,check=True).stdout.decode('utf-8').split('\0')
    staged=[p for p in staged if p]
    assert staged and all(name in staged for name in required+data_paths)
    assert not any('.venv' in Path(p).parts or '__pycache__' in Path(p).parts or (Path(p).name.startswith('.env') and Path(p).name!='.env.example') for p in staged)
    index_entries=subprocess.run(['git','ls-files','--stage','-z'],cwd=ROOT,capture_output=True,check=True).stdout.decode('utf-8').split('\0')
    for entry in filter(None,index_entries):
        metadata,name=entry.split('\t',1)
        content=(ROOT/name).read_bytes()
        blob=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
        assert metadata.split()[1]==blob, ('Git index changes file bytes',name)
    known=[v.encode('utf-8') for k,v in dotenv_values(ROOT.parent/'.env').items() if v and len(v)>15 and re.search('key|token|secret|password',k,re.I)]
    patterns=[rb'gh[pousr]_[A-Za-z0-9]{30,}',rb'github_pat_[A-Za-z0-9_]{30,}',rb'AKIA[0-9A-Z]{16}',rb'sk-(?:proj-)?[A-Za-z0-9_-]{30,}']
    findings=[]
    for name in staged:
        content=(ROOT/name).read_bytes()
        chunks=[content]
        if name.endswith('.html'):
            for encoded in re.findall(rb'data:[^"\s;]+;base64,([A-Za-z0-9+/=]+)',content):
                chunks.append(base64.b64decode(encoded))
        if any(secret in chunk for secret in known for chunk in chunks): findings.append({'file':name,'reason':'matches a configured secret value'})
        if any(re.search(pattern,chunk) for pattern in patterns for chunk in chunks): findings.append({'file':name,'reason':'credential-shaped token'})
    assert not findings, 'Potential secrets found; see filenames only, do not publish'
    limitations=['Checks cover the user-specified layout, not a complete independently supplied grading rubric.',
                 'Run/audit/API-usage records agree internally; provider invoices and routing are not independently verified.',
                 'Exam accuracy remains unknown; no exam key was consulted.',
                 'Visibility heuristics, quote parsing, OCR/attachments, and vendor authentication have documented limits.',
                 'The repaired baseline batch adapter was tested offline only; submission preparation made no new model API calls.',
                 'GitHub publication and anonymous remote-file verification must complete before final submission.']
    result={'layout':'passed','data_file_counts':counts,'data_files':data_paths,'required_paths':required,'staged_file_count':len(staged),'git_index_preserves_exact_bytes':True,
            'verified_returned_api_calls_by_study':checked,'snapshots':snapshots,'final_agent_matches_exam_freeze':True,
            'offline_report':'self-contained structure and embedded bytes verified; user reviewed this hash in Edge',
            'report_sha256':digest(OUT/'hw6_report.html'),'secret_scan':{'configured_secret_matches':0,'credential_pattern_matches':0,'ignored_secrets_and_envs':True},
            'limits':limitations,'repository_url':'https://github.com/DanielKim-94/HW6','publication':'pending push and public verification'}
    (OUT/'submission_checks.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    text=f'''# Problem 10 - Submission checks

Checks passed for the user-requested layout: agent files, prompt, requirements, AI prompt record, documentation, required outputs, and the complete data folder ({counts['practice_docs']} practice, {counts['exam_docs']} exam, {counts['my_attacks']} original attack documents, plus handbook/prices/practice key).

Recorded final outputs and selected API usage were matched to run-specific final_answer, request and response audit events. Counts of verified returned model-call records: {json.dumps(checked)}. Costs were recalculated using supplied rates. Failed attempts are retained, not substituted for complete answers. This establishes internal evidence consistency, not independent provider invoice verification or exam correctness.

All baseline, defended, and frozen-exam manifest hashes are unchanged. The final agent/prompt files still match the exam freeze. Only the external Problem 5 reproduction adapter was fixed to load the preserved prompt; its offline load check passed. No new model experiments were run while preparing submission.

The offline report has no external dependencies; embedded attack originals and exam evidence match their source bytes. The user reviewed report SHA-256 `{result['report_sha256']}` in Edge and confirmed readable chart labels/tables and a recommendation reflecting their view. That observation is user-reported evidence, recorded separately in hw6_visual_review.json.

The staged public files were scanned for exact configured secret values and common credential-token patterns, including decoded HTML data assets. No matches were found. Real environment files, virtual environments, caches and credential-file patterns are excluded; .env.example contains only a placeholder. This is a scoped scan, not a guarantee against every conceivable secret format.

## Remaining limitations

'''+''.join('- '+item+'\n' for item in limitations)+'''
## Publication

Authorized repository: https://github.com/DanielKim-94/HW6. Push and anonymous verification are pending. The user will submit the verified repository URL to Canvas themselves.
'''
    (OUT/'submission_checks.md').write_text(text,encoding='utf-8')
    print(json.dumps({'layout':'passed','counts':counts,'verified_calls':checked,'secret_matches':0,'staged_files':len(staged)}))

if __name__=='__main__':
    main()
