# Problem 10 - Submission checks

Checks passed for the user-requested layout: agent files, prompt, requirements, AI prompt record, documentation, required outputs, and the complete data folder (12 practice, 10 exam, 2 original attack documents, plus handbook/prices/practice key).

Recorded final outputs and selected API usage were matched to run-specific final_answer, request and response audit events. Counts of verified returned model-call records: {"practice_baseline": 24, "practice_final_defended": 24, "original_red_team": 8, "exam_selected_complete": 20, "controlled_cache_calls": 48}. Costs were recalculated using supplied rates. Failed attempts are retained, not substituted for complete answers. This establishes internal evidence consistency, not independent provider invoice verification or exam correctness.

All baseline, defended, and frozen-exam manifest hashes are unchanged. The final agent/prompt files still match the exam freeze. Only the external Problem 5 reproduction adapter was fixed to load the preserved prompt; its offline load check passed. No new model experiments were run while preparing submission.

The offline report has no external dependencies; embedded attack originals and exam evidence match their source bytes. The user reviewed report SHA-256 `737f6f64bcc8f6245abdd4a8a640983f51bc2c7f30f402d416a85eb559028b70` in Edge and confirmed readable chart labels/tables and a recommendation reflecting their view. That observation is user-reported evidence, recorded separately in hw6_visual_review.json.

The staged public files were scanned for exact configured secret values and common credential-token patterns, including decoded HTML data assets. No matches were found. Real environment files, virtual environments, caches and credential-file patterns are excluded; .env.example contains only a placeholder. This is a scoped scan, not a guarantee against every conceivable secret format.

## Remaining limitations

- Checks cover the user-specified layout, not a complete independently supplied grading rubric.
- Run/audit/API-usage records agree internally; provider invoices and routing are not independently verified.
- Exam accuracy remains unknown; no exam key was consulted.
- Visibility heuristics, quote parsing, OCR/attachments, and vendor authentication have documented limits.
- The repaired baseline batch adapter was tested offline only; submission preparation made no new model API calls.
- Publication verification is recorded separately in publication_verification.json.

## Publication

Authorized repository: https://github.com/DanielKim-94/HW6. Anonymous cloning and byte-for-byte verification of the initial submission succeeded; see publication_verification.json. The user will submit the verified repository URL to Canvas themselves.
