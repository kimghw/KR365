# Base Templates for MCP Services

이 패키지는 MCP (Model Context Protocol) 서비스를 쉽게 구축할 수 있는 템플릿 시스템을 제공합니다.

## 구성 요소

### 1. 핵심 컴포넌트

- **BaseHandler** (`base_handler.py`): 모든 핸들러가 구현해야 할 기본 인터페이스
- **BaseServer** (`base_server.py`): 모든 서버 타입의 기본 클래스
- **DCRAuthMixin** (`dcr_auth_mixin.py`): DCR OAuth 인증 기능을 제공하는 믹스인

### 2. 서버 템플릿

- **MCPStdioServer** (`mcp_stdio_server.py`): MCP stdio 프로토콜 서버 (Claude Desktop 통합용)
- **FastAPIServer** (`fastapi_server.py`): HTTP API 서버
- **LocalServer** (`local_server.py`): 로컬 CLI 도구

### 3. 예제 구현 (`examples/` 디렉토리)

- **ExampleHandler** (`examples/example_handler.py`): 템플릿 사용 예제 핸들러
- **example_stdio.py**: MCP stdio 서버 예제
- **example_fastapi.py**: FastAPI 서버 예제
- **example_fastapi_dcr.py**: DCR OAuth를 사용하는 FastAPI 서버 예제
- **example_local.py**: 로컬 CLI 도구 예제

## 사용 방법

### 1. 핸들러 구현

```python
from modules.base_templates import BaseHandler
from mcp.types import Tool, TextContent

class MyHandler(BaseHandler):
    async def list_tools(self) -> List[Tool]:
        return [
            Tool(
                name="my_tool",
                description="My custom tool",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "param": {"type": "string"}
                    }
                }
            )
        ]

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        if name == "my_tool":
            return [TextContent(type="text", text="Tool executed!")]
        return [TextContent(type="text", text="Unknown tool")]
```

### 2. MCP Stdio 서버 생성

```python
from modules.base_templates import MCPStdioServer
from my_module import MyHandler

# 핸들러와 서버 생성
handler = MyHandler()
server = MCPStdioServer(
    server_name="my-mcp-server",
    handler=handler
)

# 서버 실행
server.run()
```

### 3. FastAPI 서버 생성

```python
from modules.base_templates import FastAPIServer
from my_module import MyHandler

# 핸들러와 서버 생성
handler = MyHandler()
server = FastAPIServer(
    server_name="my-api-server",
    handler=handler,
    port=8000
)

# 서버 실행
server.run()
```

### 4. DCR OAuth 추가

```python
from modules.base_templates import FastAPIServer, DCRAuthMixin

class MySecureServer(FastAPIServer, DCRAuthMixin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        DCRAuthMixin.__init__(self, server_name=self.server_name)
        self.register_dcr_routes(self.app)
```

## 예제 실행

### MCP Stdio 서버
```bash
python modules/base_templates/examples/example_stdio.py
```

### FastAPI 서버
```bash
python modules/base_templates/examples/example_fastapi.py --port 8000
```

### FastAPI + DCR OAuth 서버
```bash
python modules/base_templates/examples/example_fastapi_dcr.py --port 8001
```

### 로컬 CLI 도구
```bash
# 대화형 모드
python modules/base_templates/examples/example_local.py interactive

# 도구 목록
python modules/base_templates/examples/example_local.py list

# 도구 실행
python modules/base_templates/examples/example_local.py call hello --args '{"name": "World"}'
```

## 환경 변수

- `MCP_STDIO_MODE`: stdio 모드 활성화
- `PORT`: FastAPI 서버 포트
- `HOST`: FastAPI 서버 호스트
- `CORS_ORIGINS`: CORS 허용 origin (쉼표로 구분)
- `DCR_DATABASE_PATH`: DCR 인증 DB 경로
- `DCR_ALLOWED_DOMAINS`: 허용된 도메인 목록

## 디렉토리 구조

```
modules/base_templates/
├── __init__.py              # 패키지 초기화
├── base_handler.py          # 기본 핸들러 인터페이스
├── base_server.py           # 기본 서버 클래스
├── mcp_stdio_server.py      # MCP stdio 서버 템플릿
├── fastapi_server.py        # FastAPI 서버 템플릿
├── local_server.py          # 로컬 서버 템플릿
├── dcr_auth_mixin.py        # DCR OAuth 믹스인
├── examples/                # 예제 구현
│   ├── __init__.py
│   ├── example_handler.py   # 예제 핸들러
│   ├── example_stdio.py     # stdio 서버 예제
│   ├── example_fastapi.py   # FastAPI 예제
│   ├── example_fastapi_dcr.py # FastAPI + DCR 예제
│   └── example_local.py     # 로컬 CLI 예제
└── README.md                # 이 파일
```

## 라이선스

이 프로젝트는 내부 사용을 위해 개발되었습니다.