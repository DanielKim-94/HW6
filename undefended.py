"""Explicit preserved Problem 3 mode; no new processing, prompts, or access controls."""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / 'output/baseline_v1'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--doc', required=True)
    args = parser.parse_args()
    manifest = json.loads((SNAPSHOT / 'manifest.json').read_text(encoding='utf-8'))['sha256']
    for name, digest in manifest.items():
        assert hashlib.sha256((SNAPSHOT / name).read_bytes()).hexdigest() == digest
    sys.path.insert(0, str(SNAPSHOT))
    spec = importlib.util.spec_from_file_location('preserved_agent', SNAPSHOT / 'agent.py')
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    baseline.ROOT = SNAPSHOT
    original_deps = baseline.RunDeps
    class WorkspaceDeps(original_deps):
        def __init__(self, run_id, document, output):
            super().__init__(run_id, document, ROOT / 'output')
    baseline.RunDeps = WorkspaceDeps
    baseline.dotenv_values = lambda path: dotenv_values(ROOT.parent / '.env')
    selected = Path(args.doc)
    if not selected.is_absolute():
        selected = ROOT / selected
    asyncio.run(baseline.run(str(selected.resolve())))


if __name__ == '__main__':
    main()
