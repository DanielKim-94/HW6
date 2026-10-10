# Problem 2 - Handbook token and cost estimate

## Scope and supplied pricing

Inspected `data/shop_handbook.md` and `data/prices.json`. The handbook contains shop policies, approved and removed vendors, purchasing checks, a product catalogue, purchase history, and reporting instructions. All Markdown text is included in the count, including tables, punctuation, headings, and whitespace.

The supplied JSON labels its rates `gpt-6-luna` and its source ?OpenAI Standard pricing, per 1M tokens (MGT 409 Lecture 11).? Project instructions instead specify `gpt-5.6-luna`. These calculations deliberately use the supplied rates; they do not establish the actual price of the project model or Portkey billing.

All amounts below are US dollars. **1M means 1,000,000 tokens**, not 1,000 tokens.

| Pricing category | Supplied USD per 1M tokens |
|---|---:|
| Uncached input | 0.100 |
| Cached input/read | 0.010 |
| Cache write | 0.125 |
| Output | 0.500 |

Output pricing is listed for completeness but excluded from handbook-only costs. Other instructions, vendor documents, message framing, generated output, and any gateway fees are also excluded. No model API call was made for this estimate.

## Token counting method and uncertainty

**Estimated handbook input: 10,058 tokens.** Counted locally with `tiktoken` version 0.14.0, using `o200k_base`. The installed package maps `gpt-5.6-luna` to this encoding through its model-prefix mapping; it has no registered mapping for `gpt-6-luna`. This is a local tokenizer estimate, not a server-confirmed usage count.

Read the file as UTF-8 using Python `Path.read_text`, which normalizes CRLF line endings to LF. The file contains 29,241 bytes on disk and 28,903 characters after this normalization; no content was stripped or summarized. Original-file SHA-256: `332eaabbc0b87d3eaf76719e7ef1bb2287fa33a70f1b9cc0dbf115f4d3957cb6`.

Reproduce from the HW 6 folder with its virtual environment:

```python
from pathlib import Path
import tiktoken
handbook = Path("data/shop_handbook.md").read_text(encoding="utf-8")
encoding = tiktoken.get_encoding("o200k_base")
print(len(encoding.encode(handbook)))  # 10058
```

Tokenization counts subword tokens, not words or characters divided by four. As a sensitivity comparison, `cl100k_base` counts 10,184 tokens, 126 more (about 1.25%). This comparison is not a confidence interval or a guaranteed bound. Actual counts can differ with model encoding, line-ending handling, concatenation at prompt boundaries, message framing, and provider processing. Costs scale linearly with the token count; an additional 100 handbook tokens would cost $0.000010 uncached or $0.000001 as a cached read per call.

## Handbook-only calculations

Let `T = 10,058` handbook tokens and `N` be the number of calls. Let `P_u = 0.100`, `P_r = 0.010`, and `P_w = 0.125` USD per million tokens.

- Uncached: `C_u(N) = N ? T ? P_u / 1,000,000`.
- Full cached reads, with an existing warm cache: `C_r(N) = N ? T ? P_r / 1,000,000`.
- One full cache creation: `C_w = T ? P_w / 1,000,000`.

| Scenario | One call | 1,000 calls |
|---|---:|---:|
| No caching, all handbook tokens ordinary input | $0.00100580 | $1.00580000 |
| Full cached reads, cache already warm | $0.00010058 | $0.10058000 |

Substitution for one uncached call: `10,058 ? $0.100 / 1,000,000 = $0.00100580`. For one full cached read: `10,058 ? $0.010 / 1,000,000 = $0.00010058`. Multiply either result by 1,000 for the corresponding repeated-call estimate. The read-only estimate is 90% lower, before any cache creation costs.

## Initial cache creation and warm-up

The cached-read row assumes every handbook token is already cached and reused. It does not include creating the cache and is an optimistic full-hit estimate.

Using the supplied write price, one complete handbook cache write costs `10,058 ? $0.125 / 1,000,000 = $0.00125725`. The write price replaces ordinary input pricing for those tokens; it is not an extra $0.125 fee added to the $0.100 ordinary rate. Cache write/read categories and this non-additive treatment are described in the [official OpenAI prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching).

| Cold-start scenario | Formula | Handbook-only USD |
|---|---|---:|
| One cold call that writes the entire handbook | `C_w` | $0.00125725 |
| 1,000 total calls: one write, then 999 full reads | `C_w + 999 ? C_r(1)` | $0.10173667 |
| Separate warm-up write, then one full read (two requests) | `C_w + C_r(1)` | $0.00135783 |
| Separate warm-up write, then 1,000 full reads (1,001 requests) | `C_w + 1,000 ? C_r(1)` | $0.10183725 |

These scenarios assume one successful full write, no eviction, and full subsequent reuse. A cold request that does not write a cache instead costs the ordinary input estimate and does not guarantee that the next call will hit a cache. A warm-up request may also have non-handbook input or output charges, excluded here.

## Partial hits and comparison in Problem 4

Cache reuse depends on matching a reusable prompt prefix and cache availability; identical handbook content alone does not establish a full hit. Keep the stable handbook before changing vendor content. The [official caching guide](https://developers.openai.com/api/docs/guides/prompt-caching) explains prefix reuse and recommends measuring cached and written tokens.

For handbook tokens partitioned into ordinary input `U`, cached reads `R`, and cache writes `W`, where `U + R + W = T`, the general estimate is:

`C = (U ? 0.100 + R ? 0.010 + W ? 0.125) / 1,000,000` USD.

In Problem 4, record the actual model/provider, total input tokens, cached tokens, cache-write tokens if exposed, output tokens, cache configuration, and warm-up calls. Compare cold and warm usage with these estimates using the appropriate rates. API usage describes the entire request, so distinguish the handbook contribution from instructions and vendor documents. Do not label all input tokens cached or subtract only cached tokens if cache writes are a separate billed category. If Portkey does not expose write accounting, record that limitation instead of guessing it. These estimates are a baseline for that later measurement.
