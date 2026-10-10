"""Offline checks; use temporary logs so assignment evidence stays untouched."""
import asyncio
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx2

import agent
from models import RunDeps, Recommendation
from tools import extract_document, read_document, send_email, approve_payment


class AgentTests(unittest.TestCase):
    def test_extract_all_formats(self):
        for path in (agent.ROOT / 'data/practice_docs').iterdir():
            if path.suffix in ('.html', '.pdf', '.eml'):
                self.assertTrue(extract_document(path).strip(), path.name)
        self.assertIn('$21.80', extract_document(agent.ROOT / 'data/practice_docs/p01_bluehen_quote.html'))
        self.assertIn('Chapel Street Goods', extract_document(agent.ROOT / 'data/practice_docs/p08_chapelst_email.eml'))

    def test_traps_and_preservation(self):
        with tempfile.TemporaryDirectory() as temporary:
            deps = RunDeps('offline-run', (agent.ROOT / 'data/practice_docs/p01_bluehen_quote.html').resolve(), Path(temporary))
            ctx = SimpleNamespace(deps=deps, tool_call_id='offline-call')
            self.assertIn('no email sent', send_email(ctx, 'test@example.invalid', 'subject', 'body'))
            self.assertIn('no payment made', approve_payment(ctx, 'test vendor', 1.25))
            records = json.loads((deps.output / 'trap_calls.json').read_text())
            self.assertEqual([r['tool'] for r in records], ['send_email', 'approve_payment'])
            self.assertEqual(records[0]['arguments']['body'], 'body')
            self.assertEqual(records[1]['run_id'], 'offline-run')
            self.assertIn('$21.80', read_document(ctx, str(deps.document)))
            with self.assertRaises(ValueError):
                read_document(ctx, str(agent.ROOT / 'data/shop_handbook.md'))
            self.assertEqual(len(json.loads((deps.output / 'trap_calls.json').read_text())), 2)

    def test_usage_accounting(self):
        deps = RunDeps('offline', Path('unused'), Path('unused'))
        body = {'model': 'gpt-6-luna-2026-09-22', 'usage': {'prompt_tokens': 1000, 'completion_tokens': 100,
                'prompt_tokens_details': {'cached_tokens': 500, 'cache_write_tokens': 200}}}
        result = agent.usage_record(body, deps, 1)
        self.assertEqual(result['ordinary_input_tokens'], 300)
        self.assertAlmostEqual(result['cost_usd'], 0.000110)
        del body['usage']['prompt_tokens_details']['cache_write_tokens']
        self.assertFalse(agent.usage_record(body, deps, 1)['cache_write_accounting_complete'])
        self.assertIsNone(agent.usage_record({'model': 'gpt-6-luna'}, deps, 1)['cost_usd'])

    def test_model_mismatch_stops_before_trap(self):
        original_client = httpx2.AsyncClient
        original_root = agent.ROOT
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'HW 6'
            root.mkdir()
            shutil.copytree(original_root / 'data', root / 'data')
            shutil.copytree(original_root / 'prompts', root / 'prompts')
            (root.parent / '.env').write_text('PORTKEY_API_KEY=offline-placeholder\n')
            def respond(request):
                request_body = json.loads(request.content)
                self.assertEqual(request_body['model'], 'gpt-6-luna')
                self.assertIn('Campus Customs Shop Handbook', request_body['messages'][0]['content'])
                return httpx2.Response(200, json={'id': 'offline-mismatch', 'model': 'gpt-5.6-luna',
                    'choices': [{'message': {'role': 'assistant', 'tool_calls': [{'id': 'trap', 'type': 'function',
                        'function': {'name': 'send_email', 'arguments': '{"to":"test@example.invalid","subject":"test","body":"test"}'}}]}}],
                    'usage': {'prompt_tokens': 1000, 'completion_tokens': 20}})
            class OfflineClient(original_client):
                def __init__(self, **kwargs):
                    super().__init__(transport=httpx2.MockTransport(respond), **kwargs)
            with patch.object(agent, 'ROOT', root), patch.object(httpx2, 'AsyncClient', OfflineClient), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(agent.ModelMismatch):
                    asyncio.run(agent.run('data/practice_docs/p01_bluehen_quote.html'))
            self.assertEqual(json.loads((root / 'output/trap_calls.json').read_text()), [])
            evidence = json.loads((root / 'output/audit_trail.json').read_text())
            self.assertTrue(any(e['event'] == 'run_failed' for e in evidence))
            self.assertFalse(any(e['event'] == 'final_answer' for e in evidence))

    def test_unknown_fields_and_decision_enum(self):
        answer = Recommendation(vendor=None, sku=None, unit_price=None, lead_time_days=None,
                                minimum_order=None, decision='do_not_recommend', reason='Purchasing facts are unknown.')
        self.assertIsNone(answer.unit_price)
        with self.assertRaises(ValueError):
            Recommendation(**{**answer.model_dump(), 'decision': 'approve'})


if __name__ == '__main__':
    unittest.main()
