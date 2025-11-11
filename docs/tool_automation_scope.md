# 도구 자동화 수정 범위 분석

## 📌 수정 대상 파일

### 1. **새로 생성되는 파일** ✅ (추가만 하면 됨)

#### 인프라 레벨 (전체 공통)
```
infra/core/
├── tool_registry.py          # [신규] 도구 레지스트리 클래스
├── templates/
│   ├── handlers.jinja2       # [신규] 핸들러 템플릿
│   └── registry.jinja2        # [신규] 레지스트리 템플릿

scripts/
├── generate_handlers.py      # [신규] 코드 생성 스크립트
└── generate_all.py          # [신규] 전체 모듈 일괄 생성

tests/
├── unit/
│   └── test_tool_registry.py # [신규] 레지스트리 테스트
├── integration/
│   └── test_generation.py    # [신규] 생성 테스트
└── regression/
    └── test_compatibility.py # [신규] 호환성 테스트
```

#### 모듈별 (각 모듈마다)
```
modules/[module_name]/
└── tool_config.yaml          # [신규] 도구 설정 파일
```

**영향도**: 🟢 낮음 - 기존 코드 변경 없음

---

### 2. **자동 생성으로 대체되는 파일** ⚠️ (백업 후 교체)

```
modules/[module_name]/
├── handlers.py               # [대체] 자동 생성된 파일로 교체
└── handlers_original.py      # [백업] 원본 보관
```

**현재 handlers.py의 역할**:
- `handle_list_tools()`: 도구 목록 정의
- `handle_call_tool()`: 도구 라우팅
- `call_tool_as_dict()`: HTTP용 변환

**자동 생성 후**:
- YAML + 템플릿으로 완전 자동 생성
- 비즈니스 로직은 tools.py로 이동

**영향도**: 🟡 중간 - 기존 파일 대체 (백업 필요)

---

### 3. **수정 불필요 파일** ✅ (그대로 유지)

```
modules/[module_name]/
├── tools.py                  # [유지] 비즈니스 로직
├── schemas.py                # [유지] Pydantic 모델
├── prompts.py                # [유지] 프롬프트 정의
├── [service]_handler.py      # [유지] 서비스별 핸들러
├── entrypoints/
│   ├── stdio_server.py      # [유지] MCP 서버 엔트리
│   └── http_server.py        # [유지] HTTP 서버
└── mcp_server/
    └── http_server.py        # [유지] HTTP 스트리밍
```

**영향도**: 🟢 없음 - 변경 없음

---

## 📊 모듈별 수정 범위

### 전체 14개 모듈 영향도 분석

| 모듈 | 도구 수 | handlers.py 라인 수 | 수정 난이도 | 우선순위 |
|------|---------|-------------------|------------|----------|
| **mail_iacs** | 4 | 312줄 | ⭐⭐ 쉬움 | 1 (파일럿) |
| **onedrive_mcp** | 4 | ~250줄 | ⭐⭐ 쉬움 | 2 |
| **teams_mcp** | ~4 | ~250줄 | ⭐⭐ 쉬움 | 3 |
| **calendar_mcp** | 5 | ~350줄 | ⭐⭐ 쉬움 | 4 |
| **onenote_mcp** | ~4 | ~250줄 | ⭐⭐ 쉬움 | 5 |
| **mail_query_MCP** | 7+ | ~500줄 | ⭐⭐⭐⭐ 복잡 | 6 |
| **enrollment** | ? | ? | ⭐⭐⭐ 중간 | 7 |
| **dcr_oauth** | 0 | - | - | 제외 |
| **mail_process** | ? | ? | ⭐⭐ 쉬움 | 8 |
| **mail_query** | ? | ? | ⭐⭐⭐ 중간 | 9 |
| **openai_wrapper** | 0 | - | - | 제외 |
| **web_dashboard** | 0 | - | - | 제외 |

**실제 수정 대상**: 9개 모듈 (도구가 있는 모듈만)

---

## 🔄 수정 전후 비교

