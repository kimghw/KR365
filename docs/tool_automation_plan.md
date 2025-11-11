# MCP 도구 완전 자동화 계획서

## 📋 개요
MCP(Model Context Protocol) 도구 정의와 핸들러 로직을 YAML 설정과 Jinja2 템플릿을 통해 완전 자동화하는 프로젝트입니다.

### 목표
- **중복 제거**: 도구 이름, 설명, 파라미터가 3곳에서 반복되는 문제 해결
- **개발 속도**: 새 도구 추가 시 YAML만 작성하면 모든 코드 자동 생성
- **일관성 보장**: 템플릿 기반으로 모든 모듈이 동일한 패턴 유지
- **타입 안전성**: Pydantic 스키마와 자동 생성 코드 간 타입 일치

---

## 🏗️ 아키텍처 설계

### 현재 구조 (AS-IS)
```
modules/[service_name]/
├── handlers.py         # 도구 정의 + 라우팅 로직 (중복)
├── tools.py           # 비즈니스 로직
└── schemas.py         # Pydantic 모델
```

### 목표 구조 (TO-BE)
```
modules/[service_name]/
├── tool_config.yaml    # 도구 메타데이터 (단일 소스)
├── handlers.py        # [자동 생성] 템플릿 기반
├── tools.py           # 비즈니스 로직 (수동 유지)
├── schemas.py         # Pydantic 모델 (수동 유지)
└── registry.py        # [자동 생성] 도구 레지스트리
```

---

## 📝 단계별 구현 계획

### Phase 1: 기반 구조 구축 (1-2일)

#### 1.1 도구 레지스트리 시스템 구현
```python
# infra/core/tool_registry.py
class ToolRegistry:
    """도구 메타데이터 중앙 관리"""

    def __init__(self):
        self._tools = {}

    def register(self, name: str, config: ToolConfig):
        """도구 등록"""
        self._tools[name] = config

    def get_tool(self, name: str) -> Optional[ToolConfig]:
        """도구 조회"""
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        """MCP Tool 객체 리스트 반환"""
        return [self._to_mcp_tool(config) for config in self._tools.values()]
```

#### 1.2 YAML 스키마 정의
```yaml
# modules/mail_iacs/tool_config.yaml
version: "1.0"
service_name: "mail_iacs"
service_description: "IACS Panel Management Service"

tools:
  - name: "insert_info"
    description: "패널 의장 및 멤버 정보 삽입"
    request_class: "InsertInfoRequest"
    response_class: "InsertInfoResponse"
    method_name: "insert_info"
    parameters:
      - name: "chair_address"
        type: "string"
        description: "의장 이메일 주소"
        required: true
      - name: "panel_name"
        type: "string"
        description: "패널 이름 (예: sdtp)"
        required: true
      - name: "kr_panel_member"
        type: "string"
        description: "한국 패널 멤버 이메일 주소"
        required: true
    auth_required: false
    security_checks:
      - type: "user_id_validation"
        applies_to: ["kr_panel_member"]
```

#### 테스트 체크리스트
- [ ] YAML 파일 유효성 검증 (jsonschema)
- [ ] 레지스트리 등록/조회 기능
- [ ] 중복 도구 이름 처리
- [ ] 잘못된 YAML 형식 에러 처리

---

### Phase 2: 템플릿 시스템 구축 (2-3일)

#### 2.1 Jinja2 템플릿 작성

