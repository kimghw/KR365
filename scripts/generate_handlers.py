#!/usr/bin/env python3
"""
MCP Handler 코드 생성 스크립트
YAML 설정 파일에서 handlers.py를 자동 생성합니다.
"""

import yaml
import sys
import ast
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List
from jinja2 import Environment, FileSystemLoader, StrictUndefined
import argparse


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
        for i, tool in enumerate(config['tools']):
            required_tool_fields = ['name', 'description', 'request_class', 'method_name']
            for field in required_tool_fields:
                if field not in tool:
                    raise ValueError(
                        f"Tool #{i+1} '{tool.get('name', 'unknown')}' missing field '{field}'"
                    )

        print(f"✅ Config validation passed: {len(config['tools'])} tools found")

    def prepare_context(self, config: Dict[str, Any], config_path: Path) -> Dict[str, Any]:
        """템플릿 렌더링을 위한 컨텍스트 준비"""
        # 인증이 필요한 도구들 찾기
        auth_tools = [
            tool for tool in config['tools']
            if tool.get('auth_required', False)
        ]

        # 인증 도구 이름 목록
        auth_tool_names = [f'"{tool["name"]}"' for tool in auth_tools]

        context = {
            **config,
            'generated_at': datetime.now().isoformat(),
            'config_path': str(config_path),
            'has_auth_tools': len(auth_tools) > 0,
            'auth_tool_names': auth_tool_names,
        }

        return context

    def generate(self, config_path: Path, output_path: Path, dry_run: bool = False) -> str:
        """Handler 코드 생성"""
        # 설정 로드 및 검증
        config = self.load_config(config_path)
        self.validate_config(config)

        # 템플릿 컨텍스트 준비
        context = self.prepare_context(config, config_path)

        # 템플릿 렌더링
        template = self.env.get_template('handlers.jinja2')
        rendered = template.render(context)

        # 문법 검증
        try:
            ast.parse(rendered)
            print(f"✅ Syntax validation passed")
        except SyntaxError as e:
            print(f"❌ Generated code has syntax error at line {e.lineno}: {e.msg}")
            print("\nGenerated code preview:")
            lines = rendered.split('\n')
            start = max(0, e.lineno - 3)
            end = min(len(lines), e.lineno + 3)
            for i in range(start, end):
                prefix = ">>> " if i == e.lineno - 1 else "    "
                print(f"{prefix}{i+1:4d}: {lines[i]}")
            raise

        if dry_run:
            print("\n" + "="*60)
            print("DRY RUN - Generated code preview:")
            print("="*60)
            print(rendered[:1000])  # 처음 1000자만 출력
            print("... (truncated)")
            print("="*60)
            print(f"\n✅ Dry run completed successfully")
            print(f"   Service: {config['service']['name']}")
            print(f"   Handler: {config['service']['handler_class']}")
            print(f"   Tools: {len(config['tools'])}")
            for tool in config['tools']:
                print(f"     - {tool['name']}: {tool['description'][:50]}...")
        else:
            # 파일 저장
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # 백업 생성 (파일이 존재하는 경우)
            if output_path.exists():
                backup_path = output_path.with_suffix('.py.backup')
                output_path.rename(backup_path)
                print(f"📦 Backup created: {backup_path}")

            output_path.write_text(rendered, encoding='utf-8')
            print(f"✅ Generated: {output_path}")
            print(f"   Service: {config['service']['name']}")
            print(f"   Handler: {config['service']['handler_class']}")
            print(f"   Tools: {len(config['tools'])}")

        return rendered


def main():
    parser = argparse.ArgumentParser(
        description='Generate MCP handlers from YAML config',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate handler
  python scripts/generate_handlers.py \\
    --config modules/mail_iacs/tool_config.yaml \\
    --output modules/mail_iacs/handlers.py

  # Dry run (preview without saving)
  python scripts/generate_handlers.py \\
    --config modules/mail_iacs/tool_config.yaml \\
    --output modules/mail_iacs/handlers.py \\
    --dry-run

  # Use custom template directory
  python scripts/generate_handlers.py \\
    --config modules/mail_iacs/tool_config.yaml \\
    --output modules/mail_iacs/handlers.py \\
    --template-dir custom/templates
        """
    )

    parser.add_argument(
        '--config',
        type=Path,
        required=True,
        help='Path to tool_config.yaml'
    )
    parser.add_argument(
        '--output',
        type=Path,
        required=True,
        help='Output path for generated handler'
    )
    parser.add_argument(
        '--template-dir',
        type=Path,
        default=Path('infra/core/templates'),
        help='Directory containing Jinja2 templates (default: infra/core/templates)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview generated code without saving'
    )

    args = parser.parse_args()

    # 경로 검증
    if not args.config.exists():
        print(f"❌ Config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    if not args.template_dir.exists():
        print(f"❌ Template directory not found: {args.template_dir}", file=sys.stderr)
        sys.exit(1)

    template_path = args.template_dir / 'handlers.jinja2'
    if not template_path.exists():
        print(f"❌ Template file not found: {template_path}", file=sys.stderr)
        sys.exit(1)

    # 생성기 실행
    generator = HandlerGenerator(args.template_dir)

    try:
        generator.generate(args.config, args.output, args.dry_run)

        if not args.dry_run:
            print(f"\n📝 Next steps:")
            print(f"  1. Review generated code: {args.output}")
            print(f"  2. Run tests: pytest tests/test_{args.output.parent.name}.py")
            print(f"  3. If issues, restore backup: {args.output}.backup")

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()