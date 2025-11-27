"""MCP Prompt definitions"""

from typing import Dict, Any
from mcp.types import Prompt, PromptArgument, PromptMessage, TextContent


def get_mail_attachment_query_prompt(user_query: str) -> str:
    """Get mail attachment query prompt content"""
    return f"""
메일 첨부파일 조회 시스템입니다.

사용자 질의: {user_query}

사용 가능한 기능:
1. 특정 사용자의 메일 조회
2. 첨부파일 다운로드 및 텍스트 변환
3. 날짜 범위 및 필터 적용

조회할 사용자 ID와 조건을 지정해주세요.
"""


def get_format_email_results_prompt(format_style: str, include_attachments: bool, user_id: str) -> str:
    """Get format email results prompt content"""
    return f"""
📧 이메일 조회 결과 포맷팅 지침

포맷 스타일: {format_style}
첨부파일 포함: {include_attachments}
조회 사용자: {user_id}

다음 순서와 형식으로 테이블을 작성하세요:
** 모든 메일 리스트에 대해서 작성해 주세요 **

**📊 표 구성 (필수 열)**:
| 유형 | 날짜 | 발신자/수신자 | 제목 | 주요내용 | 응답필요성 | 응답기한 | 첨부 |

**각 열 작성 지침**:
1. **유형**: 
   - 받은메일: 발신자 이메일이 조회 사용자({user_id})와 다른 경우
   - 보낸메일: 발신자 이메일이 조회 사용자({user_id})와 같은 경우
2. **날짜**: YYYY-MM-DD HH:MM 형식
3. **발신자/수신자**: 
   - 받은메일: 발신자 이름 (이메일)
   - 보낸메일: → 수신자 이름 (이메일)
4. **제목**: 전체 제목 (너무 길면 ... 사용)
5. **주요내용**: 핵심 내용 1-2줄 요약
6. **응답필요성**: 
   - 받은메일: 🔴 중요 (응답 필요) / 🟢 일반 (참고용)
   - 보낸메일: ✅ 발송완료 / ⏳ 응답대기
7. **응답기한**: 구체적 날짜 또는 "즉시", "3일 내", "없음" 등
8. **첨부**: 파일명 (파일형식) 또는 "없음"

**응답 필요성 판단 기준**:
- 질문이 포함된 경우
- "회신 요청", "답변 부탁" 등의 표현
- 마감일이 명시된 경우
- 승인/검토 요청이 있는 경우

**예시**:
| 📥 | 2024-01-15 09:30 | 김철수 (kim@company.com) | 프로젝트 진행 현황 보고 | Q1 목표 달성률 85%, 추가 예산 승인 요청 | 🔴 긴급 | 1/17까지 | 보고서.pdf |
| 📨 | 2024-01-15 11:20 | → 이영희 (lee@company.com) | Re: 프로젝트 진행 현황 보고 | 예산 승인 완료, 진행하시기 바랍니다 | ✅ 발송완료 | - | - |

이메일 내용과 첨부파일을 분석하여 응답 필요성과 기한을 정확히 판단하세요.
"""


def get_attachment_summary_format_prompt(summary_length: str, highlight_sections: str) -> str:
    """Get attachment summary format prompt content"""
    return f"""
📎 첨부파일 내용 요약 지침

요약 길이: {summary_length}
강조 섹션: {highlight_sections}

첨부파일 내용을 다음 기준으로 정리하세요:

{'**간략 요약** (3-5줄)' if summary_length == 'brief' else ''}
{'- 핵심 내용만 추출' if summary_length == 'brief' else ''}
{'- 가장 중요한 정보 위주' if summary_length == 'brief' else ''}

{'**표준 요약** (10-15줄)' if summary_length == 'standard' else ''}
{'- 주요 섹션별로 정리' if summary_length == 'standard' else ''}
{'- 중요 데이터 포함' if summary_length == 'standard' else ''}

{'**상세 요약** (전체 구조 포함)' if summary_length == 'detailed' else ''}
{'- 모든 섹션 포함' if summary_length == 'detailed' else ''}
{'- 세부 내용까지 정리' if summary_length == 'detailed' else ''}

{f'강조할 내용: {highlight_sections}' if highlight_sections else ''}

포맷 규칙:
- 📅 날짜는 굵게 표시
- 👤 인물명은 밑줄
- 💰 금액/숫자는 하이라이트
- 🔑 중요 키워드는 백틱(`)으로 감싸기

명확하고 구조화된 형태로 제공하세요.
"""


async def get_prompt(name: str, arguments: Dict[str, Any]) -> PromptMessage:
    """Get specific prompt by name"""
    if name == "mail_attachment_query":
        user_query = arguments.get("user_query", "")
        prompt_content = get_mail_attachment_query_prompt(user_query)
        
    elif name == "format_email_results":
        format_style = arguments.get("format_style", "summary")
        include_attachments = arguments.get("include_attachments", True)
        user_id = arguments.get("user_id", "")
        prompt_content = get_format_email_results_prompt(format_style, include_attachments, user_id)
        
    elif name == "attachment_summary_format":
        summary_length = arguments.get("summary_length", "standard")
        highlight_sections = arguments.get("highlight_sections", "")
        prompt_content = get_attachment_summary_format_prompt(summary_length, highlight_sections)
        
    else:
        raise ValueError(f"Unknown prompt: {name}")
    
    return PromptMessage(
        role="assistant",
        content=TextContent(type="text", text=prompt_content)
    )