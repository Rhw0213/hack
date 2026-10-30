# 📱 문자 지킴이

어르신 휴대폰에 문자가 오면 AI가 먼저 읽고, 스미싱이면 링크를 누르기 전에 경고합니다.

```
android/   문자 감지 → 기기에서 개인정보 가리기 → 판정 API 호출 → 경고 화면 · 신고 · 가족 알림
server/    FastAPI 판정 API: 링크 규칙 + 유사 사례 검색(bge-m3) + Ollama LLM 판정 + 위험도 점수
data/      사례 DB(cases.jsonl), 테스트셋(test.jsonl), 신고로 쌓인 사례(reported.jsonl)
eval/      규칙만 vs 규칙+AI vs 규칙+AI+RAG 성능 비교
```

## 판정 흐름

```
문자 수신 (앱)
 → 개인정보 가리기 (앱: 정규식)            ← 원문은 기기 밖으로 나가지 않음
 → POST /check (마스킹된 문자, 연락처 여부)
 → 서버: 다시 가리기 (정규식 + 선택적 LLM)
 → 링크 규칙 검사 (단축URL · 공식 도메인 비교 · .apk · IP)
 → 유사 사례 검색 (스미싱 Top-3 + 정상 Top-3)
 → qwen3:14b 퓨샷 판정 (새 문자 + 유사 사례 + 링크 결과)
 → 위험도 점수 (표) → 🔴/🟡/🟢
 → 🔴🟡면 exaone3.5:7.8b가 쉬운 말로 설명
```

## 위험도 점수

| 신호 | 점수 |
|---|---|
| AI 판정 스미싱 (확신 0.8 이상) | +5 |
| AI 판정 스미싱 (확신 0.8 미만, 애매하면 위험 쪽으로) | +3 |
| 기존 스미싱 사례와 유사도 0.9 이상 | +3 |
| 단축URL / 비공식 도메인 / IP 주소 링크 | +2 |
| .apk 설치 링크 | +4 |
| 긴급·압박 문구 (오늘까지, 즉시, 정지 …) | +1 |
| 저장된 연락처에서 온 문자 | -2 |

🔴 7점 이상 위험 · 🟡 4~6점 주의 · 🟢 3점 이하 정상

## API 계약

서버와 앱이 같이 지키는 형식입니다. 바꾸면 양쪽을 같이 바꿉니다.

### `POST /check`

요청
```json
{ "text": "[이름]님 건강검진 결과 확인 http://nhis-kr.top/a1", "from_contact": false }
```

응답
```json
{
  "level": "danger",
  "score": 10,
  "title": "사기 문자 같아요",
  "reasons": ["건강보험공단은 이런 주소를 쓰지 않아요", "비슷한 사기 문자가 이미 신고됐어요"],
  "explanation": "공단을 사칭해 가짜 주소로 개인정보를 빼가려는 문자예요. 링크를 누르지 마세요.",
  "category": "공공기관",
  "signals": [{ "name": "ai_smishing", "points": 5, "detail": "qwen3: smishing 0.95" }],
  "similar": [{ "id": "s012", "label": "smishing", "category": "공공기관", "similarity": 0.93 }],
  "masked_text": "[이름]님 건강검진 결과 확인 http://nhis-kr.top/a1",
  "links": ["http://nhis-kr.top/a1"],
  "elapsed_ms": 2140
}
```

- `level`: `"danger"` | `"caution"` | `"safe"`
- `title`: danger `사기 문자 같아요` · caution `조심하세요, 의심스러운 문자예요` · safe `안전한 문자 같아요`
- `reasons`: 화면에 `·` 목록으로 그대로 보여 줄 쉬운 문장. 단정하지 않고 "같아요" 수준으로 씁니다.
- `category`: `택배` | `공공기관` | `가족` | `금융` | `유출통지` | `기타`

### `POST /report`

요청 `{ "text": "<마스킹된 문자>" }` → 응답 `{ "id": "r-1a2b3c4d", "added": true, "total": 231 }`

같은 문자를 두 번 신고하면 `added: false`로 같은 `id`를 돌려줍니다. 신고된 문자는 `data/reported.jsonl`에 스미싱 사례로 쌓이고 바로 유사 사례 검색에 쓰입니다.

### `GET /health`

`{ "ok": true, "cases": 231, "ollama": true }`

## 데이터 형식

`data/cases.jsonl`, `data/reported.jsonl`: 한 줄에 사례 하나.

```json
{"id": "s001", "label": "smishing", "category": "공공기관", "text": "..."}
```

`data/test.jsonl`: 같은 형식에 두 필드를 더합니다. id는 스미싱 `ts001…`, 정상 `tn001…`입니다. `novel: true`는 사례 DB에 비슷한 수법이 없는 신규 변종입니다. `from_contact`는 없으면 `false`입니다.

```json
{"id": "ts002", "label": "smishing", "category": "유출통지", "text": "...", "novel": true, "from_contact": false}
```

### 스미싱 사례 모으기 (기획 담당)

스미싱 문구는 직접 지어내지 않고 공개 사례에서 옮깁니다. KISA 보호나라 · 경찰청 · 뉴스에 공개된 사례 문구를 `cases.jsonl`에 `s001…`로, 테스트용은 `test.jsonl`에 `ts001…`로 한 줄씩 넣습니다. 옮길 때 지킬 것은 다음과 같습니다.

