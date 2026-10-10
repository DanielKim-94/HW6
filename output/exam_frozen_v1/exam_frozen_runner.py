"""Run one exam file using frozen source, with output/credential path adapters only."""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parent
FROZEN=ROOT/'output/exam_frozen_v1'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--file',required=True)
    parser.add_argument('--experiment-id',required=True)
    args=parser.parse_args()
    manifest=json.loads((FROZEN/'manifest.json').read_text(encoding='utf-8'))
    for name,digest in manifest['sha256'].items():
        assert hashlib.sha256((FROZEN/name).read_bytes()).hexdigest()==digest, name
    assert args.file in manifest['exam_files']
    sys.path.insert(0,str(FROZEN))
    spec=importlib.util.spec_from_file_location('frozen_exam_agent',FROZEN/'agent.py')
    baseline=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    original_deps=baseline.RunDeps
    class WorkspaceDeps(original_deps):
        def __init__(self,run_id,document,output):
            super().__init__(run_id,document,ROOT/'output')
    baseline.RunDeps=WorkspaceDeps
    baseline.dotenv_values=lambda path:dotenv_values(ROOT.parent/'.env')
    asyncio.run(baseline.run(str(FROZEN/'data/exam_docs'/args.file),mode='defended',
                            experiment_id=args.experiment_id,quiet=True))

if __name__=='__main__':
    main()