**handlers.jinja2**
```jinja
"""
{{ service_description }}
MCP Protocol Handlers - Auto-generated from tool_config.yaml
Generated at: {{ generated_at }}
"""

from typing import Any, Dict, List, Optional
from mcp.types import Tool, TextContent
from infra.core.logger import get_logger
from infra.core.tool_registry import ToolRegistry
from .tools import {{ service_name }}Tools
from .schemas import (
{%- for tool in tools %}
    {{ tool.request_class }},
{%- endfor %}
)

logger = get_logger(__name__)

class {{ service_name }}Handlers:
    """{{ service_description }} MCP Protocol Handlers"""

    def __init__(self):
        self.tools = {{ service_name }}Tools()
        self.registry = ToolRegistry()

        # 도구 자동 등록
        {% for tool in tools %}
        self.registry.register(
            "{{ tool.name }}",
            {
                "description": "{{ tool.description }}",
                "request_class": {{ tool.request_class }},
                "method": self.tools.{{ tool.method_name }},
                "auth_required": {{ tool.auth_required | lower }},
                "parameters": {{ tool.parameters | tojson }}
            }
        )
        {% endfor %}
        logger.info("✅ {{ service_name }}Handlers initialized with {{ tools|length }} tools")

    async def handle_list_tools(self) -> List[Tool]:
        """List available MCP tools"""
        return self.registry.list_tools()

    async def handle_call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        authenticated_user_id: Optional[str] = None
    ) -> List[TextContent]:
        """Handle MCP tool calls"""

        tool_config = self.registry.get_tool(name)
        if not tool_config:
            return [TextContent(
                type="text",
                text=f"Unknown tool: {name}"
            )]

        try:
            # 보안 검증 (필요 시)
            {% if has_auth_tools %}
            if tool_config["auth_required"]:
                from infra.core.auth_helpers import get_authenticated_user_id
                # 인증 로직 적용
                resolved_user = get_authenticated_user_id(arguments, authenticated_user_id)
                if resolved_user:
                    arguments["user_id"] = resolved_user
            {% endif %}

            # 도구 실행
            request_class = tool_config["request_class"]
            method = tool_config["method"]

            request = request_class(**arguments)
            response = await method(request)

            # 응답 포맷팅
            if hasattr(response, 'message'):
                return [TextContent(type="text", text=response.message)]
            else:
                return [TextContent(type="text", text=response.model_dump_json(indent=2))]

        except Exception as e:
            logger.error(f"Tool execution error: {name}, {str(e)}", exc_info=True)
            return [TextContent(
                type="text",
                text=f"Error: {str(e)}"
            )]
```

#### 2.2 코드 생성 스크립트
```python
# scripts/generate_handlers.py
import yaml
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from datetime import datetime

def generate_handlers(config_path: Path, template_path: Path, output_path: Path):
    """YAML 설정에서 handlers.py 생성"""

    # YAML 로드
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # 템플릿 렌더링
    env = Environment(loader=FileSystemLoader(template_path.parent))
    template = env.get_template(template_path.name)

    # 컨텍스트 준비
    context = {
        **config,
        'generated_at': datetime.now().isoformat(),
        'has_auth_tools': any(t.get('auth_required') for t in config['tools'])
    }

    # 파일 생성
    rendered = template.render(context)
    output_path.write_text(rendered)

    print(f"✅ Generated: {output_path}")
```

#### 테스트 체크리스트
- [ ] 템플릿 렌더링 성공
- [ ] 생성된 코드 문법 검증 (ast.parse)
- [ ] import 구문 정확성
- [ ] 인덴테이션 일관성
- [ ] 특수 문자 이스케이프

---

### Phase 3: 파일럿 구현 (2-3일)

#### 3.1 단일 모듈 적용 (mail_iacs)
1. `tool_config.yaml` 작성
2. 템플릿으로 `handlers.py` 생성
3. 기존 코드와 비교
4. 통합 테스트

#### 3.2 검증 항목
```python
# tests/test_generated_handlers.py
import pytest
from modules.mail_iacs.handlers import IACSHandlers

@pytest.mark.asyncio
async def test_list_tools():
    """생성된 handlers가 도구 목록을 반환하는지 검증"""
    handlers = IACSHandlers()
    tools = await handlers.handle_list_tools()

    assert len(tools) == 4
    assert any(t.name == "insert_info" for t in tools)

@pytest.mark.asyncio
async def test_call_tool():
    """생성된 handlers가 도구를 실행하는지 검증"""
    handlers = IACSHandlers()

    result = await handlers.handle_call_tool(
        "insert_info",
        {
            "chair_address": "test@example.com",
            "panel_name": "sdtp",
            "kr_panel_member": "member@kr.com"
        }
    )

    assert result[0].type == "text"
    assert "success" in result[0].text
```

