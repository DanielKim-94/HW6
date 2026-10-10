"""Sequential, two-setup practice document experiment; preserves earlier evidence."""
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import agent


async def main():
    experiment_id = uuid4().hex
    documents = sorted((agent.ROOT / 'data/practice_docs').iterdir())
    documents = [p for p in documents if p.suffix in ('.html', '.pdf', '.eml')]
    if len(documents) != 12:
        raise ValueError('Expected exactly 12 practice documents')
    (agent.ROOT / 'output/cache_experiment_latest.json').write_text(json.dumps({
        'experiment_id': experiment_id, 'preflight_estimate_usd': 0.033,
        'estimated_enabled_usd': 0.005, 'estimated_no_cache_usd': 0.027,
        'assumptions': 'Two calls/document; roughly 10,750 input tokens/call and 150 output tokens/document; one initial cache write; no extra warm-up request.',
        'documents': [p.name for p in documents]}, indent=2), encoding='utf-8')
    print(f'Experiment {experiment_id}; preflight estimate about $0.033 for both setups.', flush=True)
    for setup in ('handbook_cache_enabled', 'no_cached_input_requested'):
        print(f'=== SETUP: {setup} ===', flush=True)
        for index, document in enumerate(documents, 1):
            relative = document.relative_to(agent.ROOT).as_posix()
            await agent.run(relative, setup=setup, experiment_id=experiment_id, quiet=True, mode='control_baseline')
            records = json.loads((agent.ROOT / 'output/cache_test.json').read_text(encoding='utf-8'))
            calls = [c for c in records if c.get('experiment_id') == experiment_id and c.get('setup') == setup and c.get('document') == relative]
            cached = [c.get('cached_input_tokens') for c in calls]
            costs = [c.get('cost_usd') for c in calls]
            total = sum(costs) if all(c is not None for c in costs) else None
            print(f'{index}/12 {document.name}: {len(calls)} calls; cached={cached}; cost={total}', flush=True)
            if setup == 'no_cached_input_requested' and any(count != 0 for count in cached):
                print('LIMITATION: zero cached tokens not established; remaining runs retain requested-setup label.', flush=True)
    print('Batch complete; generate report from saved measurements.', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
