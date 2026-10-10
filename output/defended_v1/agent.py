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
from pydantic_ai import Agent, Tool
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from models import Recommendation, RunDeps
from tools import append_json, audit, now, read_document, send_email, approve_payment, prepare_side_effect

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
    cached = details.get('cached_tokens')
    written = details.get('cache_write_tokens', usage.get('cache_write_tokens'))
    # Do not invent cache-write counts when the gateway omits them.
    result.update(input_tokens=input_tokens, output_tokens=output_tokens, cached_input_tokens=cached,
                  cache_write_tokens=written, total_tokens=usage.get('total_tokens'))
    if input_tokens is None or output_tokens is None or cached is None:
        return {**result, 'cost_usd': None, 'limitation': 'Incomplete API usage'}
    if written is None:
        return {**result, 'cost_usd': None, 'cache_write_accounting_complete': False,
                'limitation': 'Cache-write tokens not exposed; exact cost cannot be calculated without inventing a count.'}
    ordinary = input_tokens - cached - written
    if ordinary < 0:
        return {**result, 'cost_usd': None, 'limitation': 'Inconsistent API token categories'}
    components = {'ordinary_input': (ordinary, 'input_per_1m'), 'cached_input': (cached, 'cached_input_per_1m'),
                  'cache_write': (written, 'cache_write_per_1m'), 'output': (output_tokens, 'output_per_1m')}
    costs = {name: Decimal(tokens) * Decimal(str(rates[rate])) / Decimal(1_000_000)
             for name, (tokens, rate) in components.items()}
    result.update(ordinary_input_tokens=ordinary, cost_components_usd={k: float(v) for k, v in costs.items()},
                  cost_usd=float(sum(costs.values())), cache_write_accounting_complete=written is not None)
    return result