- 링크는 문자열 그대로 두되 절대 열지 않습니다. 실제 악성 주소가 걱정되면 도메인만 바꿔 넣어도 됩니다(`nhis-kr.top`처럼 비슷하게). IP는 `203.0.113.x` 대역을 씁니다.
- 이름 · 전화번호는 `홍길동`, `010-0000-1234`처럼 가짜로 바꿉니다.
- `ts001`은 건강검진 결과 확인 사칭(비슷한 사례가 `cases.jsonl`에 있어야 함), `ts002`는 DB에 없는 "개인정보 유출 확인" 변종(`novel: true`)으로 둡니다.
- 테스트 스미싱 30건 중 10건 이상은 DB에 없는 수법으로 `novel: true`를 붙입니다.
- 다 넣고 `py data\check.py`를 돌립니다. 개수, id, 카테고리, 실제 같은 전화번호, 신규 변종이 DB와 너무 비슷한지를 검사합니다.

## 실행

GPU 서버에는 Ollama만 올리고, 판정 API는 노트북에서 돌립니다. 그러면 휴대폰은 같은 와이파이의 노트북에만 붙으면 되고, 사례 DB와 신고 데이터가 노트북에 남아서 GPU 서버가 삭제돼도(11/1 13:00) 잃는 것이 없습니다.

```
휴대폰 ──와이파이/핫스팟──▶ 노트북 :8000 (FastAPI) ──SSH 터널──▶ GPU 서버 :11434 (Ollama)
```

**1. GPU 서버 (L4 24GB): 모델 세 개 합쳐 약 15GB라 동시에 올라갑니다**

```bash
curl -fsSL https://ollama.com/install.sh | sh        # sudo 권한이 없으면 ollama.com의 linux tarball 사용
OLLAMA_KEEP_ALIVE=24h ollama serve &                  # 모델을 계속 메모리에 둬서 첫 응답 지연을 없앰
ollama pull qwen3:14b && ollama pull exaone3.5:7.8b && ollama pull bge-m3
```

**2. 노트북: 터널과 서버**

```powershell
ssh -N -L 11434:localhost:11434 <user>@<gpu-server>   # VPN 연결 후, 창 하나를 계속 열어 둠
py -m pip install -r server\requirements.txt
cd server; py -m uvicorn app:app --host 0.0.0.0 --port 8000
```

처음 실행하면 사례 전체를 임베딩해서 `data/embeddings.json`에 저장합니다. 다음부터는 새 사례만 임베딩합니다. 휴대폰이 접속하려면 방화벽에서 8000번을 열어야 합니다.

```powershell
New-NetFirewallRule -DisplayName munjajikimi -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
ipconfig   # 노트북 IP 확인 → 앱의 '서버 주소'에 http://<IP>:8000
```

**3. 앱**

```powershell
cd android; .\gradlew.bat assembleDebug
adb install -r app\build\outputs\apk\debug\app-debug.apk   # 또는 APK 파일을 휴대폰으로 옮겨 직접 설치
```

앱을 열고 권한 허용 → 서버 주소 · 가족 번호 입력 → 연결 확인을 누릅니다. SIM이 없으면 '문자 내용 붙여넣기'로 시연합니다.

- 안드로이드 14는 '전체 화면 알림'이 따로 켜져 있어야 잠금 화면 위로 경고가 뜹니다. 권한 허용을 누르면 꺼져 있을 때 설정 화면을 엽니다.
- 직접 설치한 앱은 문자 권한이 회색으로 잠길 수 있습니다. 앱 정보 → ⋮ → '제한된 설정 허용' 후 다시 켜거나 `adb install`로 설치합니다.
- 노트북이 Windows면 `$env:OLLAMA_URL="http://127.0.0.1:11434"`로 지정합니다. `localhost`는 IPv6를 먼저 시도해서 연결이 느려질 수 있습니다.

**4. 성능 측정**

```powershell
py eval\evaluate.py            # 규칙만 / 규칙+AI / 규칙+AI+RAG 표를 출력하고 eval\results.md에 저장
py eval\evaluate.py --modes rules   # Ollama 없이 규칙만
```

## 시연 순서

1. `tn001` 정상 택배 문자 → 🟢 알림 없음
2. `ts001` 건강검진 사칭 → 🔴 경고 + 근거
3. `ts002` DB에 없는 "개인정보 유출 확인" 변종 → 🔴 탐지
4. 신고하기 → `GET /health`의 사례 수가 1 늘어남
5. 가족에게 알리기 → 자녀 폰에 요약 문자 도착

다시 시연하려면 `data/reported.jsonl`을 지우고 서버를 재시작합니다.

## 역할별 파일

| 역할 | 파일 |
|---|---|
| AI | `server/ai.py` (Ollama 호출, 판정 프롬프트, 유사 사례 검색) |
| 백엔드 | `server/rules.py` (가리기, 링크 규칙, 점수표), `server/app.py` (API) |
| 앱 | `android/` |
| 기획·발표 | `data/` (사례 추가 후 `py data\check.py`), `eval/` |

## 한계 (발표 때 언급)

- 플레이 스토어는 문자 권한(RECEIVE_SMS, SEND_SMS)을 엄격히 제한해서 실제 출시엔 정책 검토가 필요합니다. 시연은 APK 직접 설치입니다.
- 아이폰은 앱이 문자를 읽지 못합니다. 메시지 필터(ILMessageFilterExtension)로 확장할 수 있습니다.
- 다른 문자 앱의 링크 클릭 자체를 막을 수는 없어서, 문자가 도착하는 즉시 전체 화면 경고를 띄웁니다.

## 🚫 주의

- 스미싱 링크는 절대 열지 않습니다. 데이터의 링크는 문자열로만 저장하고, 서버도 링크에 접속하지 않습니다.
- 테스트 문자에 실제 개인정보를 넣지 않습니다.
