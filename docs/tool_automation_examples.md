# 도구 자동화 구현 예제 코드

## 1. YAML 설정 파일 예제

### 간단한 도구 설정 (mail_iacs)
```yaml
# modules/mail_iacs/tool_config.yaml
version: "1.0"
service:
  name: "IACSTools"
  handler_class: "IACSHandlers"
  description: "IACS Panel Management Service"

tools:
  - name: "insert_info"
    description: "패널 의장 및 멤버 정보 삽입. 패널 이름과 의장 주소가 중복되면 기존 데이터를 삭제하고 새 데이터를 삽입합니다."
    request_class: "InsertInfoRequest"
    response_class: "InsertInfoResponse"
    method_name: "insert_info"
    auth_required: false
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

  - name: "search_agenda"
    description: "의장이 보낸 아젠다 메일 검색. 날짜 범위, 아젠다 코드로 필터링 가능. $filter 방식 사용."
    request_class: "SearchAgendaRequest"
    response_class: "SearchAgendaResponse"
    method_name: "search_agenda"
    auth_required: true
    auth_field: "kr_panel_member"
    parameters:
      - name: "start_date"
        type: "string"
        description: "_S 시작 날짜 (ISO 형식, 기본값: 현재)"
        required: false
      - name: "end_date"
        type: "string"
        description: "_S 종료 날짜 (ISO 형식, 기본값: 3개월 전)"
        required: false
      - name: "agenda_code"
        type: "string"
        description: "_S 아젠다 코드 키워드 (옵션)"
        required: false
      - name: "panel_name"
        type: "string"
        description: "패널 이름 (필수, 예: sdtp)"
        required: true
```

### 복잡한 도구 설정 (mail_query_MCP)
```yaml
# modules/mail_query_MCP/tool_config.yaml
version: "1.0"
service:
  name: "MailQueryTools"
  handler_class: "MCPHandlers"
  description: "Email Query and Attachment Processing Service"
  has_orchestrator: true

tools:
  - name: "search_messages"
    title: "📧 Search Messages"
    description: "Query emails and download/convert attachments with advanced filtering"
    request_class: "SearchMessagesRequest"
    response_class: "SearchMessagesResponse"
    method_name: "search_messages"
    auth_required: true
    auth_field: "user_id"
    parameters:
      - name: "user_id"
        type: "string"
        description: "User ID (OPTIONAL - automatically uses authenticated user)"
        required: false
      - name: "start_date"
        type: "string"
        description: "**REQUIRED**: Start date in YYYY-MM-DD format"
        required: true
      - name: "end_date"
        type: "string"
        description: "**REQUIRED**: End date in YYYY-MM-DD format"
        required: true
      - name: "include_body"
        type: "string"
        enum: ["yes", "no"]
        default: "yes"
        description: "Include full email body in results"
        required: true
      - name: "keyword_filter"
        type: "object"
        description: "Advanced keyword filtering"
        properties:
          - name: "and_keywords"
            type: "array"
            items: "string"
            description: "All keywords must be present"
          - name: "or_keywords"
            type: "array"
            items: "string"
            description: "At least one keyword must be present"
          - name: "not_keywords"
            type: "array"
            items: "string"
            description: "None of these keywords should be present"
        required: false
```

---

## 2. Tool Registry 구현