### Before (현재)
```python
# modules/mail_iacs/handlers.py (312줄)
class IACSHandlers:
    async def handle_list_tools(self):
        # 40-128줄: 도구 정의 (88줄)
        iacs_tools = [
            Tool(name="insert_info", ...),
            Tool(name="search_agenda", ...),
            ...
        ]
        return iacs_tools

    async def handle_call_tool(self, name, arguments):
        # 134-216줄: if/elif 라우팅 (82줄)
        if name == "insert_info":
            request = InsertInfoRequest(**arguments)
            response = await self.tools.insert_info(request)
        elif name == "search_agenda":
            ...

    async def call_tool_as_dict(self, name, arguments):
        # 222-258줄: 또 if/elif (36줄)
        if name == "insert_info":
            ...
```

### After (자동 생성)
```yaml
# modules/mail_iacs/tool_config.yaml (50줄)
tools:
  - name: "insert_info"
    description: "..."
    request_class: "InsertInfoRequest"
    method_name: "insert_info"
```

```python
# modules/mail_iacs/handlers.py (자동 생성, ~150줄)
class IACSHandlers:
    def __init__(self):
        self.registry = ToolRegistry()
        # 도구 자동 등록

    async def handle_list_tools(self):
        return self.registry.list_tools()  # 1줄!

    async def handle_call_tool(self, name, arguments):
        return await self.registry.call_tool(name, arguments)  # 1줄!
```

**코드 감소**: 312줄 → 150줄 (~52% 감소)

---

## 🎯 핵심 변경 사항

### 1. **추가만 필요한 것** (Risk: 🟢 낮음)
- `tool_config.yaml` 파일 추가
- `infra/core/tool_registry.py` 추가
- 템플릿 파일 추가
- 생성 스크립트 추가

### 2. **교체가 필요한 것** (Risk: 🟡 중간)
- `handlers.py` 파일 (백업 후 교체)

### 3. **변경 불필요한 것** (Risk: 🟢 없음)
- `tools.py` (비즈니스 로직)
- `schemas.py` (데이터 모델)
- 모든 entrypoint 파일
- HTTP 서버 파일

---

## 🚀 구현 순서 (리스크 최소화)

### Step 1: 인프라 구축 (신규 파일만)
```bash
# 리스크: 없음 (기존 코드 영향 없음)
infra/core/tool_registry.py        # 생성
infra/core/templates/handlers.jinja2  # 생성
scripts/generate_handlers.py       # 생성
```

### Step 2: 파일럿 테스트 (mail_iacs)
```bash
# 리스크: 낮음 (한 모듈만, 백업 있음)
modules/mail_iacs/tool_config.yaml # 생성
modules/mail_iacs/handlers.py      # 백업 후 교체
modules/mail_iacs/handlers_original.py # 백업
```

### Step 3: 검증
```bash
# 기능 테스트
pytest tests/test_mail_iacs.py

# A/B 테스트 (원본 vs 생성)
python tests/compare_handlers.py
```

### Step 4: 점진적 확산
```bash
# 성공 시 다른 모듈로 확대
# 각 모듈별로 백업 → 생성 → 테스트 반복
```

---

## ⚡ Quick Summary

### 수정 범위
- **신규 파일**: ~10개 (인프라 + 설정)
- **교체 파일**: 9개 (handlers.py만)
- **수정 불필요**: ~100개 (나머지 전부)

### 영향받는 코드
- **직접 영향**: handlers.py (9개 파일, 총 ~2,500줄)
- **간접 영향**: 없음 (인터페이스 동일)

### 리스크
- **낮음**: 대부분 신규 파일 추가
- **중간**: handlers.py 교체 (백업으로 완화)
- **높음**: 없음

### 롤백 계획
```bash
# 문제 발생 시 즉시 롤백 가능
mv modules/*/handlers_original.py modules/*/handlers.py
rm modules/*/tool_config.yaml
# 5초면 원상복구
```

---

## 결론

**실제 수정 범위는 매우 제한적입니다:**

1. **90%는 신규 파일 추가** (기존 코드 영향 없음)
2. **10%만 기존 파일 교체** (handlers.py 9개)
3. **비즈니스 로직(tools.py)은 전혀 수정 안 함**
4. **백업과 롤백이 매우 쉬움**

따라서 리스크가 낮고 점진적 적용이 가능합니다.