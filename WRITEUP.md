# Write-up: AI proposal triage (MATACS-TH-2026-02)

**In short.** A reviewer uploads PDFs and picks a category. Code checks the files and turns them into text. One AI step reads each proposal and copies facts into a fixed form, with a quote for every fact. After that, code does the rest: it checks the quotes, applies the mandatory pass/fail rules, scores with the admin's formulas, ranks, and writes the reasons. Anything unclear is set aside for a person, and a person makes the award. See `diagram/process-flow.png`. On the sample set, the design ranks A first and E second, rules B out, and sets C and D aside for a human (reasons in `ranking.json`).

## 1. AI vs. rules

**AI, one step only:** reading messy proposal text and extracting facts (price, weeks, who holds the licence, warranty years, team items). Bidders word the same fact many ways, which rules handle badly.

**Plain code, everything else:** file checks, PDF-to-text, quote checking, mandatory pass/fail, formulas, weights, ranking and reason text.

**Why there:** a decision must be repeatable and explainable to a bidder, and maths and thresholds are where AI is least reliable. An AI that also scored could be talked into a different answer by the text it reads. If AI only extracts, a trick can at worst change a fact, and every fact has a quote a person can check.

## 2. Consistency and explainability

- **Scores are code.** Same extracted facts plus the same criteria version always give the same score. Scales are fixed numbers (for example price earns 0 points at the ceiling and full points at 20% below it), so a score never depends on the other proposals in the batch.
- **Same result twice?** Yes. The AI step uses a pinned model, a fixed prompt version, temperature 0 and a strict JSON form, and its output is saved against (file hash, prompt, model, criteria version). Ranking again reuses it. A fresh extraction could differ, so quotes are re-checked and any changed fact is highlighted. Model upgrades are tested on a known set first.
- **Seeing why.** For each proposal the reviewer gets a table: criterion, extracted value, source quote and page, rule applied, points × weight. The one-line reason is generated from that table by a template, so it cannot claim anything the numbers do not support.

## 3. Human in the loop

- **Review screen (main checkpoint).** Shows the ranked list plus the flagged and ineligible piles with reasons and quotes. The reviewer can accept, override any extracted fact (reason required), ask the bidder to clarify, clear a flag, or disqualify. Any change re-scores from saved facts and is logged.
- **Ineligible is not final.** A reviewer can reverse it, with a reason.
- **Award.** A person decides, outside the tool. The tool never awards or contacts bidders itself.
- **Audit log (append-only):** file hashes, criteria version, prompt version, model and settings, raw AI output, validation results, flags, every override or decision with user, time and reason, scoring code version, and the exported ranking.

## 4. Changing criteria

Criteria are versioned. An edit creates v2 and never rewrites v1. Old rankings stay tied to the version they used and show "criteria changed since this was scored".

- **Weights, formulas or limits changed:** re-score immediately from saved facts, with no AI cost.
- **New criterion or field:** the AI re-extracts only the new fields; other facts are reused.
- **Mandatory rules changed:** proposals may move between ranked and ineligible. The screen shows old and new rankings side by side and a reviewer confirms.

Safeguards: weights must total 100 (checked in code), only admins can edit, every edit needs a reason and is logged, and criteria lock once an award is recorded.

## 5. Risks

| Risk | Safeguard |
|---|---|
| Wrong extraction | Every value needs a verbatim quote. Code checks the quote exists in the source; failures are flagged. The reviewer sees the quote beside each value. |
| Made-up facts | "Not stated" is an allowed answer and the prompt forbids inference. D gives no schedule, so it is flagged, not guessed. |
| Wrong eligibility call | A clear failure is ineligible (B: the licence sits with an unnamed subcontractor). A missing fact is flagged, not failed, because it may be an extraction miss. A person can overturn either. |
| Manipulation (prompt injection) | C contains text telling automated reviewers to rank it first. That text is treated as data (delimited and the model is told so), a rule-based scan and the AI both report it, and above all the AI cannot set scores, code does. C is held for a person and the attempt is logged. |
| Bias | Only admin criteria are scored, same formulas for everyone; company name, size and location are not inputs. Periodic tests with shuffled order and swapped names. |
| Cost | One extraction call per proposal, cached. Re-scoring is free. File and page limits and a spend cap per batch. |
| Confidentiality | Commercial data: provider terms with no training on inputs, project-level access, retention limits. |
| Unreadable PDFs | OCR, then a text-quality check. Poor text is set aside. |
| Over-trust | Labelled decision support; flags appear above the list. |

## Assumptions (no reply awaited)

- "Last 5 years" means calendar years 2021 to 2026. C counts from 2020, so its experience count is noted as unconfirmed.
- The brief gives no point scales, so I chose defaults (README lists them); they are admin-editable data. A still ranks first in all 108 variations I tried.
- Leads described as "named" are accepted at face value; production would capture the name.
- Only A and B say what the price includes, so other bids carry a "may not be like-for-like" note.