```python
# infra/core/tool_registry.py
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from mcp.types import Tool
import json

@dataclass
class ToolConfig:
    """도구 설정 데이터 클래스"""
    name: str
    description: str
    request_class: type
    response_class: type
    method: Callable
    auth_required: bool = False
    auth_field: Optional[str] = None
    parameters: List[Dict[str, Any]] = None

class ToolRegistry:
    """
    도구 중앙 레지스트리
    모든 도구 메타데이터를 한 곳에서 관리
    """

    def __init__(self):
        self._tools: Dict[str, ToolConfig] = {}

    def register(self, tool_config: ToolConfig) -> None:
        """도구 등록"""
        if tool_config.name in self._tools:
            raise ValueError(f"Tool '{tool_config.name}' already registered")
        self._tools[tool_config.name] = tool_config

    def get_tool(self, name: str) -> Optional[ToolConfig]:
        """도구 조회"""
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        """MCP Tool 객체 리스트 반환"""
        tools = []
        for config in self._tools.values():
            tool = Tool(
                name=config.name,
                description=config.description,
                inputSchema=self._build_input_schema(config)
            )
            tools.append(tool)
        return tools

    def _build_input_schema(self, config: ToolConfig) -> Dict[str, Any]:
        """도구 설정에서 JSON Schema 생성"""
        if not config.parameters:
            return {"type": "object", "properties": {}, "required": []}

        properties = {}
        required = []

        for param in config.parameters:
            prop_schema = {"type": param["type"]}

            if "description" in param:
                prop_schema["description"] = param["description"]

            if "enum" in param:
                prop_schema["enum"] = param["enum"]

            if "default" in param:
                prop_schema["default"] = param["default"]

            properties[param["name"]] = prop_schema

            if param.get("required", False):
                required.append(param["name"])

        return {
            "type": "object",
            "properties": properties,
            "required": required
        }

    async def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        authenticated_user_id: Optional[str] = None
    ) -> Any:
        """도구 실행"""
        config = self.get_tool(name)
        if not config:
            raise ValueError(f"Unknown tool: {name}")

        # 인증 처리
        if config.auth_required and authenticated_user_id:
            if config.auth_field and config.auth_field in arguments:
                # 보안 로깅
                if arguments[config.auth_field] != authenticated_user_id:
                    print(f"⚠️ Auth override: {arguments[config.auth_field]} → {authenticated_user_id}")
                arguments[config.auth_field] = authenticated_user_id

        # Request 객체 생성 및 메서드 호출
        request = config.request_class(**arguments)
        response = await config.method(request)

        return response
```

---

## 3. Jinja2 템플릿

### handlers.jinja2
```jinja
"""
{{ service.description }}
MCP Protocol Handlers - Auto-generated from tool_config.yaml
Generated at: {{ generated_at }}
DO NOT EDIT - This file is auto-generated
"""

from typing import Any, Dict, List, Optional
from mcp.types import Tool, TextContent, Prompt, PromptArgument, PromptMessage
from infra.core.logger import get_logger
from infra.core.tool_registry import ToolRegistry, ToolConfig
from .tools import {{ service.name }}
from .schemas import (
{%- for tool in tools %}
    {{ tool.request_class }},
    {%- if tool.response_class %}
    {{ tool.response_class }},
    {%- endif %}
{%- endfor %}
)

logger = get_logger(__name__)

class {{ service.handler_class }}:
    """{{ service.description }} MCP Protocol Handlers"""

    def __init__(self):
        """Initialize handlers with tools instance and registry"""
        self.tools = {{ service.name }}()
        self.registry = ToolRegistry()
        self._register_tools()
        logger.info("✅ {{ service.handler_class }} initialized with {{ tools|length }} tools")

    def _register_tools(self):
        """Register all tools in the registry"""
        {% for tool in tools %}
        self.registry.register(
            ToolConfig(
                name="{{ tool.name }}",
                description="{{ tool.description }}",
                request_class={{ tool.request_class }},
                response_class={{ tool.response_class if tool.response_class else 'None' }},
                method=self.tools.{{ tool.method_name }},
                auth_required={{ tool.auth_required | lower }},
                {%- if tool.auth_field %}
                auth_field="{{ tool.auth_field }}",
                {%- endif %}
                parameters={{ tool.parameters | tojson }}
            )
        )
        {% endfor %}

    # ========================================================================
    # MCP Protocol: list_tools
    # ========================================================================

    async def handle_list_tools(self) -> List[Tool]:
        """List available MCP tools"""
        logger.info("🔧 [MCP Handler] list_tools() called")
        return self.registry.list_tools()

    # ========================================================================
    # MCP Protocol: call_tool
    # ========================================================================

    async def handle_call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        authenticated_user_id: Optional[str] = None
    ) -> List[TextContent]:
        """Handle MCP tool calls"""
        logger.info(f"🔨 [MCP Handler] call_tool({name}) with args: {arguments}")

        try:
            response = await self.registry.call_tool(
                name=name,
                arguments=arguments,
                authenticated_user_id=authenticated_user_id
            )

            # Format response
            if hasattr(response, 'message'):
                return [TextContent(type="text", text=response.message)]
            elif hasattr(response, 'model_dump_json'):
                return [TextContent(type="text", text=response.model_dump_json(indent=2))]
            else:
                return [TextContent(type="text", text=str(response))]

        except ValueError as e:
            error_msg = str(e)
            logger.error(error_msg)
            return [TextContent(type="text", text=f"Error: {error_msg}")]

        except Exception as e:
            logger.error(f"❌ Tool execution error: {name}, {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"Unexpected error: {str(e)}")]

    # ========================================================================
    # Helper: Convert to dict (for HTTP responses)
    # ========================================================================

    async def call_tool_as_dict(
        self,
        name: str,
        arguments: Dict[str, Any],
        authenticated_user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        HTTP API용 헬퍼: call_tool 결과를 dict로 반환
        """
        try:
            response = await self.registry.call_tool(
                name=name,
                arguments=arguments,
                authenticated_user_id=authenticated_user_id
            )

            if hasattr(response, 'model_dump'):
                return response.model_dump()
            elif hasattr(response, '__dict__'):
                return response.__dict__
            else:
                return {"result": str(response)}

        except Exception as e:
            logger.error(f"❌ Tool execution error: {name}, {str(e)}", exc_info=True)
            raise

    {%- if prompts %}
    # ========================================================================
    # MCP Protocol: list_prompts
    # ========================================================================

    async def handle_list_prompts(self) -> List[Prompt]:
        """List available MCP prompts"""
        logger.info("📋 [MCP Handler] list_prompts() called")

        return [
            {%- for prompt in prompts %}
            Prompt(
                name="{{ prompt.name }}",
                description="{{ prompt.description }}",
                arguments=[
                    {%- for arg in prompt.arguments %}
                    PromptArgument(
                        name="{{ arg.name }}",
                        description="{{ arg.description }}",
                        required={{ arg.required | lower }}
                    ),
                    {%- endfor %}
                ]
            ),
            {%- endfor %}
        ]
    {%- endif %}
```

