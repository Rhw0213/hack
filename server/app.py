"""문자 지킴이 judgment API. Run: cd server; py -m uvicorn app:app --host 0.0.0.0 --port 8000"""
import hashlib
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field

import ai
import rules

MODES = ("rules", "ai", "full")


def mask_text(text: str, use_llm: bool) -> str:
    masked = rules.mask(text)
    if use_llm and ai.MASK_LLM:
        try:
            masked = ai.llm_mask(masked)
        except ai.OllamaError:
            pass
    return masked


def analyze(text: str, from_contact: bool = False, mode: str = "full") -> dict:
    """mode: "rules" (no Ollama), "ai" (rules + zero-shot judge), "full" (rules + retrieval + few-shot judge)."""
    started = time.perf_counter()
    use_ai = mode != "rules"
    masked = mask_text(text, use_ai)
    urls = rules.extract_urls(masked)
    checks = [rules.check_link(u) for u in urls]

    signals = rules.link_signals(checks, masked)
    if urgency := rules.urgency_signal(masked):
        signals.append(urgency)
    if from_contact:
        signals.append(rules.contact_signal())

    smishing, normal, verdict = [], [], None
    if use_ai:
        try:
            if mode == "full":
                smishing, normal = ai.STORE.search(masked)
                if smishing and (similar := rules.similar_signal(smishing[0][0]["id"], smishing[0][1])):
                    signals.append(similar)
            verdict = ai.judge(masked, [rules.describe(c) for c in checks], smishing, normal)
            detail = f"{ai.JUDGE_MODEL.split(':')[0]}: {verdict.label} {verdict.confidence:.2f} · {verdict.reason}"
            signals.append(rules.judge_signal(verdict.label, verdict.confidence, detail))
        except ai.OllamaError as e:
            signals.append(rules.signal("ai_unavailable", f"AI를 쓸 수 없어 규칙으로만 판정했어요 ({e})"))

    score = sum(s.points for s in signals)
    level = rules.level_of(score)
    reasons = list(dict.fromkeys(s.reason for s in sorted(signals, key=lambda s: -s.points) if s.reason))
    explanation = rules.FALLBACK_EXPLANATION[level]
    if verdict and level != "safe":
        try:
            written, extra = ai.explain(masked, reasons, verdict.reason)
            explanation = written or explanation
            if extra and extra not in reasons:
                reasons.append(extra)
        except ai.OllamaError:
            pass
    if level != "safe" and not reasons:
        reasons.append(rules.AI_FALLBACK_REASON)

    category = (verdict and verdict.category) or (smishing[0][0]["category"] if smishing else None) or "기타"
    similar_out = sorted(
        ({"id": c["id"], "label": c["label"], "category": c["category"], "similarity": round(s, 3)}
         for c, s in smishing + normal),
        key=lambda d: -d["similarity"],
    )
    return {
        "level": level,
        "score": score,
        "title": rules.TITLES[level],
        "reasons": reasons,
        "explanation": explanation,
        "category": category,
        "signals": [{"name": s.name, "points": s.points, "detail": s.detail} for s in signals],
        "similar": similar_out,
        "masked_text": masked,
        "links": urls,
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
    }


def report(text: str) -> dict:
    masked = mask_text(text, use_llm=True)
    case_id = "r-" + hashlib.sha1(masked.encode()).hexdigest()[:8]
    if ai.STORE.has(case_id):
        return {"id": case_id, "added": False, "total": ai.STORE.count()}
    try:
        category = ai.judge(masked, [rules.describe(rules.check_link(u)) for u in rules.extract_urls(masked)]).category
    except ai.OllamaError:
        category = None
    added = ai.STORE.add({"id": case_id, "label": "smishing", "category": category or "기타", "text": masked})
    return {"id": case_id, "added": added, "total": ai.STORE.count()}


@asynccontextmanager
async def lifespan(_: FastAPI):
    threading.Thread(target=ai.STORE.warm, daemon=True).start()
    yield


app = FastAPI(title="문자 지킴이", lifespan=lifespan)


class CheckIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    from_contact: bool = False


class ReportIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


@app.post("/check")
def check_route(req: CheckIn) -> dict:
    return analyze(req.text, req.from_contact)


@app.post("/report")
def report_route(req: ReportIn) -> dict:
    return report(req.text)


@app.get("/health")
def health_route() -> dict:
    return {"ok": True, "cases": ai.STORE.count(), "ollama": ai.alive()}
