"""Verify exported answers against run evidence and report usage without grading."""
import hashlib
import json
from decimal import Decimal
from pathlib import Path

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output'
def load(name):
    return json.loads((OUT/name).read_text(encoding='utf-8'))

def main():
    metadata=load('exam_experiment.json')
    eid=metadata['experiment_id']
    results=load('exam_results.json')
    attempts=[r for r in load('exam_attempts.json') if r['experiment_id']==eid]
    completed={r['file']:r for r in attempts if r['status']=='completed'}
    failed=[r for r in attempts if r['status']!='completed']
    frozen=OUT/'exam_frozen_v1'
    manifest=json.loads((frozen/'manifest.json').read_text(encoding='utf-8'))
    assert len(results)==10 and {r['file'] for r in results}==set(metadata['files'])
    assert hashlib.sha256((OUT/'exam_results.json').read_bytes()).hexdigest()==metadata['results_sha256']
    for name,digest in manifest['sha256'].items():
        assert hashlib.sha256((frozen/name).read_bytes()).hexdigest()==digest
        if name.startswith('data/exam_docs/'):
            assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
    audit=load('audit_trail.json')
    required={'file','vendor','sku','unit_price','lead_time_days','min_order','decision','reason',
              'trap_tool_called','input_tokens','cached_tokens','output_tokens','cost_usd'}
    for result in results:
        assert set(result)==required
        attempt=completed.get(result['file'])
        if attempt:
            assert result==attempt['exam_entry']
            final=next(r['answer'] for r in audit if r['run_id']==attempt['run_id'] and r['event']=='final_answer')
            assert all(result[k]==final[k] for k in ('vendor','sku','unit_price','lead_time_days','decision','reason'))
            assert result['min_order']==final['minimum_order']
            assert attempt['handbook_on_every_call']
            assert all(r['model_matches'] for r in attempt['model_responses'])
    selected=[completed[name] for name in metadata['files'] if name in completed]
    measured_cost=sum(Decimal(str(r['cost_usd'])) for r in results) if all(r['cost_usd'] is not None for r in results) else None
    actual_models=sorted({c['actual_model'] for a in selected for c in a['api_usage']})
    text=f'''# Problem 8 - Frozen defended exam evaluation

**{len(completed)}/10 documents produced accepted final agent answers. These answers are ungraded and not described as correct.** No answer key was searched for or read. No exam document content was inspected to tune the agent. All exported fields are copied from the frozen defended agent's recorded final returns, with only `minimum_order` renamed to `min_order`. They are not manually corrected after inference.

## Freeze and execution

Before the first model call, output/exam_frozen_v1 preserved agent.py, tools.py, models.py, document_processing.py, purchasing_policy.py, prompts/prompt.md, the handbook, pricing, all ten exam originals, the runner, orchestration source, and installed package versions. manifest.json records SHA-256 values and the configuration. All frozen hashes verified unchanged after execution. Original exams were copied without interpreting their content.

Configuration: defended mode; gpt-6-luna through Portkey using the existing root .env key; reasoning effort none; no trusted side-effect authorizations; full handbook every call; model-family guard; eight-call request limit; one framework retry; zero SDK retries. Normal provider caching was retained; no new cache setup or gateway refresh was introduced for this evaluation. Credential contents are not copied to the snapshot or reports. The model alias and remote provider are not made immutable by a local source freeze; returned metadata is recorded separately.

The frozen in-run purchasing coordinator remains part of the final defended agent. Its deterministic checks and canonical reason run before final_answer is emitted, exactly as in Problems 6 and 7. **The exam export uses this actual pipeline output**, not a newly edited raw model response. Raw model outputs and coordinator events are preserved in exam_attempts.json and audit_trail.json for comparison. No defenses, parser rules, prompts, or purchasing policy were adjusted after seeing exam outputs.

Experiment ID: `{eid}`. Returned model names: {', '.join(actual_models)}. Every accepted response passed the required-family guard, and every recorded model request contained the full handbook. These are gateway-reported identities, not independent routing verification.

The external launcher needed a path-only recovery: the initial invocation ran the runner from its archive, where it resolved an incorrect workspace path. It failed before a unique audit run or API invocation and produced no answer. The recovery invoked the byte-identical workspace runner, which loads the frozen agent, redirects output logs and credential lookup to the workspace, and uses frozen exam documents. The frozen agent and archive were not modified. The original orchestration archive is retained; the corrected external launcher is separately hashed in exam_export_verification.json.

e09 then failed twice because the returned read_document argument changed characters in the non-English absolute workspace path. The reader's existing selected-document check stopped both attempts, with no accepted final answer. The second attempt was a gateway response-cache HIT replaying the same response ID and malformed argument. The third, complete rerun passed the same frozen document using the equivalent relative CLI reference `data/exam_docs/e09_email.eml`. Only the pathname representation supplied by the external adapter changed; the frozen source, system prompt, handbook, document bytes, settings, access check, and purchasing coordinator remained unchanged. The relative adapter is separately hashed; this invocation difference is disclosed rather than treated as an identical request body.

## Attempts and run references

The launch failure is retained in exam_attempts.json, separate from e01's subsequent complete attempt. Each exam file has one selected complete run; e09 also has two failed runs. Framework tool follow-ups or validation retries within one run are aggregated; they are not mislabeled as complete document reruns. Failed-attempt usage remains attached to that attempt rather than silently folded into the successful answer. There were {len(failed)} failed attempt records, including the pre-API launch failure. Earlier incomplete exam_results exports are preserved under the export_history filenames in exam_experiment.json; accepted answers for the other nine files stayed unchanged during e09 reruns.

| File | Completed attempt | Run ID | Calls | Decision (unverified) | Trap executed | Blocked trap attempts |
|---|---:|---|---:|---|---|---:|
'''
    for result in results:
        a=completed.get(result['file'])
        if a:
            text+=f"| {result['file']} | {a['attempt']} | {a['run_id']} | {len(a['api_usage'])} | {result['decision']} | {result['trap_tool_called']} | {len(a['blocked_trap_calls'])} |\n"
        else:
            text+=f"| {result['file']} | none | none | unavailable | no accepted answer | {result['trap_tool_called']} | unavailable |\n"
    text+='\nFailed records:\n\n'
    for failure in failed:
        text+=f"- {failure['file']}, attempt {failure['attempt']}: {failure['status']}; exit code {failure['exit_code']}; run ID {failure.get('run_id','not created')}. No accepted final answer is scored or substituted for this attempt.\n"
        if failure.get('api_usage'):
            subtotal=sum(Decimal(str(c['cost_usd'])) for c in failure['api_usage']) if all(c.get('cost_usd') is not None for c in failure['api_usage']) else None
            statuses=[r.get('headers',{}).get('x-portkey-cache-status') for r in failure.get('model_responses',[])]
            text+=f"  Returned response usage: {len(failure['api_usage'])} call record(s), supplied-rate estimate ${subtotal}; gateway statuses {statuses}. For a HIT, this is replayed historical response usage, not proof of fresh provider inference or incremental billing. It is retained separately from the selected run.\n"
    text+='''
## Actual usage and cost accounting

Each document's input_tokens, cached_tokens, and output_tokens sum the corresponding API-reported categories across **all successful HTTP model responses in that selected run**, including tool follow-ups and any framework retry. Each per-call cost is computed first and then summed for the document. Failed HTTP attempts without usage are recorded in audit evidence; no token count is guessed. A missing category makes the corresponding aggregate or exact cost null rather than an invented zero.

`cached_tokens` means provider cached-read input tokens. It is a **subset of input_tokens**, not extra tokens to add to input. The reported cache-write category is also a subset of input in this gateway's accounting and is retained in exam_attempts.json because the requested results schema has no write field. With per-call values I=input, C=cached reads, W=cache writes, O=output, ordinary input is I-C-W. The calculation is:

```text
ordinary_input = I - C - W
cost_usd = ((I-C-W)*0.10 + C*0.01 + W*0.125 + O*0.50) / 1,000,000
document_cost = sum(cost_usd for each reported model call in the selected run)
```

Prices are supplied USD per million tokens from the frozen data/prices.json. Charging all I at the ordinary rate and adding C again would double-count cached reads; charging write tokens at both ordinary and write rates would likewise double-count writes. The API total category is separately retained as returned; it is not substituted for input. Provider prompt caching and gateway response caching are distinct; gateway response headers are preserved in audit model_response events. These costs are supplied-rate estimates, not an invoice or a claim about gateway fees.

| File | Input | Cached reads (within input) | Cache writes (within input) | Output | Calculated USD |
|---|---:|---:|---:|---:|---:|
'''
    for result in results:
        a=completed.get(result['file'])
        text+=f"| {result['file']} | {result['input_tokens']} | {result['cached_tokens']} | {a['cache_write_tokens'] if a else 'unavailable'} | {result['output_tokens']} | {result['cost_usd']} |\n"
    text+=f'''
Total selected-run calculated cost: **{'$'+str(measured_cost) if measured_cost is not None else 'unavailable: one or more costs are missing'}**. The pre-API launch failure has no usage record and no accepted output; it is not fabricated as an API response with zero tokens.

## Preservation and limitations

exam_results.json contains exactly one entry per exam file and the requested thirteen fields. The final artifact was verified against its SHA-256 and recorded final_answer audit events. Incomplete earlier exports were archived before failed-document reruns, and accepted answers were never changed. exam_attempts.json retains attempts, run IDs, raw answers, final pipeline answers, per-call usage, cache writes, model metadata, trap calls, and in-run coordinator events. audit_trail.json, usage_log.json, and processing_log.json retain earlier assignment evidence and these exam runs; records are attributed by run ID.

No correctness score is reported because no ground truth was consulted. Missing facts, rejections, or model/coordinator disagreements are preserved rather than repaired. Rendering heuristics and anchored field parsing have the limitations documented in the Problem 6 report. Local freezing preserves implementation and evidence; it cannot establish the truth of vendor claims or guarantee unseen-attack resistance.
'''
    (OUT/'exam_results.md').write_text(text,encoding='utf-8')
    verification={'experiment_id':eid,'results_sha256':metadata['results_sha256'],
                  'frozen_manifest_sha256':metadata['frozen_manifest_sha256'],'frozen_unchanged':True,
                  'answers_match_final_audit_events':True,'completed_documents':len(completed),
                  'failed_attempts':len(failed),'correctness':'not evaluated; no key consulted',
                  'external_orchestrator_sha256':hashlib.sha256((ROOT/'exam_experiment.py').read_bytes()).hexdigest(),
                  'relative_runner_sha256':hashlib.sha256((ROOT/'exam_relative_runner.py').read_bytes()).hexdigest(),
                  'rerun_orchestrator_sha256':hashlib.sha256((ROOT/'exam_rerun_failed.py').read_bytes()).hexdigest(),
                  'workspace_runner_matches_frozen':hashlib.sha256((ROOT/'exam_frozen_runner.py').read_bytes()).hexdigest()==manifest['sha256']['exam_frozen_runner.py'],
                  'total_cost_usd':float(measured_cost) if measured_cost is not None else None}
    (OUT/'exam_export_verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
    print(json.dumps(verification))

if __name__=='__main__':
    main()
