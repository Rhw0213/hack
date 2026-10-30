"""Rule checks for 문자 지킴이: masking, links, urgency, scoring. Pure functions, no network."""
import ipaddress
import re
from typing import NamedTuple
from urllib.parse import urlsplit

CATEGORIES = ["택배", "공공기관", "가족", "금융", "유출통지", "기타"]


class Signal(NamedTuple):
    name: str
    points: int
    detail: str
    reason: str | None  # easy Korean sentence shown to the elder


POINTS = {
    "ai_smishing": 5,
    "ai_suspicious": 3,
    "similar_smishing": 3,
    "suspicious_link": 2,
    "apk": 4,
    "urgency": 1,
    "from_contact": -2,
    "ai_normal": 0,
    "ai_unavailable": 0,
}
AI_SURE = 0.8
SIMILAR = 0.9

TITLES = {
    "danger": "사기 문자 같아요",
    "caution": "조심하세요, 의심스러운 문자예요",
    "safe": "안전한 문자 같아요",
}
FALLBACK_EXPLANATION = {
    "danger": "사기 문자 같아요. 링크를 누르거나 답장하지 마시고, 가족에게 먼저 물어보세요.",
    "caution": "조심해야 할 문자 같아요. 링크를 누르기 전에 가족에게 먼저 물어보세요.",
    "safe": "위험해 보이는 점은 찾지 못했어요.",
}
AI_FALLBACK_REASON = "AI가 보기에 사기 문자와 비슷해요"


def signal(name: str, detail: str, reason: str | None = None) -> Signal:
    return Signal(name, POINTS[name], detail, reason)


def level_of(score: int) -> str:
    return "danger" if score >= 7 else "caution" if score >= 4 else "safe"


# ---- URLs -------------------------------------------------------------------

TLDS = set(
    "com net org kr top xyz shop site icu cc me ly gl do la io im app link live vip info "
    "online club cn ru biz us to sh tk ml ga cf gq pw ws asia store click fun space website "
    "buzz cyou sbs cfd bond rest work life today world one pro mobi tv jp hk tw vn ph in lol".split()
)
_PATH = r"(?:/[^\s<>\"'가-힣]*)?"
_URL_RE = re.compile(
    r"https?://[^\s<>\"'가-힣]+"
    r"|(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?" + _PATH
    + r"|(?<![a-z0-9@.\-/])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+([a-z]{2,})(?::\d{1,5})?" + _PATH,
    re.I,
)
_TRAIL = ".,;:!?)]}>'\"…"
_KR_SLD = {"co", "or", "go", "ac", "ne", "re", "pe"}


def _find_urls(text: str) -> list[tuple[int, int, str]]:
    found = []
    for m in _URL_RE.finditer(text):
        tld = m.group(1)
        if tld and tld.lower() not in TLDS:
            continue
        url = m.group(0).rstrip(_TRAIL)
        found.append((m.start(), m.start() + len(url), url))
    return found


def extract_urls(text: str) -> list[str]:
    return list(dict.fromkeys(url for _, _, url in _find_urls(text)))


def _without_urls(text: str) -> str:
    out, pos = [], 0
    for start, end, _ in _find_urls(text):
        out.append(text[pos:start])
        pos = end
    return "".join(out) + text[pos:]


def _split(url: str):
    return urlsplit(url if "://" in url else "http://" + url)


def registered_domain(host: str) -> str:
    labels = host.split(".")
    n = 3 if len(labels) >= 3 and labels[-1] == "kr" and labels[-2] in _KR_SLD else 2
    return ".".join(labels[-n:])


# ---- Masking ----------------------------------------------------------------

_NAME_STOP = (
    "고객 회원 기사 선생 사장 교수 선배 후배 담당자 관리자 사모 언니 누나 오빠 부모 어머 아버 할머 "
    "할아버 아드 동생 자녀 가족 주인 환자 보호자 가입자 신청자 이용자 구매자 납부자 수신자 대상자 "
    "수령인 신청인 대표 부장 과장 차장 팀장 실장 원장 회장 소장 반장 이장 국장 점장 이사 대리 주임 "
    "감독 작가 의사 판사 검사 목사 변호사 세무사 기자 우리 모든 신규 기존 우수 소중한 존경하는 "
    "사랑하는 친애하는"
).split()


def _account(m: re.Match) -> str:
    digits = sum(ch.isdigit() for ch in m.group(0))
    return "[계좌번호]" if 10 <= digits <= 14 else m.group(0)