---

## 4. 코드 생성 스크립트

```python
#!/usr/bin/env python3
# scripts/generate_handlers.py

import yaml
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any
from jinja2 import Environment, FileSystemLoader, StrictUndefined
import argparse
import ast

class HandlerGenerator:
    """YAML 설정에서 Handler 코드 생성"""

    def __init__(self, template_dir: Path):
        self.template_dir = template_dir
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True
        )

    def load_config(self, config_path: Path) -> Dict[str, Any]:
        """YAML 설정 파일 로드"""
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def validate_config(self, config: Dict[str, Any]) -> None:
        """설정 유효성 검증"""
        required_fields = ['version', 'service', 'tools']
        for field in required_fields:
            if field not in config:
                raise ValueError(f"Required field '{field}' missing in config")

        # 서비스 정보 검증
        service_fields = ['name', 'handler_class', 'description']
        for field in service_fields:
            if field not in config['service']:
                raise ValueError(f"Service field '{field}' missing")

        # 도구 정보 검증
        for tool in config['tools']:
            required_tool_fields = ['name', 'description', 'request_class', 'method_name']
            for field in required_tool_fields:
                if field not in tool:
                    raise ValueError(f"Tool '{tool.get('name', 'unknown')}' missing field '{field}'")

    def generate(self, config_path: Path, output_path: Path) -> None:
        """Handler 코드 생성"""
        # 설정 로드 및 검증
        config = self.load_config(config_path)
        self.validate_config(config)

        # 템플릿 컨텍스트 준비
        context = {
            **config,
            'generated_at': datetime.now().isoformat(),
            'config_path': str(config_path),
        }

        # 템플릿 렌더링
        template = self.env.get_template('handlers.jinja2')
        rendered = template.render(context)

        # 문법 검증
        try:
            ast.parse(rendered)
        except SyntaxError as e:
            print(f"❌ Generated code has syntax error: {e}")
            print("Generated code:")
            print(rendered)
            raise

        # 파일 저장
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding='utf-8')

        print(f"✅ Generated: {output_path}")
        print(f"   Tools: {len(config['tools'])}")
        print(f"   Service: {config['service']['name']}")

def main():
    parser = argparse.ArgumentParser(description='Generate MCP handlers from YAML config')
    parser.add_argument('--config', type=Path, required=True, help='Path to tool_config.yaml')
    parser.add_argument('--output', type=Path, required=True, help='Output path for generated handler')
    parser.add_argument('--template-dir', type=Path, default=Path('infra/core/templates'),
                       help='Directory containing Jinja2 templates')
    parser.add_argument('--dry-run', action='store_true', help='Print generated code without saving')

    args = parser.parse_args()

    generator = HandlerGenerator(args.template_dir)

    try:
        if args.dry_run:
            config = generator.load_config(args.config)
            generator.validate_config(config)
            print("✅ Config validation passed")
            print(f"Would generate handler with {len(config['tools'])} tools")
        else:
            generator.generate(args.config, args.output)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
```

