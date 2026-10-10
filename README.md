# Homework 6: Campus Customs vendor desk

A PydanticAI agent reads one HTML, text PDF, or `.eml` quote and returns purchasing fields and a handbook-based recommendation. This submission includes preserved API evidence, practice experiments, two original attacks, frozen exam outputs, and a self-contained offline report.

The required model for this assignment is **gpt-6-luna through Portkey**, selected explicitly in the homework instructions. Returned responses reported `gpt-6-luna-2026-09-22`. The full handbook is sent on every call. The gateway-reported provider was Azure OpenAI; this is metadata evidence, not independent routing verification.

## File layout

```text
agent.py, tools.py, models.py
document_processing.py, purchasing_policy.py, undefended.py
prompts/prompt.md
requirements.txt, requirements-lock.txt, requirements-red-team.txt
AI_prompts.md, README.md, .env.example, .gitignore, .gitattributes
data/
  shop_handbook.md, prices.json, practice_key.json
  practice_docs/       # 12 original practice files
  exam_docs/           # 10 original exam files
  my_attacks/          # two original attack documents
output/
  handbook_estimate.md
  harness.md, trap_calls.json, usage_log.json, audit_trail.json
  cache_test.json, cache_test.md
  attack_results.json, attack_results.md
  defense_results.json, defense_results.md
  red_team.md, red_team_results.json
  exam_results.json, exam_results.md, exam_attempts.json
  hw6_report.html
  baseline_v1/, defended_v1/, exam_frozen_v1/
  ...                 # controls, run metadata, extraction and verification evidence
```

The complete `data/` folder is submitted, including the practice key. The inference agent never reads that key; only practice evaluation scripts use it after inference. No exam answer key was searched for or consulted.

## Setup and local key

Tested with Windows PowerShell and Python 3.14.7. Create a virtual environment inside this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-red-team.txt
```

`requirements.txt` pins direct agent dependencies; `requirements-red-team.txt` adds PDF authoring. `requirements-lock.txt` preserves the earlier defended dependency environment; `output/exam_frozen_v1/environment-lock.txt` records installed packages at the exam freeze. Other Python/platform combinations were not tested.

For fidelity to the frozen implementation, the agent loads `PORTKEY_API_KEY` from **the parent folder's `.env`**, not this repository's `.env`. No real key is included. If the parent file does not already exist:

```powershell
if (-not (Test-Path ..\.env)) { Copy-Item .env.example ..\.env }
```

Edit `../.env` locally and replace the placeholder with your Portkey key. Keep an existing configured parent file rather than overwriting it. Both `.env` and `.env.*` are ignored; `.env.example` is the intentional placeholder exception. Do not paste a key into code, logs, commits, or the report. API runs require internet access and incur usage charges; viewing the report does not.

## Run one quote

```powershell
.\.venv\Scripts\python.exe agent.py --doc data/practice_docs/p01_bluehen_quote.html
.\.venv\Scripts\python.exe agent.py --mode undefended --doc data/practice_docs/p01_bluehen_quote.html
```

Default defended mode processes document visibility, restricts tool access, uses prompt rules, and applies the existing local purchasing coordinator before emitting its final answer. Raw model answers and coordinator corrections are retained separately. Explicit undefended mode starts a separate process using hash-verified Problem 3 source and prompt in `output/baseline_v1`; it does not use the later defense layers.

The reader may access only the selected document. `send_email` and `approve_payment` remain **inert logging traps** in both modes: they have no email/payment implementation. Defended mode hides them without trusted server-side capabilities and also denies unauthorized calls in their implementations. Documents cannot grant those capabilities.

Run CLI processes sequentially: logs use atomic JSON-array replacement and an in-process lock, not a cross-process database. Relative document references help avoid model corruption of non-English absolute paths.

## Reproduce experiments without overwriting submitted evidence

Use a separate clone or working copy for new experiments. Batch scripts append raw logs but update latest-experiment selectors and regenerated reports. New outputs can vary; reproduction does not guarantee identical answers or cache behavior. Preserve the submitted `output/` folder and its snapshots before rerunning.

```powershell
# Offline implementation checks; no model API calls.
.\.venv\Scripts\python.exe -m unittest test_agent test_defenses

# Problem 4: 12 documents in each cache setup; then report returned usage.
.\.venv\Scripts\python.exe cache_experiment.py
.\.venv\Scripts\python.exe cache_report.py

# Problem 5: preserved undefended source on all 12 practice documents.
.\.venv\Scripts\python.exe attack_experiment.py
# If a document failed, retry only failed documents, retaining earlier attempts:
# .\.venv\Scripts\python.exe attack_experiment.py --retry-failed
.\.venv\Scripts\python.exe attack_report.py

# Problem 6: four cumulative variants for controlled cost comparisons.
.\.venv\Scripts\python.exe defense_experiment.py
.\.venv\Scripts\python.exe defense_experiment.py --final-only
.\.venv\Scripts\python.exe defense_report.py

