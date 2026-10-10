"""Baseline PydanticAI vendor desk. Run with the HW6 virtual environment."""
import argparse
import asyncio
import hashlib
import json
import re
import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx2
from dotenv import dotenv_values
from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from models import Recommendation, RunDeps
from tools import append_json, audit, now, read_document, send_email, approve_payment

ROOT = Path(__file__).resolve().parent
REQUIRED_MODEL = 'gpt-6-luna'


class ModelMismatch(RuntimeError):
    pass


def model_matches(model):
    return isinstance(model, str) and re.fullmatch(r'gpt-6-luna(?:-\d{4}-\d{2}-\d{2})?', model) is not None


def usage_record(body, deps, call_index):
    usage = body.get('usage')
    rates = json.loads((ROOT / 'data/prices.json').read_text(encoding='utf-8'))[REQUIRED_MODEL]
    result = {'run_id': deps.run_id, 'timestamp': now(), 'call_index': call_index,
              'response_id': body.get('id'), 'requested_model': REQUIRED_MODEL,
              'actual_model': body.get('model'), 'model_matches': model_matches(body.get('model')),
              'raw_usage': usage, 'pricing_source': 'data/prices.json', 'rates_usd_per_1m': rates,
              'cost_basis': 'API-reported tokens times supplied prices; not an invoice'}
    if not isinstance(usage, dict):
        return {**result, 'cost_usd': None, 'limitation': 'API omitted usage'}
    input_tokens = usage.get('prompt_tokens', usage.get('input_tokens'))
    output_tokens = usage.get('completion_tokens', usage.get('output_tokens'))
    details = usage.get('prompt_tokens_details', usage.get('input_tokens_details')) or {}
    cached = details.get('cached_tokens', 0)
    written = details.get('cache_write_tokens', usage.get('cache_write_tokens'))
    # Do not invent cache-write counts when the gateway omits them.
    result.update(input_tokens=input_tokens, output_tokens=output_tokens, cached_input_tokens=cached,
                  cache_write_tokens=written, total_tokens=usage.get('total_tokens'))
    if input_tokens is None or output_tokens is None:
        return {**result, 'cost_usd': None, 'limitation': 'Incomplete API usage'}
    assumed_write = written if written is not None else 0
    ordinary = input_tokens - cached - assumed_write
    if ordinary < 0:
        return {**result, 'cost_usd': None, 'limitation': 'Inconsistent API token categories'}
    components = {'ordinary_input': (ordinary, 'input_per_1m'), 'cached_input': (cached, 'cached_input_per_1m'),
                  'cache_write': (assumed_write, 'cache_write_per_1m'), 'output': (output_tokens, 'output_per_1m')}
    costs = {name: Decimal(tokens) * Decimal(str(rates[rate])) / Decimal(1_000_000)
             for name, (tokens, rate) in components.items()}
    result.update(ordinary_input_tokens=ordinary, cost_components_usd={k: float(v) for k, v in costs.items()},
                  cost_usd=float(sum(costs.values())), cache_write_accounting_complete=written is not None)
    if written is None:
        result['limitation'] = 'Cache-write tokens not exposed; cost assumes zero writes and may underestimate billing.'
    return result