#### 테스트 체크리스트
- [ ] 도구 목록 조회 정상 작동
- [ ] 모든 도구 실행 가능
- [ ] 에러 처리 로직 작동
- [ ] 인증 필요 도구 검증
- [ ] 응답 포맷 일치

---

### Phase 4: 전체 모듈 확산 (3-4일)

#### 4.1 마이그레이션 순서
1. **간단한 모듈부터**: 도구 4개 이하
   - mail_iacs (4 tools)
   - onedrive_mcp (4 tools)
   - teams_mcp (~4 tools)

2. **중간 복잡도**: 도구 5-7개
   - calendar_mcp (5 tools)
   - onenote_mcp (~4 tools)

3. **복잡한 모듈**: 특수 로직 포함
   - mail_query_MCP (7+ tools, orchestrator)
   - enrollment (auth flows)

#### 4.2 각 모듈별 체크리스트
- [ ] tool_config.yaml 작성
- [ ] handlers.py 백업
- [ ] 새 handlers.py 생성
- [ ] 기능 테스트 실행
- [ ] HTTP/stdio 통합 테스트

---

### Phase 5: CI/CD 통합 (1-2일)

#### 5.1 빌드 파이프라인
```yaml
# .github/workflows/generate-tools.yml
name: Generate Tool Handlers

on:
  push:
    paths:
      - 'modules/**/tool_config.yaml'
      - 'templates/**/*.jinja2'

jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install pyyaml jinja2

      - name: Generate handlers
        run: python scripts/generate_all_handlers.py

      - name: Validate generated code
        run: python -m py_compile modules/**/handlers.py

      - name: Run tests
        run: pytest tests/test_generated_handlers.py
```

#### 5.2 Pre-commit Hook
```bash
#!/bin/bash
# .git/hooks/pre-commit

# YAML 변경 감지
if git diff --cached --name-only | grep -q "tool_config.yaml"; then
    echo "Regenerating handlers..."
    python scripts/generate_handlers.py

    # 생성된 파일 스테이징
    git add modules/**/handlers.py
fi
```

#### 테스트 체크리스트
- [ ] CI 파이프라인 트리거
- [ ] 코드 생성 성공
- [ ] 자동 테스트 통과
- [ ] PR 자동 생성

---

## 🧪 테스트 전략

### 단위 테스트
```python
# tests/unit/test_registry.py
def test_tool_registration():
    registry = ToolRegistry()
    registry.register("test_tool", {...})
    assert registry.get_tool("test_tool") is not None

# tests/unit/test_template.py
def test_template_rendering():
    rendered = render_template(config)
    assert "class IACSHandlers" in rendered
```

### 통합 테스트
```python
# tests/integration/test_generated_handlers.py
@pytest.mark.asyncio
async def test_end_to_end():
    """YAML → 템플릿 → handlers → 도구 실행"""
    # 1. YAML 로드
    config = load_yaml("test_config.yaml")

    # 2. 핸들러 생성
    generate_handlers(config, "handlers_test.py")

    # 3. 생성된 핸들러 import
    from handlers_test import TestHandlers

    # 4. 도구 실행
    handlers = TestHandlers()
    tools = await handlers.handle_list_tools()
    assert len(tools) > 0
```