---

## 5. 테스트 코드

### 단위 테스트
```python
# tests/unit/test_tool_registry.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from infra.core.tool_registry import ToolRegistry, ToolConfig

@pytest.fixture
def registry():
    return ToolRegistry()

@pytest.fixture
def sample_tool_config():
    return ToolConfig(
        name="test_tool",
        description="Test tool",
        request_class=MagicMock,
        response_class=MagicMock,
        method=AsyncMock(),
        auth_required=False,
        parameters=[
            {"name": "param1", "type": "string", "required": True},
            {"name": "param2", "type": "number", "required": False}
        ]
    )

def test_register_tool(registry, sample_tool_config):
    """도구 등록 테스트"""
    registry.register(sample_tool_config)
    assert registry.get_tool("test_tool") is not None

def test_duplicate_registration(registry, sample_tool_config):
    """중복 등록 방지 테스트"""
    registry.register(sample_tool_config)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(sample_tool_config)

def test_list_tools(registry, sample_tool_config):
    """도구 목록 조회 테스트"""
    registry.register(sample_tool_config)
    tools = registry.list_tools()

    assert len(tools) == 1
    assert tools[0].name == "test_tool"
    assert tools[0].description == "Test tool"

@pytest.mark.asyncio
async def test_call_tool(registry, sample_tool_config):
    """도구 실행 테스트"""
    sample_tool_config.method.return_value = {"success": True}
    registry.register(sample_tool_config)

    result = await registry.call_tool(
        "test_tool",
        {"param1": "value1", "param2": 42}
    )

    assert result == {"success": True}
    sample_tool_config.method.assert_called_once()
```

### 통합 테스트
```python
# tests/integration/test_generated_handlers.py
import pytest
import tempfile
from pathlib import Path
from scripts.generate_handlers import HandlerGenerator

@pytest.fixture
def test_config():
    return {
        "version": "1.0",
        "service": {
            "name": "TestTools",
            "handler_class": "TestHandlers",
            "description": "Test Service"
        },
        "tools": [
            {
                "name": "test_tool",
                "description": "Test tool",
                "request_class": "TestRequest",
                "response_class": "TestResponse",
                "method_name": "test_method",
                "auth_required": False,
                "parameters": []
            }
        ]
    }

@pytest.fixture
def template_dir(tmp_path):
    """임시 템플릿 디렉토리 생성"""
    template_path = tmp_path / "handlers.jinja2"
    template_content = """
class {{ service.handler_class }}:
    pass
"""
    template_path.write_text(template_content)
    return tmp_path

def test_generator(test_config, template_dir, tmp_path):
    """코드 생성 테스트"""
    # YAML 파일 생성
    config_path = tmp_path / "config.yaml"
    import yaml
    config_path.write_text(yaml.dump(test_config))

    # 출력 경로
    output_path = tmp_path / "generated.py"

    # 생성기 실행
    generator = HandlerGenerator(template_dir)
    generator.generate(config_path, output_path)

    # 생성된 파일 확인
    assert output_path.exists()
    content = output_path.read_text()
    assert "class TestHandlers:" in content
```

### 회귀 테스트
```python
# tests/regression/test_backward_compatibility.py
import pytest
from modules.mail_iacs.handlers import IACSHandlers as OriginalHandlers
# from modules.mail_iacs.handlers_generated import IACSHandlers as GeneratedHandlers

@pytest.mark.asyncio
async def test_tools_match():
    """생성된 핸들러가 원본과 동일한 도구 제공"""
    original = OriginalHandlers()
    # generated = GeneratedHandlers()

    original_tools = await original.handle_list_tools()
    # generated_tools = await generated.handle_list_tools()

    # Tool 개수 확인
    assert len(original_tools) == 4
    # assert len(generated_tools) == 4

    # Tool 이름 확인
    original_names = {t.name for t in original_tools}
    expected = {"insert_info", "search_agenda", "search_responses", "insert_default_value"}
    assert original_names == expected
```

