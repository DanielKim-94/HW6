"""Preserve the final defended sources and verify the immutable baseline manifest."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'output'
baseline = OUT / 'baseline_v1'
for name, digest in json.loads((baseline / 'manifest.json').read_text(encoding='utf-8'))['sha256'].items():
    assert hashlib.sha256((baseline / name).read_bytes()).hexdigest() == digest, name
destination = OUT / 'defended_v1'
assert not (destination / 'manifest.json').exists(), 'Refusing to replace a preserved version'
files = ['agent.py', 'tools.py', 'models.py', 'document_processing.py', 'purchasing_policy.py',
         'undefended.py', 'prompts/prompt.md', 'requirements.txt', 'requirements-lock.txt',
         'test_agent.py', 'test_defenses.py', 'defense_experiment.py', 'defense_report.py',
         'data/shop_handbook.md', 'data/prices.json', 'output/harness.md']
manifest = {'version': 'defended-v1', 'baseline_verified': True, 'sha256': {}}
for name in files:
    target = destination / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / name, target)
    manifest['sha256'][name] = hashlib.sha256(target.read_bytes()).hexdigest()
(destination / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print('Defended snapshot saved; baseline hashes unchanged.')