async def run(document: str, *, setup=None, experiment_id=None, quiet=False, mode='defended'):
    if mode not in ('defended', 'control_baseline', 'processing_only', 'processing_architecture'):
        raise ValueError('Unknown mode; use CLI --mode undefended for preserved Problem 3 source')
    if setup not in (None, 'handbook_cache_enabled', 'no_cached_input_requested'):
        raise ValueError('Unknown experiment setup')
    selected = Path(document)
    if not selected.is_absolute():
        selected = ROOT / selected
    selected = selected.resolve()
    deps = RunDeps(uuid4().hex, selected, ROOT / 'output')
    deps.processing_enabled = mode != 'control_baseline'
    deps.architecture_enabled = mode in ('defended', 'processing_architecture')
    deps.output.mkdir(exist_ok=True)
    for name in ('trap_calls.json', 'usage_log.json', 'audit_trail.json'):
        path = deps.output / name
        if not path.exists():
            path.write_text('[]\n', encoding='utf-8')
    audit(deps, 'run_started', document=str(selected.relative_to(ROOT)) if selected.is_relative_to(ROOT) else str(selected), required_model=REQUIRED_MODEL, baseline='baseline-v1', setup=setup, experiment_id=experiment_id, mode=mode)
    client = None
    call_index = 0
    recorded_calls = set()
    cache_options = {'mode': 'explicit', 'ttl': '30m'} if setup else None
    try:
        if not selected.is_file():
            raise FileNotFoundError('Selected document does not exist')
        key = (dotenv_values(ROOT.parent / '.env').get('PORTKEY_API_KEY') or '').strip()
        if not key:
            raise ValueError('PORTKEY_API_KEY is missing from the root .env')
        handbook = (ROOT / 'data/shop_handbook.md').read_text(encoding='utf-8')
        deps.handbook = handbook
        prompt_path = ROOT / 'prompts/prompt.md' if mode == 'defended' else ROOT / 'output/baseline_v1/prompts/prompt.md'
        prompt = prompt_path.read_text(encoding='utf-8')

        async def requested(request):
            nonlocal call_index
            body = json.loads(request.content)
            call_index += 1
            messages = body.get('messages', [])
            def message_text(message):
                content = message.get('content', '')
                if isinstance(content, str):
                    return content
                return '\n'.join(part.get('text', '') for part in content if isinstance(part, dict))
            has_handbook = any(handbook in message_text(message) for message in messages)
            breakpoints = [index for index, message in enumerate(messages)
                           if isinstance(message.get('content'), list) and any('prompt_cache_breakpoint' in part for part in message['content'])]
            audit(deps, 'model_request', call_index=call_index, requested_model=body.get('model'),
                  handbook_present=has_handbook, handbook_sha256=hashlib.sha256(handbook.encode()).hexdigest(),
                  tools=[item.get('function', {}).get('name') for item in body.get('tools', [])],
                  setup=setup, experiment_id=experiment_id, prompt_cache_options=body.get('prompt_cache_options'),
                  breakpoint_message_indices=breakpoints, gateway_force_refresh=request.headers.get('x-portkey-cache-force-refresh'))
            if body.get('model') != REQUIRED_MODEL or not has_handbook:
                raise RuntimeError('Refusing request with wrong model or missing handbook')
            if setup and body.get('prompt_cache_options') != cache_options:
                raise RuntimeError('Experiment cache controls absent from outgoing request')
            if setup == 'handbook_cache_enabled' and not breakpoints:
                raise RuntimeError('Handbook cache breakpoint absent')
            if setup == 'no_cached_input_requested' and breakpoints:
                raise RuntimeError('No-cache request unexpectedly contains cache breakpoints')

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
            if setup:
                entry = usage_record(body, deps, call_index)
                entry.update(experiment_id=experiment_id, setup=setup, document=document, phase='document',
                             http_status=response.status_code, response_headers=metadata['headers'],
                             provider_cache_options=cache_options,
                             gateway_force_refresh_requested=True,
                             gateway_cache_status=response.headers.get('x-portkey-cache-status'))
                append_json(deps.output / 'cache_test.json', entry)
                recorded_calls.add(call_index)
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
                if setup and 'HIT' in response.headers.get('x-portkey-cache-status', '').upper():
                    raise RuntimeError('Gateway response cache hit; provider experiment invalid')

        http_client = httpx2.AsyncClient(trust_env=False, event_hooks={'request': [requested], 'response': [responded]})
        client = AsyncOpenAI(api_key=key, base_url='https://api.portkey.ai/v1',
                             default_headers={'x-portkey-api-key': key, **({'x-portkey-cache-force-refresh': 'true'} if setup else {})}, http_client=http_client,
                             max_retries=0, timeout=60)
        settings = {'openai_reasoning_effort': 'none'}
        if setup:
            settings.update(openai_prompt_cache_options=cache_options,
                            openai_cache_instructions=setup == 'handbook_cache_enabled',
                            openai_prompt_cache_key=f'hw6-{experiment_id}-{setup}')
        model = OpenAIChatModel(REQUIRED_MODEL, provider=OpenAIProvider(openai_client=client), settings=settings)
        agent = Agent(model, deps_type=RunDeps, output_type=Recommendation,
                      system_prompt=prompt + '\n\n# Shop handbook\n\n' + handbook,
                      tools=[read_document, Tool(send_email, prepare=prepare_side_effect),
                             Tool(approve_payment, prepare=prepare_side_effect)], retries=1)
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
        audit(deps, 'raw_model_answer', answer=answer, mode=mode)
        if deps.architecture_enabled:
            if not deps.document_read or deps.quote_evidence is None:
                raise RuntimeError('No selected-document evidence; refusing to invent a recommendation')
            from purchasing_policy import decide
            answer = decide(deps.quote_evidence, handbook).model_dump(mode='json')
            audit(deps, 'architecture_decision', answer=answer, raw_model_answer=result.output.model_dump(mode='json'),
                  corrected_fields=[key for key in answer if answer[key] != result.output.model_dump(mode='json')[key]])
        audit(deps, 'final_answer', answer=answer)
        if setup:
            append_json(deps.output / 'cache_runs.json', {'experiment_id': experiment_id, 'run_id': deps.run_id,
                        'setup': setup, 'document': document, 'status': 'completed', 'answer': answer})
        if not quiet:
            print(json.dumps({'run_id': deps.run_id, 'answer': answer}, indent=2))
        return answer
    except Exception as exc:
        if setup:
            if call_index and call_index not in recorded_calls:
                append_json(deps.output / 'cache_test.json', {'run_id': deps.run_id, 'experiment_id': experiment_id,
                    'setup': setup, 'document': document, 'phase': 'document', 'call_index': call_index,
                    'timestamp': now(), 'raw_usage': None, 'cost_usd': None, 'error_type': type(exc).__name__,
                    'limitation': 'No API response usage returned for this attempted call'})
            append_json(deps.output / 'cache_runs.json', {'experiment_id': experiment_id, 'run_id': deps.run_id,
                        'setup': setup, 'document': document, 'status': 'failed', 'error_type': type(exc).__name__})
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
    parser.add_argument('--mode', choices=('defended', 'undefended'), default='defended',
                        help='Default defended; undefended runs the preserved Problem 3 source in a separate process')
    args = parser.parse_args()
    if args.mode == 'undefended':
        import subprocess
        return subprocess.call([sys.executable, str(ROOT / 'undefended.py'), '--doc', args.doc])
    try:
        asyncio.run(run(args.doc))
    except Exception:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
