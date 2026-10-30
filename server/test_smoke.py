"""Smoke test without Ollama or pytest. Run: py server\\test_smoke.py"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="munja-"))
os.environ.update(DATA_DIR=str(TMP), OLLAMA_URL="http://127.0.0.1:9", MASK_LLM="0")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ai  # noqa: E402
import app  # noqa: E402
import rules  # noqa: E402

CASES = [
    {"id": "s1", "label": "smishing", "category": "공공기관", "text": "[국민건강보험] 건강검진 결과 확인 http://nhis-kr.top/b2"},
    {"id": "s2", "label": "smishing", "category": "택배", "text": "택배 주소 불일치 확인 http://cj-dlv.xyz/q"},
    {"id": "n1", "label": "normal", "category": "택배", "text": "택배가 문 앞에 도착했습니다"},
    {"id": "n2", "label": "normal", "category": "기타", "text": "아빠 오늘 저녁 같이 먹어요"},
]
(TMP / "cases.jsonl").write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in CASES), encoding="utf-8")
SAMPLE = "[이름]님 건강검진 결과 확인 http://nhis-kr.top/a1"


def names(result):
    return {s["name"] for s in result["signals"]}


def test_masking():
    url = "https://nhis-kr.top/9001011234567?tel=01012345678"
    text = (f"홍길동님 고객님 연락처 010-1234-5678 계좌 110-123-456789 주민 900101-1234567 "
            f"인증번호 [482913] 확인 {url} 문의 1588-1234")
    assert rules.mask(text) == (
        f"[이름]님 고객님 연락처 [전화번호] 계좌 [계좌번호] 주민 [주민번호] "
        f"인증번호 [인증번호] 확인 {url} 문의 1588-1234"
    ), rules.mask(text)
    assert rules.mask("192.168.10.20:8080/01012345678 로 접속") == "192.168.10.20:8080/01012345678 로 접속"
    assert rules.mask("Mr.Kim 1.5kg 배송") == "Mr.Kim 1.5kg 배송"
    assert rules.extract_urls("Mr.Kim 1.5kg 배송 bit.ly/x.") == ["bit.ly/x"]


def link_names(text):
    return {s.name for s in rules.link_signals([rules.check_link(u) for u in rules.extract_urls(text)], text)}


def test_links():
    short = rules.link_signals([rules.check_link("https://bit.ly/3xYz")], "택배 확인 https://bit.ly/3xYz")
    assert [(s.name, s.reason) for s in short] == [("suspicious_link", "진짜 주소를 숨기는 단축 링크예요")]
    fake = rules.link_signals([rules.check_link("http://nhis-kr.top/a1")], SAMPLE)
    assert [(s.name, s.reason) for s in fake] == [("suspicious_link", "건강보험공단은 이런 주소를 쓰지 않아요")]
    assert link_names("앱 설치 http://dl-safe.com/app.apk") == {"suspicious_link", "apk"}
    ip = rules.link_signals([rules.check_link("http://45.12.3.9/login")], "로그인 http://45.12.3.9/login")
    assert [(s.name, s.reason) for s in ip] == [("suspicious_link", "숫자로 된 이상한 주소예요")]
    assert link_names("건강보험 고지서 확인 https://www.nhis.or.kr/nhis/index.do") == set()
    assert link_names("정부24 안내 https://www.gov.kr/portal") == set()
    assert rules.check_link("nhis.or.kr.evil.top").kind == "unofficial"
    assert rules.check_link("https://nhis.or.kr.verify-top.com/x").kind == "unofficial"
    two = rules.link_signals([rules.check_link(u) for u in ("bit.ly/a", "han.gl/b")], "bit.ly/a han.gl/b")
    assert [s.points for s in two] == [2], "suspicious_link counts once per message"


def test_thresholds():
    assert [rules.level_of(s) for s in (3, 4, 6, 7)] == ["safe", "caution", "caution", "danger"]


def test_rules_mode_sends_nothing_to_ollama():
    real = ai._request
    ai._request = lambda *a, **k: (_ for _ in ()).throw(AssertionError("rules mode called Ollama"))
    try:
        r = app.analyze("[긴급] 택배 반송 즉시 확인 https://bit.ly/3xYz", mode="rules")
    finally:
        ai._request = real
    assert names(r) == {"suspicious_link", "urgency"} and r["score"] == 3 and r["level"] == "safe", r


def test_ollama_down_still_answers():
    assert ai.alive() is False
    r = app.analyze(SAMPLE, mode="full")
    assert names(r) == {"suspicious_link", "ai_unavailable"}, r["signals"]
    assert r["level"] == "safe" and r["score"] == 2 and r["category"] == "기타"
    assert r["reasons"] == ["건강보험공단은 이런 주소를 쓰지 않아요"]
    assert r["links"] == ["http://nhis-kr.top/a1"] and r["masked_text"] == SAMPLE
    assert app.health_route() == {"ok": True, "cases": 4, "ollama": False}


JUDGE_REPLY = {"reason": "공단을 사칭해 가짜 주소로 유도함", "label": "smishing", "confidence": 0.95, "category": "공공기관"}
EXPLAIN_REPLY = {"explanation": "공단인 척하는 가짜 주소 같아요. 누르지 마세요.", "extra_reason": ""}
CHATS = []


def fake_embed(texts):
    topics = ["건강검진", "택배", "저녁"]
    return [[1.0 if t in x else 0.0 for t in topics] + [0.0 if any(t in x for t in topics) else 1.0] for x in texts]


def fake_chat(model, messages, schema=None, temperature=0.0, think=None):
    CHATS.append({"model": model, "messages": messages, "schema": schema, "think": think})
    if schema is ai.JUDGE_SCHEMA:
        return "<think></think>" + json.dumps(JUDGE_REPLY, ensure_ascii=False)
    return json.dumps(EXPLAIN_REPLY, ensure_ascii=False)


def test_full_mode_reaches_danger():
    CHATS.clear()
    r = app.analyze(SAMPLE, mode="full")
    assert names(r) == {"suspicious_link", "similar_smishing", "ai_smishing"}, r["signals"]
    assert r["score"] == 10 and r["level"] == "danger" and r["title"] == "사기 문자 같아요"
    assert r["reasons"] == ["비슷한 사기 문자가 이미 신고됐어요", "건강보험공단은 이런 주소를 쓰지 않아요"], r["reasons"]
    assert r["explanation"] == EXPLAIN_REPLY["explanation"] and r["category"] == "공공기관"
    assert r["similar"][0] == {"id": "s1", "label": "smishing", "category": "공공기관", "similarity": 1.0}
    judge_call = next(c for c in CHATS if c["schema"] is ai.JUDGE_SCHEMA)
    prompt = judge_call["messages"][0]["content"]
    assert judge_call["model"] == ai.JUDGE_MODEL and judge_call["think"] is False
    assert CASES[0]["text"] in prompt and "[normal]" in prompt, "retrieved cases reach the judge prompt"
    assert "http://nhis-kr.top/a1: 공식 기관 주소가 아님" in prompt


def test_ai_mode_skips_retrieval():
    CHATS.clear()
    r = app.analyze(SAMPLE, mode="ai")
    assert names(r) == {"suspicious_link", "ai_smishing"} and r["similar"] == [] and r["score"] == 7
    assert "참고 사례" not in CHATS[0]["messages"][0]["content"]


def test_report_is_idempotent():
    text = "홍길동님 [국민연금] 미수령 환급금 확인 http://nps-refund.top/k"
    masked = "[이름]님 [국민연금] 미수령 환급금 확인 http://nps-refund.top/k"
    expected_id = "r-" + hashlib.sha1(masked.encode()).hexdigest()[:8]
    first = app.report_route(app.ReportIn(text=text))
    second = app.report_route(app.ReportIn(text=text))
    assert first == {"id": expected_id, "added": True, "total": 5}, first
    assert second == {"id": expected_id, "added": False, "total": 5}, second
    rows = ai.read_jsonl(TMP / "reported.jsonl")
    assert [(r["id"], r["label"], r["category"], r["text"]) for r in rows] == [(expected_id, "smishing", "공공기관", masked)]
    assert ai.Store(TMP).has(expected_id) and ai.Store(TMP).count() == 5, "a restart sees the report"
    smishing, _ = ai.STORE.search(masked)
    assert smishing[0][0]["id"] == expected_id, "a report is searchable right away"


if __name__ == "__main__":
    try:
        test_masking()
        test_links()
        test_thresholds()
        test_rules_mode_sends_nothing_to_ollama()
        test_ollama_down_still_answers()
        ai.embed, ai.chat = fake_embed, fake_chat
        test_full_mode_reaches_danger()
        test_ai_mode_skips_retrieval()
        test_report_is_idempotent()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print("smoke ok")
