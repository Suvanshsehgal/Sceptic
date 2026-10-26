# Seeded-bug evaluation

Measures how often the pipeline catches known defects and how often it reports defects in correct code.

## What is measured

- **Seeded bugs (12):** 4 hallucinated API calls, 3 specification mismatches, 5 security defects. Files are in `seeded_bugs/`, labeled in `seeded_bugs/manifest.json`.
- **Clean controls (3):** correct code that uses the same APIs. Any MEDIUM-or-higher finding on these is a false positive.
- **Catch rule:** a bug is caught when its expected agent reports a MEDIUM-or-higher finding. For spec mismatches the finding must also be an `AssertionError` from a generated test. A crash such as `TypeError` does not count as catching the spec mismatch.

## How to run

```
python evaluation/run_seeded_eval.py
```

Blind-Tester runs in the Docker sandbox (`SCEPTIC_SANDBOX=docker`, the default). Generated tests come from the Groq model in `GROQ_MODEL`, so the result varies from run to run. Results are written to `results/`.

## Results (12 seeded bugs, 3 clean controls, Groq test generation on)

| Run | Catch rate | Caught | False-positive rate | Clean controls flagged |
|---|---|---|---|---|
| 1 | 75% | 9 / 12 | 67% | 2 / 3 |
| 2 | 75% | 9 / 12 | 33% | 1 / 3 |
| 3 | 75% | 9 / 12 | 33% | 1 / 3 |

Run 1's result file was deleted by mistake during cleanup. Its numbers are copied from the console output.

By category (identical in all runs):

| Category | Caught | Missed |
|---|---|---|
| Hallucinated API (Fact-Checker) | 4 / 4 | none |
| Specification mismatch (Blind-Tester) | 1 / 3 | add returns product; floor division instead of true division |
| Security (Security-Guard) | 4 / 5 | hardcoded password |

## Caveats

- **Only three clean controls.** One false positive changes the false-positive rate by 33 points. Treat the false-positive rate as indicative, not precise.
- **The false positives come from generated tests.** Blind-Tester asks the LLM for test expectations. When the expectation is wrong for correct code, the correct code fails. The scanners did not report these.
- **Hardcoded password missed.** Bandit reports the pattern at LOW, and the Semgrep rule did not match. The catch rule requires MEDIUM or higher, so this is a real gap in how severity is mapped.
- **Specification mismatches are the weakest category.** The template fallback tests check only that the function returns something and do not check the spec. The LLM-generated tests found one of three mismatches.
- **Results depend on the model.** `GROQ_MODEL` (default `openai/gpt-oss-120b`) decides the generated tests. Re-running after a model change can change the numbers.