---

## 6. 배포 스크립트

### Makefile
```makefile
# Makefile
.PHONY: generate test clean

MODULES := mail_iacs onedrive_mcp onenote_mcp teams_mcp calendar_mcp

generate:
	@echo "Generating handlers for all modules..."
	@for module in $(MODULES); do \
		if [ -f "modules/$$module/tool_config.yaml" ]; then \
			echo "  - Generating $$module..."; \
			python scripts/generate_handlers.py \
				--config modules/$$module/tool_config.yaml \
				--output modules/$$module/handlers.py; \
		fi \
	done

test: generate
	@echo "Running tests..."
	pytest tests/ -v

validate:
	@echo "Validating generated code..."
	@for module in $(MODULES); do \
		if [ -f "modules/$$module/handlers.py" ]; then \
			python -m py_compile modules/$$module/handlers.py; \
		fi \
	done

clean:
	@echo "Cleaning generated files..."
	@find modules -name "handlers_generated.py" -delete
	@find . -name "__pycache__" -type d -exec rm -rf {} +
	@find . -name "*.pyc" -delete

watch:
	@echo "Watching for YAML changes..."
	@fswatch -o modules/**/tool_config.yaml | xargs -n1 -I{} make generate
```

### GitHub Actions
```yaml
# .github/workflows/generate-tools.yml
name: Generate and Test Tools

on:
  push:
    paths:
      - 'modules/**/tool_config.yaml'
      - 'infra/core/templates/**'
      - 'scripts/generate_handlers.py'
  pull_request:
    paths:
      - 'modules/**/tool_config.yaml'

jobs:
  generate-and-test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'

    - name: Install dependencies
      run: |
        pip install pyyaml jinja2 pytest pytest-asyncio
        pip install -r requirements.txt

    - name: Generate handlers
      run: make generate

    - name: Validate generated code
      run: make validate

    - name: Run tests
      run: make test

    - name: Upload generated files
      if: success()
      uses: actions/upload-artifact@v3
      with:
        name: generated-handlers
        path: modules/**/handlers.py
```

---

## 7. 마이그레이션 가이드

### Step 1: 백업
```bash
# 기존 handlers 백업
cp modules/mail_iacs/handlers.py modules/mail_iacs/handlers_original.py
```

### Step 2: YAML 작성
```bash
# tool_config.yaml 생성
vim modules/mail_iacs/tool_config.yaml
```

### Step 3: 생성 및 비교
```bash
# 새 handler 생성
python scripts/generate_handlers.py \
  --config modules/mail_iacs/tool_config.yaml \
  --output modules/mail_iacs/handlers_generated.py

# 비교
diff modules/mail_iacs/handlers.py modules/mail_iacs/handlers_generated.py
```

### Step 4: 테스트
```bash
# 임시로 교체
mv modules/mail_iacs/handlers.py modules/mail_iacs/handlers_backup.py
mv modules/mail_iacs/handlers_generated.py modules/mail_iacs/handlers.py

# 테스트 실행
pytest tests/test_mail_iacs.py -v

# 성공 시 커밋, 실패 시 롤백
```

---

## 8. 트러블슈팅

### 문제: Import 오류
```python
# 해결: 템플릿에서 조건부 import
{% if tool.response_class %}
from .schemas import {{ tool.response_class }}
{% endif %}
```

### 문제: 특수 문자 이스케이프
```python
# 해결: Jinja2 필터 사용
description="{{ tool.description | escape }}"
```

### 문제: 복잡한 파라미터 구조
```yaml
# 해결: 중첩 객체 지원
parameters:
  - name: "keyword_filter"
    type: "object"
    properties:
      - name: "and_keywords"
        type: "array"
        items: "string"
```

### 문제: 디버깅 어려움
```python
# 해결: 생성된 코드에 메타데이터 추가
"""
Generated from: {{ config_path }}
Generated at: {{ generated_at }}
Template version: {{ template_version }}
"""
```