### 회귀 테스트
```python
# tests/regression/test_backward_compatibility.py
def test_generated_matches_original():
    """생성된 코드가 기존 코드와 동일한 동작"""
    original = OriginalHandlers()
    generated = GeneratedHandlers()

    original_tools = await original.handle_list_tools()
    generated_tools = await generated.handle_list_tools()

    assert len(original_tools) == len(generated_tools)
    for o, g in zip(original_tools, generated_tools):
        assert o.name == g.name
        assert o.description == g.description
```

---

## 📊 성공 지표

### 정량적 지표
- **코드 중복**: 70% 감소 (3곳 → 1곳)
- **새 도구 추가 시간**: 30분 → 5분
- **타입 오류**: 0건 (자동 검증)
- **테스트 커버리지**: 90% 이상

### 정성적 지표
- 개발자 만족도 향상
- 온보딩 시간 단축
- 유지보수 용이성 증가
- 일관성 있는 코드 품질

---

## ⚠️ 위험 요소 및 대응

### 위험 1: 복잡한 비즈니스 로직
**문제**: 일부 도구가 특수한 전/후처리 필요
**대응**:
- 템플릿에 커스텀 훅 지원
- `pre_process`, `post_process` 옵션 추가

### 위험 2: 기존 코드와 호환성
**문제**: 생성된 코드가 기존 시스템과 충돌
**대응**:
- 점진적 마이그레이션
- 기능 플래그로 새/구 코드 전환

### 위험 3: 디버깅 어려움
**문제**: 자동 생성 코드 디버깅 복잡
**대응**:
- 소스맵 생성
- 생성된 코드에 주석 추가
- 디버그 모드 지원

---

## 📅 일정

| Phase | 기간 | 시작일 | 종료일 | 산출물 |
|-------|------|--------|--------|--------|
| Phase 1 | 1-2일 | D+0 | D+2 | 레지스트리 시스템 |
| Phase 2 | 2-3일 | D+2 | D+5 | 템플릿 시스템 |
| Phase 3 | 2-3일 | D+5 | D+8 | 파일럿 모듈 |
| Phase 4 | 3-4일 | D+8 | D+12 | 전체 마이그레이션 |
| Phase 5 | 1-2일 | D+12 | D+14 | CI/CD 통합 |

**총 소요 기간**: 9-14일 (약 2-3주)

---

## 🚀 시작하기

### 1. 환경 설정
```bash
# 필요 패키지 설치
pip install pyyaml jinja2 jsonschema pytest pytest-asyncio

# 프로젝트 구조 생성
mkdir -p infra/core/templates
mkdir -p scripts
mkdir -p tests/{unit,integration,regression}
```

### 2. 첫 번째 YAML 작성
```bash
# mail_iacs 모듈부터 시작
cd modules/mail_iacs
cp tool_config.yaml.example tool_config.yaml
# 편집...
```

### 3. 코드 생성 실행
```bash
python scripts/generate_handlers.py \
  --config modules/mail_iacs/tool_config.yaml \
  --template templates/handlers.jinja2 \
  --output modules/mail_iacs/handlers_generated.py
```

### 4. 테스트 실행
```bash
pytest tests/test_mail_iacs_generated.py -v
```

---

## 📚 참고 자료

- [Jinja2 Documentation](https://jinja.palletsprojects.com/)
- [YAML Schema Validation](https://json-schema.org/)
- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [Pydantic V2 Documentation](https://docs.pydantic.dev/)

---

## 🔄 변경 이력

| 날짜 | 버전 | 변경 내용 | 작성자 |
|------|------|-----------|--------|
| 2024-11-11 | 1.0 | 초기 계획서 작성 | System |

---

## ✅ 최종 체크리스트

### 구현 전
- [ ] 모든 이해관계자 동의
- [ ] 백업 계획 수립
- [ ] 롤백 절차 문서화

### 구현 중
- [ ] 각 Phase별 테스트 통과
- [ ] 코드 리뷰 완료
- [ ] 문서 업데이트

### 구현 후
- [ ] 성능 측정
- [ ] 사용자 교육
- [ ] 모니터링 설정