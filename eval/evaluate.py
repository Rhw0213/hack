"""Compare rules / rules+AI / rules+AI+RAG on data/test.jsonl.

Run: py eval\\evaluate.py [--modes rules,ai,full]
"""
import argparse
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import ai  # noqa: E402
from app import MODES, analyze  # noqa: E402

OUT = Path(__file__).resolve().parent / "results.md"
FLAGGED = {"caution", "danger"}
MODE_LABEL = {"rules": "규칙만 (rules)", "ai": "규칙+AI (ai)", "full": "규칙+AI+RAG (full)"}
HEADER = [
    "| 모드 | 탐지율 | 오탐률 | 신규 변종 탐지율 | 위험(🔴) 비율 | 평균 응답 ms | p95 ms |",
    "|---|---|---|---|---|---|---|",
]
LEGEND = [
    "- 탐지율: 스미싱 문자를 🟡 주의 또는 🔴 위험으로 판정한 비율",
    "- 오탐률: 정상 문자를 🟡 주의 또는 🔴 위험으로 판정한 비율",
    "- 신규 변종 탐지율: 사례 DB에 비슷한 수법이 없는 스미싱(`novel: true`)의 탐지율",
    "- 위험(🔴) 비율: 스미싱 문자 중 🔴 위험까지 올라간 비율",
]


def rate(hits: int, total: int) -> str:
    return f"{hits / total:.1%} ({hits}/{total})" if total else "-"


def p95(values: list[float]) -> float:
    return sorted(values)[max(0, math.ceil(0.95 * len(values)) - 1)]


def run(mode: str, items: list[dict]) -> list[tuple[dict, dict, float]]:
    rows = []
    for item in items:
        started = time.perf_counter()
        result = analyze(item["text"], bool(item.get("from_contact", False)), mode)
        rows.append((item, result, (time.perf_counter() - started) * 1000))
    return rows


def summarize(mode: str, rows: list[tuple[dict, dict, float]]) -> tuple[str, list[str]]:
    smishing = [(i, r) for i, r, _ in rows if i["label"] == "smishing"]
    normal = [(i, r) for i, r, _ in rows if i["label"] != "smishing"]
    novel = [(i, r) for i, r in smishing if i.get("novel")]
    ms = [m for _, _, m in rows]
    flagged = lambda pairs: sum(r["level"] in FLAGGED for _, r in pairs)  # noqa: E731
    table_row = (
        f"| {MODE_LABEL[mode]} | {rate(flagged(smishing), len(smishing))} | {rate(flagged(normal), len(normal))} "
        f"| {rate(flagged(novel), len(novel))} | {rate(sum(r['level'] == 'danger' for _, r in smishing), len(smishing))} "
        f"| {sum(ms) / len(ms):.0f} | {p95(ms):.0f} |"
    )

    def line(kind: str, item: dict, r: dict) -> str:
        sigs = ", ".join(s["name"] for s in r["signals"]) or "-"
        novel_tag = " (novel)" if item.get("novel") else ""
        return f"- {kind} `{item['id']}`{novel_tag}: {r['level']} {r['score']}점 [{sigs}]"

    detail = [f"## {MODE_LABEL[mode]}", ""]
    down = sum(any(s["name"] == "ai_unavailable" for s in r["signals"]) for _, r, _ in rows)
    if down:
        detail += [f"주의: {down}건은 AI 응답 없이 규칙으로만 판정됐어요.", ""]
    misses = [line("놓침", i, r) for i, r in smishing if r["level"] not in FLAGGED]
    alarms = [line("오탐", i, r) for i, r in normal if r["level"] in FLAGGED]
    detail += (misses + alarms) or ["- 놓친 스미싱과 오탐이 없어요."]
    return table_row, detail + [""]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modes", default=",".join(MODES))
    modes = [m.strip() for m in parser.parse_args().modes.split(",") if m.strip()]
    if bad := [m for m in modes if m not in MODES]:
        parser.error(f"unknown mode {bad}; choose from {','.join(MODES)}")

    test_path = ai.DATA_DIR / "test.jsonl"
    items = ai.read_jsonl(test_path)
    if not items:
        sys.exit(f"{test_path} 에 테스트 문자가 없어요.")

    notes = []
    if any(m != "rules" for m in modes) and not ai.alive():
        skipped = [m for m in modes if m != "rules"]
        modes = [m for m in modes if m == "rules"]
        notes.append(f"Ollama({ai.OLLAMA_URL})에 연결할 수 없어 {', '.join(skipped)} 모드는 건너뛰었어요.")
        print(notes[-1])
    if not modes:
        sys.exit("평가할 모드가 없어요.")

    n_smishing = sum(i["label"] == "smishing" for i in items)
    n_novel = sum(i["label"] == "smishing" and bool(i.get("novel")) for i in items)
    summary = f"데이터: `{test_path}` (스미싱 {n_smishing}건 · 정상 {len(items) - n_smishing}건 · 신규 변종 {n_novel}건)"
    table, details = list(HEADER), []
    for mode in modes:
        print(f"{mode} 모드 평가 중... ({len(items)}건)", flush=True)
        row, detail = summarize(mode, run(mode, items))
        table.append(row)
        details += detail

    print("\n" + "\n".join(table))
    report = ["# 문자 지킴이 평가 결과", "", summary, "", *table, "", *LEGEND, ""]
    report += [f"> {n}" for n in notes] + ([""] if notes else []) + details
    OUT.write_text("\n".join(report), encoding="utf-8")
    print(f"\n결과를 {OUT} 에 저장했어요.")


if __name__ == "__main__":
    main()
