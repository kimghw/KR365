"""
IACSGraph 프로젝트의 구조화된 로깅 시스템

프로젝트 전반에서 사용할 표준화된 로거를 제공합니다.
새로운 logging_config 모듈과 통합하여 일관된 로깅을 제공합니다.
"""

import logging
from typing import Optional

# 새로운 logging_config 모듈 사용
from .logging_config import get_logging_config, get_logger as get_configured_logger


def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    """
    IACSGraph 프로젝트용 로거를 반환합니다.

    새로운 logging_config 모듈을 사용하여 일관된 로깅을 제공합니다.

    Args:
        name: 로거 이름 (일반적으로 모듈명)
        level: 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Returns:
        설정된 로거 인스턴스
    """
    return get_configured_logger(name, level)


def configure_root_logger(level: str = "INFO") -> None:
    """
    루트 로거 설정

    Args:
        level: 로그 레벨
    """
    config = get_logging_config()
    config.level = config._parse_level(level)
    config.configure_root_logger()


def update_all_loggers_level(level: str) -> None:
    """
    모든 기존 로거의 레벨을 업데이트

    Args:
        level: 새로운 로그 레벨
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # 루트 로거 업데이트
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    for handler in root_logger.handlers:
        handler.setLevel(log_level)

    # 모든 기존 로거 업데이트
    for name in logging.Logger.manager.loggerDict:
        logger = logging.getLogger(name)
        if logger.handlers:  # 핸들러가 있는 로거만 업데이트
            logger.setLevel(log_level)
            for handler in logger.handlers:
                handler.setLevel(log_level)


class LoggerMixin:
    """로거를 사용하는 클래스를 위한 믹스인"""

    @property
    def logger(self) -> logging.Logger:
        """클래스 전용 로거를 반환"""
        if not hasattr(self, "_logger"):
            self._logger = get_logger(self.__class__.__module__)
        return self._logger

    def log_debug(self, message: str, **kwargs) -> None:
        """디버그 메시지 로깅"""
        self.logger.debug(message, **kwargs)

    def log_info(self, message: str, **kwargs) -> None:
        """정보 메시지 로깅"""
        self.logger.info(message, **kwargs)

    def log_warning(self, message: str, **kwargs) -> None:
        """경고 메시지 로깅"""
        self.logger.warning(message, **kwargs)

    def log_error(self, message: str, **kwargs) -> None:
        """오류 메시지 로깅"""
        self.logger.error(message, **kwargs)

    def log_critical(self, message: str, **kwargs) -> None:
        """치명적 오류 메시지 로깅"""
        self.logger.critical(message, **kwargs)


# ============================================================================
# 표준화된 로깅 헬퍼 함수들 (DCR, FastAPI 등 공통 사용)
# ============================================================================

def log_db_operation(
    logger: logging.Logger,
    operation: str,
    query: str,
    params: tuple = (),
    affected_rows: Optional[int] = None,
    enabled: bool = True
) -> None:
    """데이터베이스 작업 표준화된 로깅

    Args:
        logger: 로거 인스턴스
        operation: 작업 타입 (EXECUTE_START, EXECUTE_SUCCESS, FETCH_ONE, FETCH_ALL 등)
        query: SQL 쿼리
        params: 쿼리 파라미터
        affected_rows: 영향받은 행 수
        enabled: 로깅 활성화 여부 (환경변수로 제어 가능)
    """
    if not enabled:
        return

    from datetime import datetime

    # 쿼리 정리 (여러 줄을 한 줄로)
    clean_query = " ".join(query.split())

    # 작업 타입 및 이모지 판별
    query_upper = clean_query.upper()

    if operation in ["EXECUTE_START", "EXECUTE_SUCCESS", "FETCH_ONE", "FETCH_ALL"]:
        if operation == "EXECUTE_START":
            emoji = "🚀"
            operation_type = "EXECUTE_START"
        elif operation == "EXECUTE_SUCCESS":
            emoji = "✅"
            operation_type = "EXECUTE_SUCCESS"
        elif operation in ["FETCH_ONE", "FETCH_ALL"]:
            emoji = "🔍"
            operation_type = operation
    elif query_upper.startswith("INSERT"):
        operation_type = "INSERT"
        emoji = "➕"
    elif query_upper.startswith("UPDATE"):
        operation_type = "UPDATE"
        emoji = "📝"
    elif query_upper.startswith("DELETE"):
        operation_type = "DELETE"
        emoji = "🗑️"
    elif query_upper.startswith("SELECT"):
        operation_type = "SELECT"
        emoji = "🔍"
    else:
        operation_type = "OTHER"
        emoji = "⚙️"

    # 테이블 이름 추출
    table_name = "unknown"
    if "FROM" in query_upper:
        parts = query_upper.split("FROM")
        if len(parts) > 1:
            table_parts = parts[1].strip().split()
            if table_parts:
                table_name = table_parts[0]
    elif "INTO" in query_upper:
        parts = query_upper.split("INTO")
        if len(parts) > 1:
            table_parts = parts[1].strip().split()
            if table_parts:
                table_name = table_parts[0]
    elif "UPDATE" in query_upper:
        parts = query_upper.split("UPDATE")
        if len(parts) > 1:
            table_parts = parts[1].strip().split()
            if table_parts:
                table_name = table_parts[0]

    # 파라미터 마스킹 (민감정보 보호)
    masked_params = []
    for param in params:
        if param and isinstance(param, str):
            if any(keyword in str(param).lower() for keyword in ["token", "secret", "password", "key"]):
                masked_params.append("***MASKED***")
            elif len(str(param)) > 50:
                masked_params.append(f"{str(param)[:20]}...{str(param)[-10:]}")
            else:
                masked_params.append(param)
        else:
            masked_params.append(param)

    # 로그 메시지 구성
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    log_msg = f"[{timestamp}] {emoji} DB {operation_type} on {table_name}"

    if affected_rows is not None:
        log_msg += f" ({affected_rows} rows affected)"

    if masked_params:
        log_msg += f" | Params: {masked_params[:5]}"
        if len(masked_params) > 5:
            log_msg += f" ... and {len(masked_params) - 5} more"

    # 쿼리 미리보기
    if len(clean_query) > 100:
        log_msg += f" | Query: {clean_query[:100]}..."
    else:
        log_msg += f" | Query: {clean_query}"

    logger.info(log_msg)


def log_api_request(
    logger: logging.Logger,
    method: str,
    path: str,
    client_ip: Optional[str] = None,
    user_id: Optional[str] = None,
    request_id: Optional[str] = None
) -> None:
    """API 요청 표준화된 로깅

    Args:
        logger: 로거 인스턴스
        method: HTTP 메서드
        path: 요청 경로
        client_ip: 클라이언트 IP
        user_id: 사용자 ID
        request_id: 요청 ID (추적용)
    """
    from datetime import datetime

    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    log_msg = f"[{timestamp}] 📥 {method} {path}"

    if client_ip:
        log_msg += f" | IP: {client_ip}"
    if user_id:
        log_msg += f" | User: {user_id}"
    if request_id:
        log_msg += f" | ReqID: {request_id[:8]}"

    logger.info(log_msg)


def log_api_response(
    logger: logging.Logger,
    method: str,
    path: str,
    status_code: int,
    duration_ms: Optional[float] = None,
    request_id: Optional[str] = None
) -> None:
    """API 응답 표준화된 로깅

    Args:
        logger: 로거 인스턴스
        method: HTTP 메서드
        path: 요청 경로
        status_code: HTTP 상태 코드
        duration_ms: 처리 시간 (밀리초)
        request_id: 요청 ID (추적용)
    """
    from datetime import datetime

    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

    # 상태 코드별 이모지
    if 200 <= status_code < 300:
        emoji = "✅"
    elif 300 <= status_code < 400:
        emoji = "🔀"
    elif 400 <= status_code < 500:
        emoji = "⚠️"
    else:
        emoji = "❌"

    log_msg = f"[{timestamp}] {emoji} {method} {path} → {status_code}"

    if duration_ms is not None:
        log_msg += f" | {duration_ms:.2f}ms"
    if request_id:
        log_msg += f" | ReqID: {request_id[:8]}"

    logger.info(log_msg)