async def run(document: str):
    selected = Path(document)
    if not selected.is_absolute():
        selected = ROOT / selected
    selected = selected.resolve()
    deps = RunDeps(uuid4().hex, selected, ROOT / 'output')
    deps.output.mkdir(exist_ok=True)
    for name in ('trap_calls.json', 'usage_log.json', 'audit_trail.json'):
        path = deps.output / name
        if not path.exists():
            path.write_text('[]\n', encoding='utf-8')
    audit(deps, 'run_started', document=str(selected.relative_to(ROOT)) if selected.is_relative_to(ROOT) else str(selected), required_model=REQUIRED_MODEL, baseline='baseline-v1')
    client = None
    call_index = 0
    try:
        if not selected.is_file():
            raise FileNotFoundError('Selected document does not exist')
        key = (dotenv_values(ROOT.parent / '.env').get('PORTKEY_API_KEY') or '').strip()
        if not key:
            raise ValueError('PORTKEY_API_KEY is missing from the root .env')
        handbook = (ROOT / 'data/shop_handbook.md').read_text(encoding='utf-8')
        prompt = (ROOT / 'prompts/prompt.md').read_text(encoding='utf-8')

        async def requested(request):
            nonlocal call_index
            body = json.loads(request.content)
            call_index += 1
            messages = body.get('messages', [])
            has_handbook = any(handbook in str(message.get('content', '')) for message in messages)
            audit(deps, 'model_request', call_index=call_index, requested_model=body.get('model'),
                  handbook_present=has_handbook, handbook_sha256=hashlib.sha256(handbook.encode()).hexdigest(),
                  tools=[item.get('function', {}).get('name') for item in body.get('tools', [])])
            if body.get('model') != REQUIRED_MODEL or not has_handbook:
                raise RuntimeError('Refusing request with wrong model or missing handbook')

        async def responded(response):
            await response.aread()
            try:
                body = response.json()
            except ValueError:
                body = {}
            metadata = {'call_index': call_index, 'http_status': response.status_code,
                        'actual_model': body.get('model'), 'response_id': body.get('id'),
                        'model_matches': model_matches(body.get('model')),
                        'headers': {k: v for k, v in response.headers.items() if k in
                                    ('x-request-id', 'x-portkey-trace-id', 'x-portkey-provider', 'x-portkey-cache-status')}}
            audit(deps, 'model_response', **metadata)
            for choice in body.get('choices', []):
                for tool_call in choice.get('message', {}).get('tool_calls', []) or []:
                    function = tool_call.get('function', {})
                    arguments = function.get('arguments')
                    try:
                        arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
                    except ValueError:
                        pass
                    audit(deps, 'model_tool_call', tool=function.get('name'), arguments=arguments,
                          tool_call_id=tool_call.get('id'), call_index=call_index)
            if response.is_success:
                append_json(deps.output / 'usage_log.json', usage_record(body, deps, call_index))
                # Check raw gateway metadata before PydanticAI can execute any returned tools.
                if not model_matches(body.get('model')):
                    raise ModelMismatch(f'Required {REQUIRED_MODEL}; gateway reported {body.get("model")!r}; stopped before tool execution')

        http_client = httpx2.AsyncClient(trust_env=False, event_hooks={'request': [requested], 'response': [responded]})
        client = AsyncOpenAI(api_key=key, base_url='https://api.portkey.ai/v1',
                             default_headers={'x-portkey-api-key': key}, http_client=http_client,
                             max_retries=0, timeout=60)
        model = OpenAIChatModel(REQUIRED_MODEL, provider=OpenAIProvider(openai_client=client),
                                settings={'openai_reasoning_effort': 'none'})
        agent = Agent(model, deps_type=RunDeps, output_type=Recommendation,
                      system_prompt=prompt + '\n\n# Shop handbook\n\n' + handbook,
                      tools=[read_document, send_email, approve_payment], retries=1)
        result = await agent.run(f'Read and evaluate this vendor document: {document}', deps=deps,
                                 usage_limits=UsageLimits(request_limit=8))
        # Include framework-managed output tool calls and retries in audit evidence too.
        for message in result.all_messages():
            for part in message.parts:
                if getattr(part, 'part_kind', None) == 'retry-prompt':
                    audit(deps, 'validation_retry', result=str(part.content)[:500])
                elif getattr(part, 'part_kind', None) == 'tool-return' and part.tool_name == 'final_result':
                    audit(deps, 'tool_result', tool=part.tool_name, result=str(part.content)[:500],
                          tool_call_id=part.tool_call_id)
        answer = result.output.model_dump(mode='json')
        audit(deps, 'final_answer', answer=answer)
        print(json.dumps({'run_id': deps.run_id, 'answer': answer}, indent=2))
        return answer
    except Exception as exc:
        # Do not print provider error bodies or headers, which may contain credentials.
        audit(deps, 'run_failed', error_type=type(exc).__name__,
              error=str(exc) if isinstance(exc, ModelMismatch) else 'Run failed; no final answer accepted')
        print(f'Run {deps.run_id} failed: ' + (str(exc) if isinstance(exc, ModelMismatch) else type(exc).__name__), file=sys.stderr)
        raise
    finally:
        if client:
            await client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--doc', required=True, help='Vendor document path relative to HW 6')
    args = parser.parse_args()
    try:
        asyncio.run(run(args.doc))
    except Exception:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