# Problem 7: two existing originals, each in both modes.
.\.venv\Scripts\python.exe red_team_experiment.py
.\.venv\Scripts\python.exe red_team_report.py

# Offline report generation from selected recorded experiments.
.\.venv\Scripts\python.exe build_hw6_report.py
```

The Problem 5 runner was repaired for submission so it reads the preserved baseline prompt even though the live prompt now contains defenses. This is a path adapter change only; no stored results or immutable snapshots were changed, and no new API experiments were run for submission preparation. Human-view observations in reports apply to the recorded original trials and should be collected again for materially different documents or results.

`create_my_attacks.py` refuses to overwrite the supplied originals; run it only in a separate working copy after intentionally removing those two output documents. The checked-in originals and their hashes are already available. The study did not tune payloads through hidden retries.

### Frozen exam evidence and reruns

`exam_results.json` contains one selected complete return per file, with `minimum_order` exported as `min_order`. No accepted answer was hand-edited or graded. Its final pipeline contains the pre-existing coordinator; raw model answers are in `exam_attempts.json`. `exam_experiment.json` records the result hash, selected runs, and incomplete-export history.

To test one file with the archived configuration in a separate clone, use a new experiment identifier:

```powershell
.\.venv\Scripts\python.exe exam_relative_runner.py --file e01_quote.html --experiment-id independent-reproduction
```

Repeat for each of the ten exam filenames if a fresh full evaluation is wanted. This appends raw audit and usage evidence but does **not** replace the submitted exam-results artifact. The frozen exam runner verifies all archived hashes. `exam_experiment.py` deliberately refuses to overwrite existing exam results or the freeze; `exam_rerun_failed.py` only handles files with no accepted answer and preserves earlier incomplete exports. Do not remove those safeguards to revise a submitted answer.

The original study had one failed pre-API launch and two failed e09 attempts caused by a malformed absolute tool path. The second e09 failure was a gateway HIT replay; its reported historical usage does not establish new inference or billing. e09 completed on attempt 3 using an equivalent relative reference to the same frozen document. All failures, successful reruns, and usage remain recorded separately.

## Offline report

Open `output/hw6_report.html` directly in Edge or another browser. It includes its own styles, inline SVG chart, PDF preview, downloadable original attack documents, and embedded numerical evidence. It has no external scripts, fonts, styles, or file dependencies. Moving just this HTML file to another folder still permits offline viewing.

The user reviewed it in Edge and confirmed readable chart labels/tables and a recommendation reflecting their view. This is recorded as user-reported visual evidence in `output/hw6_visual_review.json`, distinct from automated structure/number checks.

Display rounding does not alter exact experiment results: token counts are comma-separated integers; experiment/per-document USD uses six decimals; USD per 1,000 documents uses four; item prices, monthly USD and percentages use two. Experiment totals, scaled means, and 30,000-document projections are separately labeled.

## What was measured and what remains unknown

- Problem 4 baseline caching: $0.005124405 for 12 cached documents versus $0.026600000 without cached input, including writes; savings 80.74%. Every no-cache call reported zero cached reads/writes. Gateway refreshes distinguished input caching from response reuse.
- Problem 5 baseline: 8/12 complete six-field matches and 10/12 decision matches. Final defended practice pipeline: 12/12 on both metrics. One raw clean-quote model decision was repaired by the existing coordinator; pipeline success is not perfect model accuracy.
- Original attacks: neither chosen behavior succeeded in either mode, despite both payloads reaching both readers. This exposes visibility-filter gaps and is not a universal-resistance claim.
- Exam: ten complete, ungraded outputs; **accuracy is unknown**. Reported usage and audit records support the returns, not independent correctness or invoice verification.
- At 1,000 documents/day for 30 days, defended measured means project to about $10.58 under the observed warm exam pattern or $67.73 without cached input. These are workload/cache scenarios, not a guaranteed range. Same supplied rates, model, similar quote/output lengths and roughly two calls/document are assumed; fees, review, hosting, OCR, and extra failures/retries are excluded.

Static rendering heuristics do not fully reproduce browser/PDF visibility, scanned PDFs need OCR, email attachments are not parsed, unfamiliar quote formats can need review, and vendor-name matching is not identity verification. Use the agent to draft recommendations with a person reviewing every quote and decision; keep real email and payment authority outside this prototype.

## Submission status

`output/submission_checks.md` and `output/submission_checks.json` record the provided-layout, run-evidence, secret-exclusion, and offline checks. These checks cover the user-specified file list; no complete independent grading rubric was supplied, so full rubric compliance is not claimed. Run records are internally matched to audit/API metadata; they are not independently reconciled with a provider invoice.

Published at https://github.com/DanielKim-94/HW6. An anonymous clone verified every initial submitted file byte-for-byte; see `output/publication_verification.json`. The user will submit the final repository URL to Canvas themselves; no Canvas submission is performed by this project.

Git attributes preserve exact file bytes, including PDFs and frozen hash-verified evidence, across Windows checkouts.
