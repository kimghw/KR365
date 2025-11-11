"""
Tool Registry System for MCP Handlers
도구 메타데이터를 중앙에서 관리하는 레지스트리 시스템
"""

from typing import Dict, Any, List, Optional, Callable, Union
from dataclasses import dataclass, field
from mcp.types import Tool
import json
from infra.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ToolConfig:
    """도구 설정 데이터 클래스"""
    name: str
    description: str
    request_class: type
    method: Callable
    response_class: Optional[type] = None
    auth_required: bool = False
    auth_field: Optional[str] = None
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    input_schema: Optional[Dict[str, Any]] = None  # 직접 정의된 스키마


class ToolRegistry:
    """
    도구 중앙 레지스트리
    모든 도구 메타데이터를 한 곳에서 관리
    """

    def __init__(self):
        self._tools: Dict[str, ToolConfig] = {}
        logger.info("ToolRegistry initialized")

    def register(self, tool_config: ToolConfig) -> None:
        """도구 등록"""
        if tool_config.name in self._tools:
            raise ValueError(f"Tool '{tool_config.name}' already registered")

        self._tools[tool_config.name] = tool_config
        logger.info(f"Tool registered: {tool_config.name}")

    def get_tool(self, name: str) -> Optional[ToolConfig]:
        """도구 조회"""
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        """MCP Tool 객체 리스트 반환"""
        tools = []
        for config in self._tools.values():
            # input_schema가 직접 정의된 경우 그대로 사용
            if config.input_schema:
                input_schema = config.input_schema
            else:
                input_schema = self._build_input_schema(config)

            tool = Tool(
                name=config.name,
                description=config.description,
                inputSchema=input_schema
            )
            tools.append(tool)

        logger.info(f"Listed {len(tools)} tools")
        return tools

    def _build_input_schema(self, config: ToolConfig) -> Dict[str, Any]:
        """도구 설정에서 JSON Schema 생성"""
        if not config.parameters:
            return {"type": "object", "properties": {}, "required": []}

        properties = {}
        required = []

        for param in config.parameters:
            # 파라미터가 dict 형태인 경우
            if isinstance(param, dict):
                prop_schema = {"type": param.get("type", "string")}

                if "description" in param:
                    prop_schema["description"] = param["description"]

                if "enum" in param:
                    prop_schema["enum"] = param["enum"]

                if "default" in param:
                    prop_schema["default"] = param["default"]

                if "items" in param:
                    prop_schema["items"] = param["items"]

                if "properties" in param:
                    prop_schema["properties"] = self._build_properties(param["properties"])

                properties[param["name"]] = prop_schema

                if param.get("required", False):
                    required.append(param["name"])

        return {
            "type": "object",
            "properties": properties,
            "required": required
        }

    def _build_properties(self, props: List[Dict[str, Any]]) -> Dict[str, Any]:
        """중첩된 properties 빌드"""
        result = {}
        for prop in props:
            prop_schema = {"type": prop.get("type", "string")}

            if "description" in prop:
                prop_schema["description"] = prop["description"]

            if "items" in prop:
                prop_schema["items"] = {"type": prop["items"]}

            result[prop["name"]] = prop_schema

        return result

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

        logger.info(f"Calling tool: {name} with args: {list(arguments.keys())}")

        # 인증 처리
        if config.auth_required and authenticated_user_id:
            if config.auth_field and config.auth_field in arguments:
                # 보안 로깅
                provided_value = arguments.get(config.auth_field)
                if provided_value and provided_value != authenticated_user_id:
                    logger.warning(
                        f"⚠️ Auth override: {config.auth_field}={provided_value} → {authenticated_user_id}"
                    )
                arguments[config.auth_field] = authenticated_user_id

        # Request 객체 생성 및 메서드 호출
        try:
            request = config.request_class(**arguments)
            response = await config.method(request)

            logger.info(f"Tool {name} executed successfully")
            return response

        except Exception as e:
            logger.error(f"Tool {name} execution failed: {str(e)}", exc_info=True)
            raise

    def get_tool_count(self) -> int:
        """등록된 도구 개수 반환"""
        return len(self._tools)

    def get_tool_names(self) -> List[str]:
        """등록된 도구 이름 목록 반환"""
        return list(self._tools.keys())

    def clear(self) -> None:
        """모든 도구 제거 (테스트용)"""
        self._tools.clear()
        logger.info("All tools cleared from registry")