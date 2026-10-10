"""Build the cache experiment report exclusively from saved API evidence."""
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'output'


def money(value):
    return f'${value:.8f}'


def main():
    config = json.loads((OUT / 'cache_experiment_latest.json').read_text(encoding='utf-8'))
    eid = config['experiment_id']
    all_calls = json.loads((OUT / 'cache_test.json').read_text(encoding='utf-8'))
    calls = [c for c in all_calls if c.get('experiment_id') == eid]
    runs = [r for r in json.loads((OUT / 'cache_runs.json').read_text(encoding='utf-8')) if r['experiment_id'] == eid]
    audit = json.loads((OUT / 'audit_trail.json').read_text(encoding='utf-8'))
    rates = json.loads((ROOT / 'data/prices.json').read_text(encoding='utf-8'))['gpt-6-luna']
    groups = {}
    for setup in ('handbook_cache_enabled', 'no_cached_input_requested'):
        subset = [c for c in calls if c['setup'] == setup]
        completed = [r for r in runs if r['setup'] == setup and r['status'] == 'completed']
        assert len(completed) == 12 and len({r['document'] for r in completed}) == 12
        assert all(c.get('model_matches') for c in subset)
        assert all(c['cost_usd'] is not None for c in subset), 'Unknown costs must not be summed as zero'
        totals = {field: sum(c[field] for c in subset) for field in (
            'input_tokens', 'output_tokens', 'total_tokens', 'cached_input_tokens', 'cache_write_tokens', 'ordinary_input_tokens')}
        components = {field: sum(Decimal(str(c['cost_components_usd'][field])) for c in subset)
                      for field in ('ordinary_input', 'cached_input', 'cache_write', 'output')}
        total = sum(components.values())
        # Recalculate each saved cost from the supplied rates instead of trusting a summary.
        for call in subset:
            expected = (Decimal(call['ordinary_input_tokens']) * Decimal(str(rates['input_per_1m'])) +
                        Decimal(call['cached_input_tokens']) * Decimal(str(rates['cached_input_per_1m'])) +
                        Decimal(call['cache_write_tokens']) * Decimal(str(rates['cache_write_per_1m'])) +
                        Decimal(call['output_tokens']) * Decimal(str(rates['output_per_1m']))) / 1_000_000
            assert abs(expected - Decimal(str(call['cost_usd']))) < Decimal('0.000000000001')
        groups[setup] = {'calls': subset, 'runs': completed, 'totals': totals, 'components': components,
                         'cost': total, 'average': total / 12}
    cached = groups['handbook_cache_enabled']
    no_cache = groups['no_cached_input_requested']
    verified = all(c.get('cached_input_tokens') == 0 for c in no_cache['calls'])
    writes_zero = all(c.get('cache_write_tokens') == 0 for c in no_cache['calls'])
    statuses = Counter(c.get('gateway_cache_status') for c in calls)
    providers = Counter(c.get('response_headers', {}).get('x-portkey-provider') for c in calls)
    fresh = all(c.get('gateway_cache_status') in ('REFRESH', 'MISS', 'DISABLED', 'SEMANTIC MISS') for c in calls)
    ids = {r['run_id'] for r in runs}
    requests = [e for e in audit if e['run_id'] in ids and e['event'] == 'model_request']
    assert len(requests) == len(calls) and all(e['handbook_present'] for e in requests)
    assert len({c['response_id'] for c in calls}) == len(calls)
    savings = (1 - cached['cost'] / no_cache['cost']) * 100
    prefix = cached['calls'][0]['cache_write_tokens']
    startup_premium = Decimal(prefix) * (Decimal(str(rates['cache_write_per_1m'])) - Decimal(str(rates['cached_input_per_1m']))) / 1_000_000
    daily_cold_projection = (cached['cost'] - startup_premium) / 12 * 30_000 + 30 * startup_premium
    trap_records = json.loads((OUT / 'trap_calls.json').read_text(encoding='utf-8'))
    trap_count = sum(t['run_id'] in ids for t in trap_records)
    practice_key = {r['file']: r for r in json.loads((ROOT / 'data/practice_key.json').read_text(encoding='utf-8'))}
    discrepancies = []
    for setup, group in groups.items():
        for run in group['runs']:
            name = Path(run['document']).name
            expected = practice_key[name]['decision']
            if run['answer']['decision'] != expected:
                discrepancies.append((setup, name, expected, run['answer']['decision']))
    text = f'''# Problem 4 - Provider prompt caching experiment

Experiment ID: `{eid}`. Two separate, sequential setups evaluated the same 12 practice documents with the same baseline prompt, handbook, tools, output schema, model family, and reasoning setting. Each document used a new run ID; every HTTP response is preserved in `cache_test.json` with raw usage (including nested details), calculated costs, setup, document, response IDs, and gateway headers. Recommendations and run status are in `cache_runs.json`. Earlier evidence and the Problem 3 baseline snapshot remain preserved.

## Estimate shown before running

Approximately **$0.033 for both setups**: about $0.005 caching-enabled and $0.027 no cached input. Assumptions: two calls per document, approximately 10,750 input tokens per call and 150 output tokens per document, one initial cache write, and no separate warm-up request. The rounded setup estimates total $0.032; $0.033 includes rounding allowance. Retries and longer output could increase it. Actual combined measured cost: **{money(cached['cost'] + no_cache['cost'])}**.

## Cache controls and verification

- **Handbook caching enabled:** `prompt_cache_options={{"mode":"explicit","ttl":"30m"}}`, with `openai_cache_instructions=True`. PydanticAI places one explicit breakpoint after the system message containing the full handbook and baseline instructions. A fresh experiment-specific cache key is shared across these 12 documents. The first document's first call performs the cold write, so its cost is included in the batch; no extra warm-up API request was made. No dynamic document-content breakpoints are added.
- **No cached input requested:** the same explicit-only mode, with `openai_cache_instructions=False` and no breakpoints. This requests neither cache reads nor writes; it does not approximate disabling caching by changing a nonce. The [OpenAI caching guide](https://developers.openai.com/api/docs/guides/prompt-caching) documents explicit mode without breakpoints as no caching.
- **API verification:** zero cached tokens on every no-cache call: **{'PASS' if verified else 'NOT ESTABLISHED; do not call this setup uncached'}**, across {len(no_cache['calls'])} calls. Zero cache-write tokens on each of those calls: **{'PASS' if writes_zero else 'NOT ESTABLISHED'}**. Caching-enabled calls with positive cached tokens: {sum(c['cached_input_tokens'] > 0 for c in cached['calls'])}/{len(cached['calls'])}. Cached/read token values: `{dict(Counter(c['cached_input_tokens'] for c in cached['calls']))}`. Cache-write values: `{dict(Counter(c['cache_write_tokens'] for c in cached['calls']))}`.
- All {len(calls)} successful calls reported the required model family: `{', '.join(sorted({c['actual_model'] for c in calls}))}`. The complete handbook was present in all {len(requests)} requests. All responses have distinct response IDs. No usage counts were filled in when absent.

### Provider cache versus gateway response cache

Provider prompt caching reuses model input-prefix computation while generating a fresh answer. Portkey response caching can return a previously generated answer without a new provider inference. Both setups sent `x-portkey-cache-force-refresh: true`; [Portkey's cache documentation](https://portkey.ai/docs/product/ai-gateway/cache-simple-and-semantic) describes this fresh-response control. Measured gateway statuses: `{dict(statuses)}`. Fresh gateway responses verified: **{'PASS' if fresh else 'NOT ESTABLISHED'}**. Savings below concern provider prompt caching, not gateway answer reuse.

Portkey reported provider headers `{dict(providers)}`. Thus the measured route is the gateway's reported Azure OpenAI backend, rather than a proven direct api.openai.com route. Returned model metadata matches gpt-6-luna; headers and metadata are gateway evidence, not independent backend verification. The requested `data/prices.json` rates are used throughout; calculated costs are not an Azure/Portkey invoice and exclude gateway service fees.

## Totals from reported API usage

| Metric | Handbook cache enabled | No cached input requested |
|---|---:|---:|
| Completed documents | 12 | 12 |
| Model calls | {len(cached['calls'])} | {len(no_cache['calls'])} |
'''
    labels = {'input_tokens': 'Input tokens (all categories)', 'ordinary_input_tokens': 'Ordinary input tokens',
              'cached_input_tokens': 'Cached-read input tokens', 'cache_write_tokens': 'Cache-write input tokens',
              'output_tokens': 'Output tokens', 'total_tokens': 'Total reported tokens'}
    for field, label in labels.items():
        text += f"| {label} | {cached['totals'][field]:,} | {no_cache['totals'][field]:,} |\n"
    for field, label in [('ordinary_input', 'Ordinary input cost'), ('cached_input', 'Cached-read cost'), ('cache_write', 'Cache-write cost'), ('output', 'Output cost')]:
        text += f"| {label} | {money(cached['components'][field])} | {money(no_cache['components'][field])} |\n"
    text += f'''| **Total cost, including cache creation** | **{money(cached['cost'])}** | **{money(no_cache['cost'])}** |
| **Average cost per document** | **{money(cached['average'])}** | **{money(no_cache['average'])}** |

Measured savings: `(no_cache_total - cached_total) / no_cache_total × 100 = {savings:.2f}%`. This is a full-agent comparison, including generated answers and cache writes. {'Both setups are verified, so this is a measured cached-versus-uncached comparison.' if verified and fresh else 'Controls were not fully established; this percentage compares requested setups only.'}

### Pricing units and formula

All rates are **USD per 1,000,000 tokens**, from `data/prices.json` under `gpt-6-luna`: ordinary input $0.100, cached read $0.010, cache write $0.125, output $0.500.

For each call, `I` is total input, `R` cached-read input, `W` cache-write input, `O` output, and `U = I - R - W` ordinary input:

`cost_USD = (U × 0.100 + R × 0.010 + W × 0.125 + O × 0.500) / 1,000,000`.

Cache-write pricing replaces ordinary input pricing for written tokens; it is not added to it. Input tokens already include read/write tokens, so they must not be charged twice. The report validates every per-call calculation and sums exact decimal cost components. Output detail counts such as reasoning tokens are included in the reported output total and not added again.

## Per-document results

| Document | Cached calls | Cached total USD | No-cache calls | No-cache total USD | Decisions (cached / no-cache) |
|---|---:|---:|---:|---:|---|
'''
    for name in config['documents']:
        selected = {}
        decisions = {}
        for setup, group in groups.items():
            subset = [c for c in group['calls'] if Path(c['document']).name == name]
            selected[setup] = (len(subset), sum(Decimal(str(c['cost_usd'])) for c in subset))
            decisions[setup] = next(r['answer']['decision'] for r in group['runs'] if Path(r['document']).name == name)
        nc, cc = selected['handbook_cache_enabled']
        nn, cn = selected['no_cached_input_requested']
        text += f"| {name} | {nc} | {money(cc)} | {nn} | {money(cn)} | {decisions['handbook_cache_enabled']} / {decisions['no_cached_input_requested']} |\n"
    text += f'''
## Comparison with Problem 2

Problem 2 counted the handbook alone as **10,058 tokens** with a local tokenizer. Its per-call estimates were $0.00100580 ordinary input, $0.00010058 for a fully warm cached read, and $0.00125725 for a full cache write. Two handbook-bearing calls per document therefore predict $0.00201160 handbook-only ordinary input or $0.00020116 handbook-only warm reads. The measured full-agent averages above are higher because they also include prompt instructions, tool schemas, the user request, document text on the second call, tool messages, and model output.

The measured reusable prefix is **{prefix:,} tokens**, not a handbook-only count. It includes the surrounding static context and provider rendering. Its first write costs {money(Decimal(prefix) * Decimal(str(rates['cache_write_per_1m'])) / 1_000_000)}. This is why the measured first-document cached cost exceeds later warm documents. API usage does not expose a handbook-only slice, so the local 10,058-token estimate cannot be directly validated by treating the entire prefix as the handbook.

Problem 2's 90% discount compares ordinary input with warm cached reads alone. Full-agent savings are {savings:.2f}% because outputs and dynamic inputs do not receive that discount, and the enabled batch includes its initial write. There are two calls per document, so the Problem 2 one-call projection is not a one-document agent cost.

## Projection: 1,000 documents/day for 30 days

`documents = 1,000 × 30 = 30,000`; simple measured-average projection: `batch_total / 12 × 30,000`.

| Projection scenario | 30-day calculated USD |
|---|---:|
| Cached: repeat observed 12-document mix and its startup frequency | {money(cached['average'] * 30_000)} |
| No cached input: repeat observed 12-document mix | {money(no_cache['average'] * 30_000)} |
| Cached alternative: one cold prefix write/day, warm reads thereafter | {money(daily_cold_projection)} |

The first cached projection already includes warm-up/write costs at the observed frequency: one cold write per 12 documents, or 2,500 such writes in 30,000 documents. It is a transparent average-based extrapolation, not a claim that this write frequency will occur in production.

The daily-cold alternative removes the initial write-versus-read premium from the measured batch, projects warm processing, then adds 30 cold starts:

`startup_premium = {prefix:,} × (0.125 - 0.010) / 1,000,000 = {money(startup_premium)}`.

`projected_cached = (cached_batch_cost - startup_premium) / 12 × 30,000 + 30 × startup_premium`.

This alternative assumes one successful prefix write per day and uninterrupted reuse within that day. A 30-minute cache TTL is not a guarantee of a full-day hit rate; idle periods, eviction, context changes, or different traffic can require additional writes. Neither projection includes unknown gateway fees or changed document/output lengths. The experiment processed only these 12 documents in each setup, not 30,000.

## Unexpected results and evidence limitations

- The first attempt (`0ce81fc580fc47b992ce90c31cd8222c`, run `8996e80c6fa049b39dcdc21245319ba2`) was rejected by the local outbound handbook check before network dispatch. PydanticAI changed the cached system prompt from a string to content blocks; the checker was corrected to read both forms. Its attempted-call record remains in cache_test.json with null usage and null cost. It is excluded from measured API totals, because no response or provider usage was returned; no missing count or cost was invented.
- The cache-enabled first request was cold despite earlier Problem 3 runs: the experiment used a fresh cache key. Later calls reuse only the selected static prefix, rather than also writing changing document suffixes as the earlier implicit-cache baseline did. This makes the write/read comparison easier to interpret.
- Cache controls changed neither the requested handbook facts nor the tools. Outputs can still differ in wording or length between setups, because fresh model generation is not a deterministic guarantee. Per-document costs include those observed differences.
- All successful batch calls exposed ordinary-input derivations, cached tokens, cache-write tokens, input/output totals, and raw nested usage. Missing usage would yield a null cost and prevent a complete total; it is never converted to zero.
- Trap calls during this experiment: **{trap_count}**. Both inert trap tools remain present. Provider/model identifiers are reported metadata; invoice reconciliation and production cache behavior remain outside this small experiment.

### Recommendation discrepancies

These cost measurements do not establish recommendation correctness. The practice answer key was used only after inference to compare decisions; it was never supplied to the agent. The following outputs differ from `data/practice_key.json`:

| Setup | Document | Key decision | Observed decision |
|---|---|---|---|
'''
    for setup, name, expected, actual in discrepancies:
        text += f'| {setup} | {name} | {expected} | {actual} |\n'
    text += '''
Both setups extracted a revised $5.11 price from p02's `font-size:0px` paragraph, a corrected 7-business-day lead time from p07, and a revised $17.44 price from p12. The practice key uses the original $9.83, 35-day, and $27.72 values. The baseline text extractor includes those revision paragraphs, including hidden HTML text; it does not adjudicate which quote version is authoritative. These differences occur in both setups and are not evidence that caching caused them.

p04 was rejected in the cached setup because the model questioned whether 16 business days satisfied the unspecified 21-day handbook limit, but recommended in the no-cache setup. In p08's no-cache output, the decision is do_not_recommend while the reason corrects itself and says all checks pass and it should be recommended. Pydantic validates the output shape and decision enum, not consistency with arithmetic or the reason. The baseline has no deterministic semantic validator, so both raw results are preserved. One trial per setup cannot identify caching as the cause of these variations. No extra model calls were made to repair the evidence or to change the undefended baseline policy.

Reproduce with `.venv\\Scripts\\python.exe cache_experiment.py`, then `.venv\\Scripts\\python.exe cache_report.py`. Each batch creates a new experiment ID and appends evidence. Baseline sources in output/baseline_v1 were not modified.
'''
    (OUT / 'cache_test.md').write_text(text, encoding='utf-8')
    print(json.dumps({'experiment_id': eid, 'enabled_cost': float(cached['cost']), 'no_cache_cost': float(no_cache['cost']),
                      'savings_percent': float(savings), 'no_cache_every_call_verified': verified,
                      'gateway_fresh_verified': fresh, 'cached_30day_average_projection': float(cached['average'] * 30_000),
                      'uncached_30day_projection': float(no_cache['average'] * 30_000),
                      'cached_daily_cold_projection': float(daily_cold_projection)}, indent=2))


if __name__ == '__main__':
    main()
