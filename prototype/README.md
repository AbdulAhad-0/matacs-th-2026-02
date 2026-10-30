# Prototype (optional)

Two small scripts that mirror the two halves of the design. No deployment needed.

| File | Role |
|---|---|
| `criteria.json` | The admin's criteria for the category, as data (mandatory rules, weights, scoring scales, fields to extract). Nothing about the category is hard-coded in the scripts. |
| `extract.py` | The AI step (diagram step 5) and the code around it: manipulation pre-scan, schema check, quote verification. Builds its prompt from `../PROMPTS.md` and `criteria.json`. |
| `score.py` | Everything after extraction (steps 7 to 10): mandatory gate, project limits, scoring, ranking, template-written reasons, a small audit record. No AI. |
| `extractions/A.json` to `E.json` | Expected extraction output for the sample set: structured facts only (no quotes, no licence numbers, no sample text). |
| `test_prototype.py` | 17 plain-assert tests, no pytest needed. |

## Run it

```bash
cd prototype
python score.py                        # rank the sample set from the saved extractions
python score.py --check ../ranking.json  # confirm ranking.json matches the rules
python test_prototype.py               # run the tests
python extract.py --dry-run            # print the exact prompt that would be sent (no API call)
```

To run the AI step on your own text: copy `../.env.example` to `../.env`, add a key, `pip install -r requirements.txt`, put plain-text proposals in `prototype/samples/` (git-ignored; one file per letter, page breaks marked `=== Page N ===`), then run `python extract.py`. Output goes to `extractions_live/` (also git-ignored), so the committed sample extractions are never overwritten. Point `score.py --extractions extractions_live` at it.

## What has and has not been tested

- **Tested:** all scoring, gating, ranking, pre-scan, schema validation, quote verification and prompt-building logic (17 tests). The `extract_one` flow is tested with a stubbed model: valid reply, made-up quote, and invalid JSON twice.
- **Not tested:** the live API call in `call_model()`. It was written without an API key available, so check the model name in `.env` and the temperature setting first.
