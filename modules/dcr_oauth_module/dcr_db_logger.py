"""
DCR Database Operation Logger
DCR 데이터베이스의 모든 작업을 상세히 로깅하는 모듈
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Union
import traceback

from infra.core.logger import get_logger

logger = get_logger(__name__)


class DCRDatabaseLogger:
    """DCR 데이터베이스 작업 로거"""

    def __init__(self, log_dir: str = "./logs"):
        """
        DCR Database Logger 초기화

        Args:
            log_dir: 로그 파일을 저장할 디렉토리
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # DCR DB 전용 로그 파일
        self.log_file = self.log_dir / "dcr_db_operations.log"

        # 환경변수로 로깅 활성화 여부 확인
        self.enabled = os.getenv("DCR_DB_LOGGING", "true").lower() == "true"

        if self.enabled:
            logger.info(f"DCR DB 로깅 활성화됨. 로그 파일: {self.log_file}")

    def _write_log(self, log_entry: Dict[str, Any]):
        """로그 엔트리를 파일에 기록"""
        if not self.enabled:
            return

        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                # JSON 형식으로 저장 (한 줄에 하나의 로그)
                json_entry = json.dumps(log_entry, ensure_ascii=False, default=str)
                f.write(json_entry + '\n')
        except Exception as e:
            logger.error(f"로그 파일 쓰기 실패: {e}")

    def log_operation(
        self,
        operation: str,
        table: str,
        data: Optional[Dict[str, Any]] = None,
        query: Optional[str] = None,
        params: Optional[Any] = None,
        result: Optional[Any] = None,
        error: Optional[str] = None,
        user_email: Optional[str] = None,
        client_id: Optional[str] = None
    ):
        """
        데이터베이스 작업 로깅

        Args:
            operation: 작업 유형 (INSERT, UPDATE, DELETE, SELECT 등)
            table: 대상 테이블
            data: 작업 데이터
            query: 실행된 SQL 쿼리
            params: 쿼리 파라미터
            result: 작업 결과
            error: 에러 메시지 (실패 시)
            user_email: 작업 수행 사용자
            client_id: 클라이언트 ID
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "table": table,
            "success": error is None
        }

        # 선택적 필드 추가
        if data:
            log_entry["data"] = data
        if query:
            log_entry["query"] = query
        if params:
            log_entry["params"] = params
        if result is not None:
            log_entry["result"] = result
        if error:
            log_entry["error"] = error
            log_entry["traceback"] = traceback.format_exc()
        if user_email:
            log_entry["user_email"] = user_email
        if client_id:
            log_entry["client_id"] = client_id

        # 파일에 기록
        self._write_log(log_entry)

        # 콘솔 로깅 (중요 작업만)
        if operation in ["INSERT", "UPDATE", "DELETE"]:
            if error:
                logger.error(
                    f"DCR DB {operation} 실패 - Table: {table}, "
                    f"User: {user_email or 'N/A'}, Error: {error}"
                )
            else:
                logger.info(
                    f"DCR DB {operation} 성공 - Table: {table}, "
                    f"User: {user_email or 'N/A'}"
                )

    def log_client_registration(
        self,
        client_id: str,
        user_email: str,
        action: str,
        details: Optional[Dict[str, Any]] = None,
        success: bool = True,
        error: Optional[str] = None
    ):
        """
        클라이언트 등록/수정/삭제 로깅

        Args:
            client_id: 클라이언트 ID
            user_email: 사용자 이메일
            action: 작업 (register, update, delete)
            details: 추가 상세 정보
            success: 성공 여부
            error: 에러 메시지
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "CLIENT_REGISTRATION",
            "action": action,
            "client_id": client_id,
            "user_email": user_email,
            "success": success
        }

        if details:
            log_entry["details"] = details
        if error:
            log_entry["error"] = error

        self._write_log(log_entry)

        # 콘솔 로깅
        if success:
            logger.info(f"클라이언트 {action} 성공: {client_id} ({user_email})")
        else:
            logger.error(f"클라이언트 {action} 실패: {client_id} ({user_email}) - {error}")

    def log_token_operation(
        self,
        operation: str,
        user_email: str,
        token_type: str = "access_token",
        success: bool = True,
        error: Optional[str] = None,
        expires_in: Optional[int] = None
    ):
        """
        토큰 관련 작업 로깅

        Args:
            operation: 작업 (generate, refresh, revoke)
            user_email: 사용자 이메일
            token_type: 토큰 타입 (access_token, refresh_token)
            success: 성공 여부
            error: 에러 메시지
            expires_in: 토큰 만료 시간 (초)
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "TOKEN_OPERATION",
            "operation": operation,
            "user_email": user_email,
            "token_type": token_type,
            "success": success
        }

        if expires_in:
            log_entry["expires_in"] = expires_in
        if error:
            log_entry["error"] = error

        self._write_log(log_entry)

        # 콘솔 로깅
        if success:
            logger.debug(f"토큰 {operation} 성공: {user_email} ({token_type})")
        else:
            logger.error(f"토큰 {operation} 실패: {user_email} - {error}")

    def get_recent_logs(self, limit: int = 100, operation: Optional[str] = None) -> list:
        """
        최근 로그 조회

        Args:
            limit: 조회할 로그 개수
            operation: 특정 작업만 필터링 (선택사항)

        Returns:
            로그 엔트리 리스트
        """
        if not self.log_file.exists():
            return []

        logs = []
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                # 파일 끝에서부터 읽기 위해 전체 읽기 후 역순 처리
                lines = f.readlines()
                for line in reversed(lines[-limit:]):
                    try:
                        log_entry = json.loads(line.strip())
                        if operation is None or log_entry.get('operation') == operation:
                            logs.append(log_entry)
                        if len(logs) >= limit:
                            break
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"로그 파일 읽기 실패: {e}")

        return logs

    def get_statistics(self) -> Dict[str, Any]:
        """
        DCR DB 작업 통계 조회

        Returns:
            작업별 통계 정보
        """
        if not self.log_file.exists():
            return {"message": "No logs found"}

        stats = {
            "total_operations": 0,
            "operations_by_type": {},
            "success_rate": 0,
            "failed_operations": [],
            "recent_errors": []
        }

        success_count = 0

        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        log_entry = json.loads(line.strip())
                        stats["total_operations"] += 1

                        # 작업별 카운트
                        op_type = log_entry.get('operation', 'UNKNOWN')
                        stats["operations_by_type"][op_type] = \
                            stats["operations_by_type"].get(op_type, 0) + 1

                        # 성공/실패 카운트
                        if log_entry.get('success', True):
                            success_count += 1
                        else:
                            # 실패한 작업 기록 (최근 10개만)
                            if len(stats["failed_operations"]) < 10:
                                stats["failed_operations"].append({
                                    "timestamp": log_entry.get('timestamp'),
                                    "operation": op_type,
                                    "error": log_entry.get('error', 'Unknown error')
                                })

                        # 최근 에러 (최근 5개만)
                        if log_entry.get('error') and len(stats["recent_errors"]) < 5:
                            stats["recent_errors"].append({
                                "timestamp": log_entry.get('timestamp'),
                                "operation": op_type,
                                "error": log_entry.get('error')
                            })

                    except json.JSONDecodeError:
                        continue

            # 성공률 계산
            if stats["total_operations"] > 0:
                stats["success_rate"] = round(
                    (success_count / stats["total_operations"]) * 100, 2
                )

        except Exception as e:
            logger.error(f"통계 생성 실패: {e}")
            stats["error"] = str(e)

        return stats


# 싱글톤 인스턴스
_dcr_db_logger = None

def get_dcr_db_logger() -> DCRDatabaseLogger:
    """DCR DB 로거 싱글톤 인스턴스 반환"""
    global _dcr_db_logger
    if _dcr_db_logger is None:
        _dcr_db_logger = DCRDatabaseLogger()
    return _dcr_db_logger