def _name(m: re.Match) -> str:
    word = m.group(1)
    return word if word.endswith(tuple(_NAME_STOP)) else "[이름]"


# Order matters: longer, more specific numbers first so a phone is never read as an account.
_MASKS = [
    (re.compile(r"(?<![\d-])\d{6}-?[1-4]\d{6}(?![\d-])"), "[주민번호]"),
    (re.compile(r"(?<![\d-])\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}(?![\d-])"), "[카드번호]"),
    (re.compile(r"(인증번호|승인번호|인증코드)(\s*(?:는|:)?\s*)(?:\[\s*\d{4,8}\s*\]|\d{4,8}(?!\d))"), r"\1\2[인증번호]"),
    (re.compile(r"(?<![\d-])01[016789][-. ]?\d{3,4}[-. ]?\d{4}(?![\d-])"), "[전화번호]"),
    (re.compile(r"(?<![\d-])0\d{1,2}-\d{3,4}-\d{4}(?![\d-])"), "[전화번호]"),
    (re.compile(r"(?<![\d-])\d+(?:-\d+)*(?![\d-])"), _account),
    (re.compile(r"(?<![가-힣])((?:(?!님)[가-힣]){2,4}?)(?=\s?고객님)"), _name),
    (re.compile(r"(?<![가-힣])((?:(?!님)[가-힣]){2,4})(?=님)"), _name),
]


def mask(text: str) -> str:
    urls = _find_urls(text)
    holders = [f"{chr(0xE100 + i)}" for i in range(len(urls))]
    out, pos = [], 0
    for (start, end, _), holder in zip(urls, holders):
        out += [text[pos:start], holder]
        pos = end
    masked = "".join(out) + text[pos:]
    for pattern, repl in _MASKS:
        masked = pattern.sub(repl, masked)
    for (_, _, url), holder in zip(urls, holders):
        masked = masked.replace(holder, url)
    return masked


# ---- Links ------------------------------------------------------------------

OFFICIAL = [
    ("건강보험공단", ["건강보험", "건보", "국민건강", "건강검진"], ["nhis.or.kr"]),
    ("국민연금공단", ["국민연금"], ["nps.or.kr"]),
    ("국세청", ["국세청", "홈택스"], ["nts.go.kr", "hometax.go.kr"]),
    ("정부24", ["정부24"], ["gov.kr"]),
    ("경찰청", ["경찰"], ["police.go.kr"]),
    ("검찰청", ["검찰"], ["spo.go.kr"]),
    ("법원", ["법원"], ["scourt.go.kr"]),
    ("도로교통공단", ["도로교통", "교통위반", "범칙금", "과태료"], ["koroad.or.kr", "efine.go.kr"]),
    ("우체국", ["우체국"], ["epost.go.kr", "koreapost.go.kr"]),
    ("질병관리청", ["질병관리"], ["kdca.go.kr"]),
    ("개인정보보호위원회", ["개인정보보호위원회"], ["pipc.go.kr"]),
    ("한국인터넷진흥원", ["인터넷진흥원", "KISA"], ["kisa.or.kr", "boho.or.kr"]),
    ("금융감독원", ["금감원", "금융감독원"], ["fss.or.kr"]),
    ("한국도로공사", ["하이패스", "도로공사"], ["ex.co.kr"]),
    ("CJ대한통운", ["대한통운"], ["cjlogistics.com"]),
    ("한진택배", ["한진"], ["hanjin.com", "hanjin.co.kr"]),
    ("롯데택배", ["롯데택배", "롯데글로벌"], ["lotteglogis.com"]),
    ("로젠택배", ["로젠"], ["ilogen.com"]),
    ("쿠팡", ["쿠팡"], ["coupang.com"]),
    ("KB국민은행", ["국민은행", "KB국민"], ["kbstar.com", "kbcard.com"]),
    ("신한", ["신한"], ["shinhan.com", "shinhancard.com"]),
    ("우리은행", ["우리은행", "우리카드"], ["wooribank.com", "wooricard.com"]),
    ("하나은행", ["하나은행", "하나카드"], ["hanabank.com", "kebhana.com", "hanacard.co.kr"]),
    ("NH농협", ["농협"], ["nonghyup.com"]),
    ("카카오뱅크", ["카카오뱅크"], ["kakaobank.com"]),
    ("카카오", ["카카오"], ["kakao.com", "kakaocorp.com"]),
    ("토스", ["토스"], ["toss.im"]),
    ("네이버", ["네이버"], ["naver.com"]),
    ("SK텔레콤", ["SK텔레콤", "SKT"], ["sktelecom.com", "tworld.co.kr"]),
    ("KT", ["KT "], ["kt.com"]),
    ("LG유플러스", ["유플러스"], ["lguplus.com"]),
    ("삼성카드", ["삼성카드"], ["samsungcard.com"]),
    ("현대카드", ["현대카드"], ["hyundaicard.com"]),
]
OFFICIAL_DOMAINS = {d for _, _, domains in OFFICIAL for d in domains}
SHORT_HOSTS = set(
    "bit.ly han.gl me2.do vo.la url.kr t.ly tinyurl.com goo.gl ow.ly is.gd buly.kr c11.kr "
    "kko.to naver.me t.co rebrand.ly cutt.ly shorturl.at zrr.kr lrl.kr".split()
)
KIND_LABEL = {
    "official": "공식 기관 주소",
    "short": "단축 링크(진짜 주소를 숨김)",
    "ip": "숫자로 된 IP 주소",
    "unofficial": "공식 기관 주소가 아님",
}
APK_REASON = "앱 설치 파일(.apk) 링크예요. 절대 설치하지 마세요"


