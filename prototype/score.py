#!/usr/bin/env python3
"""Rule-based half of the proposal triage flow (steps 6-10 in the diagram).

Input : criteria.json (admin config) + one extraction JSON per proposal.
Output: status (ranked / flagged / ineligible), score, rank and a per-criterion breakdown.

No AI is used here. The same inputs always give the same output, and a proposal's
score never depends on the other proposals in the batch.

    python score.py                       # score the committed sample extractions
    python score.py --check ../ranking.json   # also compare with ranking.json
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


# ---------------------------------------------------------------- helpers
def load_json(path):
    return json.loads(Path(path).read_text())


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def get(ext, key):
    """Extracted value for a field, or None if the field is missing."""
    field = ext.get("fields", {}).get(key)
    return None if field is None else field.get("value")


def resolve(x, project):
    """Anchors may be numbers or 'project.<name>' references into the criteria config."""
    if isinstance(x, str) and x.startswith("project."):
        return project[x.split(".", 1)[1]]
    return x


def linear_points(v, zero_at, full_at):
    """0 points at zero_at, 100 at full_at, straight line between, clamped.
    Works for 'higher is better' and 'lower is better' (zero_at > full_at)."""
    return 100 * max(0.0, min(1.0, (v - zero_at) / (full_at - zero_at)))


def validate_config(cfg):
    total = sum(c["weight"] for c in cfg["weighted"])
    if total != 100:
        raise ValueError(f"Weights must add up to 100, got {total}")


# ---------------------------------------------------------------- mandatory gate
def check_status(ext, check):
    v = get(ext, check["field"])
    if "min" in check:
        return "unclear" if v is None else ("pass" if v >= check["min"] else "fail")
    if check.get("present"):
        return "pass" if v not in (None, "") else "unclear"
    if v in check.get("pass", []):
        return "pass"
    if v in check.get("fail", []):
        return "fail"
    return "unclear"  # not_stated / unclear / missing: a human should look, not a rule guess


# ---------------------------------------------------------------- weighted criteria
def score_criterion(ext, crit, project):
    """Returns (points_0_to_100 or None if a needed value is missing, human-readable detail)."""
    s = crit["scoring"]
    if s["type"] == "linear":
        v = get(ext, s["field"])
        if v is None:
            return None, "not stated"
        return linear_points(v, resolve(s["zero_at"], project), resolve(s["full_at"], project)), f"{v:g}"
    if s["type"] == "linear_avg":
        parts, shown, missing = [], [], False
        for comp in s["components"]:
            v = get(ext, comp["field"])
            if v is None:
                parts.append(0.0)
                shown.append("not stated")
                missing = True
            else:
                parts.append(linear_points(v, comp["zero_at"], comp["full_at"]))
                shown.append(f"{v:g}")
        return sum(parts) / len(parts), " / ".join(shown) + (" (part missing)" if missing else "")
    if s["type"] == "checklist":
        hits = []
        for item in s["items"]:
            v = get(ext, item["field"])
            ok = (v not in (None, "")) if item.get("present") else (v == item.get("equals"))
            hits.append((item["label"], ok))
        pts = 100 * sum(ok for _, ok in hits) / len(hits)
        return pts, ", ".join(f"{'yes' if ok else 'no'}: {lab}" for lab, ok in hits)
    raise ValueError(f"Unknown scoring type {s['type']}")


def evaluate(ext, cfg, year):
    proj = cfg["project"]
    inel, holds, notes = [], [], list(ext.get("notes", []))

    # 1. manipulation signals (AI report + rule-based pre-scan) -> hold for a human
    signals = list(ext.get("suspicious_instructions", [])) + list(ext.get("prescan_hits", []))
    if signals:
        pages = sorted({str(s.get("page", "?")) for s in signals})
        holds.append(f"Text aimed at automated reviewers found (page {', '.join(pages)}); ignored for scoring, needs human review")
    if ext.get("verification_problems"):
        holds.append("Extraction could not be verified against the source text; needs human review")

    # 2. mandatory pass/fail
    mandatory = []
    for m in cfg["mandatory"]:
        results = [check_status(ext, c) for c in m["checks"]]
        res = "fail" if "fail" in results else "unclear" if "unclear" in results else "pass"
        mandatory.append((m["label"], res))
        if res == "fail":
            inel.append(f"Fails mandatory criterion: {m['label']}")
        elif res == "unclear":
            holds.append(f"Mandatory criterion not confirmed: {m['label']}")

    # 3. weighted criteria, hard limits, notes
    rows, total = [], 0.0
    for crit in cfg["weighted"]:
        pts, detail = score_criterion(ext, crit, proj)
        s = crit["scoring"]
        limit_key = s.get("ineligible_if_above")
        if limit_key and pts is not None:
            v, limit = get(ext, s["field"]), resolve(limit_key, proj)
            if v > limit:
                inel.append(f"{crit['label']} ({v:g}) is above the limit ({limit:g})")
        if pts is None:
            if crit.get("hold_if_missing"):
                holds.append(f"{crit['label']} not stated, so the project requirement cannot be verified")
            else:
                notes.append(f"{crit['label']} not stated (scored 0)")
            pts = 0.0
        for rule in crit.get("notes_if", []):
            if get(ext, rule["field"]) != rule["equals"]:
                notes.append(rule["message"])
        w = crit.get("window")
        if w:
            start, back = get(ext, w["start_year_field"]), get(ext, w["years_back_field"])
            window_start = year - proj["experience_window_years"]
            if start is not None and start < window_start:
                notes.append(f"Experience counted from {start}, earlier than the {proj['experience_window_years']}-year window "
                             f"(from {window_start}); count may include older installs")
        earned = pts * crit["weight"] / 100
        total += earned
        rows.append({"id": crit["id"], "label": crit["label"], "weight": crit["weight"], "detail": detail,
                     "points": round(pts, 1), "earned": round(earned, 2)})

    if inel:
        status, score = "ineligible", None
    elif holds:
        status, score = "flagged", None
    else:
        status, score = "ranked", total
    return {"proposal": ext["proposal_id"], "status": status, "score": score,
            "price": get(ext, "price.total_cad"),
            "provisional_score": total if status == "flagged" else None,
            "mandatory": mandatory, "rows": rows,
            "ineligible_reasons": inel, "holds": holds, "notes": notes}


def explain(r):
    """Template-written reason (no AI), built only from the breakdown."""
    if r["status"] == "ineligible":
        return "; ".join(r["ineligible_reasons"]) + ". Not scored."
    if r["status"] == "flagged":
        return "Held for human review: " + "; ".join(r["holds"]) + f". Provisional score {r['provisional_score']:.1f} if cleared."
    best = max(r["rows"], key=lambda x: x["points"])
    worst = min(r["rows"], key=lambda x: x["points"])
    return (f"Passes all mandatory checks. Score {r['score']:.1f}/100. Strongest: {best['label']} ({best['points']:.0f}/100). "
            f"Weakest: {worst['label']} ({worst['points']:.0f}/100).")


def run(cfg, extractions, year):
    validate_config(cfg)
    results = [evaluate(e, cfg, year) for e in extractions]
    ranked = [r for r in results if r["status"] == "ranked"]
    # tie-break: higher experience points, then lower price
    ranked.sort(key=lambda r: (-r["score"], -next(x["points"] for x in r["rows"] if x["id"] == "experience"),
                               r["price"] if r["price"] is not None else float("inf")))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    for r in results:
        r.setdefault("rank", None)
    results.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["proposal"]))
    return results


# ---------------------------------------------------------------- CLI
def print_report(results):
    for r in results:
        head = f"{r['proposal']}: {r['status'].upper()}"
        if r["rank"]:
            head += f"  rank {r['rank']}  score {r['score']:.1f}"
        elif r["provisional_score"] is not None:
            head += f"  (provisional score {r['provisional_score']:.1f}, not ranked)"
        print(head)
        for lab, res in r["mandatory"]:
            print(f"    mandatory [{res:7}] {lab}")
        if r["status"] != "ineligible":
            for row in r["rows"]:
                print(f"    {row['label']:<18} {row['detail']:<40} {row['points']:>5.1f}/100 x {row['weight']}% = {row['earned']:>5.2f}")
        for t in r["ineligible_reasons"] + r["holds"]:
            print(f"    ! {t}")
        for t in r["notes"]:
            print(f"    note: {t}")
        print(f"    reason: {explain(r)}\n")


def check_against(results, path):
    expected = {e["proposal"]: e for e in load_json(path)}
    bad = 0
    for r in results:
        e = expected[r["proposal"]]
        same = e["status"] == r["status"] and e["rank"] == r["rank"]
        if e["score"] is not None or r["score"] is not None:
            same = same and e["score"] is not None and r["score"] is not None and abs(e["score"] - r["score"]) < 0.05
        print(f"check {r['proposal']}: {'OK' if same else 'MISMATCH'}")
        bad += not same
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--criteria", default=HERE / "criteria.json")
    ap.add_argument("--extractions", default=HERE / "extractions")
    ap.add_argument("--year", type=int, default=2026, help="evaluation year (explicit so runs are reproducible)")
    ap.add_argument("--check", help="path to a ranking.json to compare against")
    ap.add_argument("--json", help="write the run record (results + input hashes) to this path")
    args = ap.parse_args()

    cfg = load_json(args.criteria)
    files = sorted(Path(args.extractions).glob("*.json"))
    results = run(cfg, [load_json(f) for f in files], args.year)
    print_report(results)

    if args.json:  # tiny audit record: what went in, what came out
        record = {"criteria_version": cfg["version"], "criteria_sha256": sha256(args.criteria),
                  "evaluation_year": args.year, "inputs_sha256": {f.stem: sha256(f) for f in files},
                  "results": [{k: r[k] for k in ("proposal", "status", "rank", "score", "provisional_score")} for r in results]}
        Path(args.json).write_text(json.dumps(record, indent=2))
    if args.check:
        sys.exit(1 if check_against(results, args.check) else 0)


if __name__ == "__main__":
    main()
