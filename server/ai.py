"""Ollama boundary: embeddings and the case store, the qwen3 judge, the exaone explanation."""
import hashlib
import heapq
import http.client
import json
import math
import os
import threading
import urllib.request
from pathlib import Path
from typing import NamedTuple

import rules

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "qwen3:14b")
EXPLAIN_MODEL = os.environ.get("EXPLAIN_MODEL", "exaone3.5:7.8b")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-m3")
MASK_LLM = os.environ.get("MASK_LLM", "0") == "1"
DATA_DIR = Path(os.environ.get("DATA_DIR") or Path(__file__).resolve().parent.parent / "data")

# Ollama is local; a proxy from the environment would swallow localhost requests.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class OllamaError(Exception):
    """Ollama is unreachable or answered something unusable."""


def _request(path: str, body: dict | None, timeout: float) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(OLLAMA_URL + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (OSError, ValueError, http.client.HTTPException) as e:
        raise OllamaError(f"{path}: {e}") from e


def alive() -> bool:
    try:
        _request("/api/tags", None, timeout=2)
        return True
    except OllamaError:
        return False


def _unit(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def embed(texts: list[str]) -> list[list[float]]:
    resp = _request("/api/embed", {"model": EMBED_MODEL, "input": texts}, timeout=120)
    vecs = resp.get("embeddings")
    if not isinstance(vecs, list) or len(vecs) != len(texts):
        raise OllamaError(f"/api/embed: expected {len(texts)} embeddings, got {str(resp)[:200]}")
    return [_unit(v) for v in vecs]


def chat(model: str, messages: list[dict], schema: dict | None = None,
         temperature: float = 0.0, think: bool | None = None) -> str:
    body = {"model": model, "messages": messages, "stream": False, "options": {"temperature": temperature}}
    if schema is not None:
        body["format"] = schema
    if think is not None:
        body["think"] = think
    resp = _request("/api/chat", body, timeout=180)
    try:
        return resp["message"]["content"]
    except (KeyError, TypeError) as e:
        raise OllamaError(f"/api/chat: unexpected response {str(resp)[:200]}") from e


def _json_object(content: str) -> dict:
    try:
        obj = json.loads(content[content.index("{"): content.rindex("}") + 1])
    except ValueError as e:
        raise OllamaError(f"model did not answer JSON: {content[:200]!r}") from e
    if not isinstance(obj, dict):
        raise OllamaError(f"model did not answer a JSON object: {content[:200]!r}")
    return obj


# ---- Case store -----------------------------------------------------------------

def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("text"), str) and row.get("id"):
            rows.append(row)
    return rows


def _key(text: str) -> str:
    return hashlib.sha1(f"{EMBED_MODEL}\n{text}".encode()).hexdigest()


class Store:
    """Cases from cases.jsonl + reported.jsonl, with embeddings cached in embeddings.json."""

    BATCH = 32

    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.lock = threading.RLock()
        self.items: list[tuple[dict, str]] | None = None  # (case with masked text, embedding key)
        self.cache: dict[str, list[float]] = {}

    @staticmethod
    def _item(case: dict) -> tuple[dict, str]:
        text = rules.mask(case["text"])
        category = case.get("category") if case.get("category") in rules.CATEGORIES else "기타"
        label = "smishing" if case.get("label") == "smishing" else "normal"
        return {**case, "text": text, "category": category, "label": label}, _key(text)

    def _load(self) -> list[tuple[dict, str]]:
        if self.items is None:
            rows = read_jsonl(self.dir / "cases.jsonl") + read_jsonl(self.dir / "reported.jsonl")
            self.items = [self._item(r) for r in rows]
            try:
                self.cache = json.loads((self.dir / "embeddings.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.cache = {}
        return self.items

    def _save_cache(self):
        path = self.dir / "embeddings.json"
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(self.cache), encoding="utf-8")
        os.replace(tmp, path)

    def _embed_missing(self):
        missing = list(dict.fromkeys((k, c["text"]) for c, k in self._load() if k not in self.cache))
        for i in range(0, len(missing), self.BATCH):
            batch = missing[i:i + self.BATCH]
            self.cache.update(zip((k for k, _ in batch), embed([t for _, t in batch])))
            self._save_cache()

    def warm(self):
        try:
            with self.lock:
                self._embed_missing()
        except OllamaError as e:
            print(f"[store] embeddings not ready, will retry on first request: {e}")

    def count(self) -> int:
        with self.lock:
            return len(self._load())

    def has(self, case_id: str) -> bool:
        with self.lock:
            return any(c["id"] == case_id for c, _ in self._load())

    def search(self, text: str, k: int = 3) -> tuple[list[tuple[dict, float]], list[tuple[dict, float]]]:
        """Top-k smishing and top-k normal cases by cosine similarity."""
        query = embed([text])[0]
        with self.lock:
            self._embed_missing()
            # ponytail: brute-force cosine in pure Python over every case. Fine for hundreds of
            # cases; past ~10k swap to FAISS/Chroma.
            scored = [(c, sum(a * b for a, b in zip(query, self.cache[key]))) for c, key in self.items]
        top = {label: heapq.nlargest(k, (s for s in scored if s[0]["label"] == label), key=lambda s: s[1])
               for label in ("smishing", "normal")}
        return top["smishing"], top["normal"]

    def add(self, case: dict) -> bool:
        """Append a reported case. Returns False when its id is already stored."""
        with self.lock:
            if self.has(case["id"]):
                return False
            path = self.dir / "reported.jsonl"
            prefix = "\n" if path.exists() and path.stat().st_size and not path.read_bytes().endswith(b"\n") else ""
            with path.open("a", encoding="utf-8") as f:
                f.write(prefix + json.dumps(case, ensure_ascii=False) + "\n")
            self.items.append(self._item(case))
            try:
                self._embed_missing()
            except OllamaError:
                pass  # the next search embeds it
            return True


STORE = Store(DATA_DIR)


# ---- Judge ----------------------------------------------------------------------

class Verdict(NamedTuple):
    label: str
    confidence: float
    category: str | None
    reason: str


# reason comes first so the model writes its grounds before committing to a label.
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "label": {"type": "string", "enum": ["smishing", "normal"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "category": {"type": "string", "enum": rules.CATEGORIES},
    },
    "required": ["reason", "label", "confidence", "category"],
}

JUDGE_SYSTEM = """당신은 한국어 문자 메시지가 스미싱(문자 사기)인지 판정하는 보안 전문가입니다.
받는 사람은 70대 어르신입니다. 개인정보는 [이름], [전화번호], [계좌번호] 같은 표시로 미리 가려 두었습니다. 가려진 표시 자체는 사기의 근거가 아닙니다.

판정 기준:
- 링크를 누르게 하거나, 앱을 설치하게 하거나, 개인정보·금융정보 입력, 송금, 낯선 번호로 전화를 요구하면 스미싱일 가능성이 큽니다.
- 공공기관·택배사·금융사·가족을 사칭하고 서두르게 만드는 말투는 스미싱의 전형적인 특징입니다.
- 공식 주소만 쓰는 안내, 결제·배송 완료 같은 단순 알림, 아는 사람과의 일상 대화는 정상입니다.

category는 문자의 주제입니다: 택배, 공공기관(정부·공단·경찰·검찰·법원), 가족(가족·지인 사칭 포함), 금융(은행·카드·대출·투자), 유출통지(개인정보 유출·해킹 안내), 기타.

링크 검사 결과(서버가 규칙으로 확인한 사실):
{links}
{examples}
JSON으로만 답하세요. reason에는 판단 근거를 한국어 한 문장으로 씁니다. confidence는 0에서 1 사이 숫자입니다."""


def _examples(smishing: list[tuple[dict, float]], normal: list[tuple[dict, float]]) -> str:
    if not smishing and not normal:
        return ""
    lines = ["", "참고 사례(비슷한 문자를 검색한 결과입니다. 새 문자와 수법이 같을 때만 참고하세요):"]
    lines += [f"[{c['label']}] {c['text']}" for c, _ in sorted(smishing + normal, key=lambda s: -s[1])]
    return "\n".join(lines) + "\n"


def judge_messages(text: str, link_notes: list[str], smishing=(), normal=()) -> list[dict]:
    system = JUDGE_SYSTEM.format(
        links="\n".join(f"- {n}" for n in link_notes) or "- 링크 없음",
        examples=_examples(list(smishing), list(normal)),
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": f"새 문자:\n{text}"}]


def parse_verdict(content: str) -> Verdict:
    obj = _json_object(content)
    if obj.get("label") not in ("smishing", "normal"):
        raise OllamaError(f"judge label missing: {content[:200]!r}")
    try:
        confidence = min(max(float(obj.get("confidence", 0.5)), 0.0), 1.0)
    except (TypeError, ValueError):
        confidence = 0.5
    category = obj.get("category") if obj.get("category") in rules.CATEGORIES else None
    return Verdict(obj["label"], confidence, category, str(obj.get("reason") or "").strip())


def judge(text: str, link_notes: list[str], smishing=(), normal=()) -> Verdict:
    messages = judge_messages(text, link_notes, smishing, normal)
    return parse_verdict(chat(JUDGE_MODEL, messages, schema=JUDGE_SCHEMA, temperature=0, think=False))


# ---- Explanation and optional LLM masking ------------------------------------------

EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {"explanation": {"type": "string"}, "extra_reason": {"type": "string"}},
    "required": ["explanation", "extra_reason"],
}

EXPLAIN_SYSTEM = """당신은 70대 어르신께 방금 받은 문자가 왜 위험해 보이는지 알려 드리는 도우미입니다.

explanation 쓰는 법:
- 존댓말로, 짧은 문장 1~2개로 씁니다.
- 어려운 말(URL, 도메인, 스미싱, 피싱, 악성코드, APK 같은 말)은 쓰지 않습니다. 링크는 '주소'라고 합니다.
- 단정하지 않습니다. '~같아요', '~수 있어요'처럼 말합니다.
- 하지 말아야 할 행동(주소 누르기, 앱 설치, 전화하기, 돈 보내기 중 해당하는 것)을 알려 드립니다.

extra_reason 쓰는 법:
- 'AI 판단 근거'에 '이미 보여 드린 이유'에 없는 새로운 내용이 있을 때만, 그 내용을 쉬운 한 문장으로 씁니다. 같은 말투 규칙을 지킵니다.
- 새로운 내용이 없으면 빈 문자열로 둡니다."""


def explain(text: str, reasons: list[str], judge_reason: str) -> tuple[str, str]:
    """Returns (explanation, extra_reason); extra_reason is empty when it adds nothing."""
    shown = "\n".join(f"- {r}" for r in reasons) or "- 없음"
    user = f"문자:\n{text}\n\n이미 보여 드린 이유:\n{shown}\n\nAI 판단 근거: {judge_reason or '없음'}"
    messages = [{"role": "system", "content": EXPLAIN_SYSTEM}, {"role": "user", "content": user}]
    obj = _json_object(chat(EXPLAIN_MODEL, messages, schema=EXPLAIN_SCHEMA, temperature=0.2))
    return str(obj.get("explanation") or "").strip(), str(obj.get("extra_reason") or "").strip()


MASK_SYSTEM = """다음 문자에서 사람 이름은 [이름]으로, 주소(집 주소·도로명 주소)는 [주소]로 바꾸세요.
그 밖의 글자, 링크, 숫자, 띄어쓰기, [전화번호] 같은 표시는 한 글자도 바꾸지 마세요.
바꾼 문자만 출력하세요."""


def llm_mask(text: str) -> str:
    """Second masking pass for names and addresses; keeps the input if the model touched a link."""
    messages = [{"role": "system", "content": MASK_SYSTEM}, {"role": "user", "content": text}]
    out = chat(EXPLAIN_MODEL, messages, temperature=0).strip()
    if not out or any(url not in out for url in rules.extract_urls(text)):
        return text
    return out