class LinkCheck(NamedTuple):
    url: str
    kind: str  # a KIND_LABEL key
    apk: bool


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def check_link(url: str) -> LinkCheck:
    parts = _split(url)
    host = (parts.hostname or "").rstrip(".")
    if _is_ip(host):
        kind = "ip"
    elif host.removeprefix("www.") in SHORT_HOSTS:
        kind = "short"
    elif registered_domain(host) in OFFICIAL_DOMAINS or host.endswith(".go.kr"):
        kind = "official"
    else:
        kind = "unofficial"
    return LinkCheck(url, kind, ".apk" in (parts.path + "?" + parts.query).lower())


def describe(check: LinkCheck) -> str:
    return f"{check.url}: {KIND_LABEL[check.kind]}" + (", 앱 설치 파일(.apk)" if check.apk else "")


def mentioned_institution(text: str) -> str | None:
    plain = _without_urls(text)
    return next((name for name, keywords, _ in OFFICIAL if any(k in plain for k in keywords)), None)


def _topic(name: str) -> str:
    last = name[-1]
    if "가" <= last <= "힣":
        return "은" if (ord(last) - ord("가")) % 28 else "는"
    return "은" if last.upper() in "LMNR" else "는"


def _link_reason(kind: str, institution: str | None) -> str:
    if kind == "short":
        return "진짜 주소를 숨기는 단축 링크예요"
    if kind == "ip":
        return "숫자로 된 이상한 주소예요"
    if institution:
        return f"{institution}{_topic(institution)} 이런 주소를 쓰지 않아요"
    return "공식 주소가 아닌 링크가 있어요"


def link_signals(checks: list[LinkCheck], text: str) -> list[Signal]:
    found = []
    bad = [c for c in checks if c.kind != "official"]
    if bad:
        detail = ", ".join(f"{c.url} ({KIND_LABEL[c.kind]})" for c in bad)
        found.append(signal("suspicious_link", detail, _link_reason(bad[0].kind, mentioned_institution(text))))
    apks = [c.url for c in checks if c.apk]
    if apks:
        found.append(signal("apk", ", ".join(apks), APK_REASON))
    return found


# ---- Words and context --------------------------------------------------------

URGENCY = [
    "오늘까지", "즉시", "정지", "긴급", "마감", "미납", "체납", "압류", "만료",
    "지금바로", "차단", "소멸", "반송", "영장", "출석", "24시간내", "24시간이내",
]


def urgency_signal(text: str) -> Signal | None:
    compact = re.sub(r"\s+", "", text)
    hits = [w for w in URGENCY if w in compact]
    return signal("urgency", ", ".join(hits), "서두르라고 재촉하는 말이 있어요") if hits else None


def contact_signal() -> Signal:
    return signal("from_contact", "저장된 연락처에서 온 문자")


def similar_signal(case_id: str, similarity: float) -> Signal | None:
    if similarity < SIMILAR:
        return None
    return signal("similar_smishing", f"{case_id} 유사도 {similarity:.2f}", "비슷한 사기 문자가 이미 신고됐어요")


def judge_signal(label: str, confidence: float, detail: str) -> Signal:
    if label != "smishing":
        return signal("ai_normal", detail)
    return signal("ai_smishing" if confidence >= AI_SURE else "ai_suspicious", detail)
