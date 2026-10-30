import json
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

DATA = Path(__file__).resolve().parent
LABELS = {"smishing", "normal"}
CATEGORIES = {"택배", "공공기관", "가족", "금융", "유출통지", "기타"}
PHONE = re.compile(r"01[016789][-. ]?\d{3,4}[-. ]?\d{4}")
FAKE_PHONE = re.compile(r"010[-. ]?0000[-. ]?\d{4}")

errors = []


def load(name):
    rows = []
    if not (DATA / name).exists():
        errors.append(f"{name} missing")
        return rows
    for n, line in enumerate((DATA / name).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            errors.append(f"{name}:{n} invalid JSON ({e})")
    return rows


def check_rows(name, rows, id_prefix):
    ids = Counter(r.get("id") for r in rows)
    for i, c in ids.items():
        if c > 1:
            errors.append(f"{name}: duplicate id {i}")
    for r in rows:
        rid = r.get("id", "?")
        if r.get("label") not in LABELS:
            errors.append(f"{name}:{rid} bad label {r.get('label')!r}")
        if r.get("category") not in CATEGORIES:
            errors.append(f"{name}:{rid} bad category {r.get('category')!r}")
        if not isinstance(r.get("text"), str) or not r["text"].strip():
            errors.append(f"{name}:{rid} empty text")
            continue
        if not id_prefix(r):
            errors.append(f"{name}:{rid} id does not match label")
        for m in PHONE.findall(r["text"]):
            if not FAKE_PHONE.fullmatch(m):
                errors.append(f"{name}:{rid} real-looking phone {m}")


def report(name, rows):
    print(f"{name}: {len(rows)} rows")
    for label in sorted(LABELS):
        cats = Counter(r["category"] for r in rows if r.get("label") == label)
        print(f"  {label}: {sum(cats.values())}  " + ", ".join(f"{c} {n}" for c, n in sorted(cats.items())))


cases = load("cases.jsonl")
test = load("test.jsonl")

check_rows("cases.jsonl", cases, lambda r: str(r.get("id", ""))[:1] == ("s" if r.get("label") == "smishing" else "n"))
check_rows("test.jsonl", test, lambda r: str(r.get("id", ""))[:2] == ("ts" if r.get("label") == "smishing" else "tn"))

case_counts = Counter(r.get("label") for r in cases)
if case_counts["smishing"] < 100 or case_counts["normal"] < 100:
    errors.append(f"cases.jsonl needs >=100 per label, has {dict(case_counts)}")

test_counts = Counter(r.get("label") for r in test)
if len(test) != 60 or test_counts["smishing"] != 30 or test_counts["normal"] != 30:
    errors.append(f"test.jsonl needs exactly 30+30, has {dict(test_counts)}")

for r in test:
    for field in ("novel", "from_contact"):
        if not isinstance(r.get(field), bool):
            errors.append(f"test.jsonl:{r.get('id')} missing bool {field}")

case_texts = {r.get("text") for r in cases}
for r in test:
    if r.get("text") in case_texts:
        errors.append(f"test.jsonl:{r.get('id')} text duplicated in cases")

novel_smishing = [r for r in test if r.get("novel") and r.get("label") == "smishing"]
if len(novel_smishing) < 10:
    errors.append(f"test.jsonl needs >=10 novel smishing, has {len(novel_smishing)}")

worst = []
for r in (r for r in test if r.get("novel")):
    best = max(cases, key=lambda c: SequenceMatcher(None, r["text"], c["text"]).ratio(), default=None)
    if best is None:
        continue
    ratio = SequenceMatcher(None, r["text"], best["text"]).ratio()
    if ratio >= 0.6:
        worst.append((ratio, r["id"], best["id"]))
for ratio, tid, cid in sorted(worst, reverse=True)[:10]:
    errors.append(f"novel {tid} too close to {cid} (ratio {ratio:.2f})")

report("cases.jsonl", cases)
report("test.jsonl", test)
print(f"  novel smishing: {len(novel_smishing)}, from_contact: {sum(1 for r in test if r.get('from_contact'))}")

if errors:
    print(f"\nFAIL ({len(errors)})")
    for e in errors:
        print("  " + e)
    sys.exit(1)
print("\nOK")
