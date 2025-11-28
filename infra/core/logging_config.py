"""
통합 로깅 설정 시스템

애플리케이션 전체의 로깅을 일관되게 관리하는 설정 모듈입니다.
구조화된 로깅과 다양한 출력 형식을 지원합니다.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

import colorlog


class LogLevel(Enum):
    """로그 레벨 정의"""
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


class LogFormat(Enum):
    """로그 출력 형식"""
    SIMPLE = "simple"  # 간단한 형식
    DETAILED = "detailed"  # 상세 형식
    JSON = "json"  # JSON 형식
    COLORED = "colored"  # 컬러 콘솔 출력


class StructuredFormatter(logging.Formatter):
    """구조화된 JSON 로그 포매터"""

    def format(self, record: logging.LogRecord) -> str:
        """로그 레코드를 JSON 형식으로 변환"""
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 추가 컨텍스트 정보가 있으면 포함
        if hasattr(record, "extra_data"):
            log_data["context"] = record.extra_data

        # 예외 정보가 있으면 포함
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


class LoggingConfig:
    """통합 로깅 설정 클래스"""

    # 로그 형식 템플릿
    FORMATS = {
        LogFormat.SIMPLE: "%(levelname)s - %(name)s - %(message)s",
        LogFormat.DETAILED: "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
        LogFormat.COLORED: "%(log_color)s%(levelname)-8s%(reset)s %(blue)s%(name)s%(reset)s - %(message)s",
    }

    # 로그 레벨 색상 설정
    LOG_COLORS = {
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'red,bg_white',
    }

    def __init__(
        self,
        level: str = "INFO",
        format_type: LogFormat = LogFormat.DETAILED,
        log_dir: Optional[Path] = None,
        enable_file_logging: bool = True,
        enable_console_logging: bool = True,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5
    ):
        """
        로깅 설정 초기화

        Args:
            level: 로그 레벨
            format_type: 로그 형식
            log_dir: 로그 파일 저장 디렉토리
            enable_file_logging: 파일 로깅 활성화 여부
            enable_console_logging: 콘솔 로깅 활성화 여부
            max_bytes: 로그 파일 최대 크기
            backup_count: 백업 파일 개수
        """
        self.level = self._parse_level(level)
        self.format_type = format_type
        self.log_dir = log_dir or Path("logs")
        self.enable_file_logging = enable_file_logging
        self.enable_console_logging = enable_console_logging
        self.max_bytes = max_bytes
        self.backup_count = backup_count

        # 로그 디렉토리 생성
        if self.enable_file_logging:
            self.log_dir.mkdir(parents=True, exist_ok=True)

        # 설정된 로거 추적
        self._configured_loggers = set()

    def _parse_level(self, level: str) -> int:
        """문자열 로그 레벨을 정수로 변환"""
        try:
            return LogLevel[level.upper()].value
        except KeyError:
            print(f"⚠️  알 수 없는 로그 레벨: {level}. INFO로 설정합니다.")
            return LogLevel.INFO.value

    def _get_log_file_path(self, logger_name: str) -> Path:
        """
        로거 이름을 기반으로 로그 파일 경로 생성 (모듈별로 하나의 파일)

        Examples:
            infra.core.database -> logs/infra/core.log
            infra.core.config -> logs/infra/core.log (같은 파일)
            modules.account.account_repository -> logs/modules/account.log
            modules.account.account_orchestrator -> logs/modules/account.log (같은 파일)
            modules.auth.auth_orchestrator -> logs/modules/auth.log
            modules.mail_query_without_db.mcp_server.http_server -> logs/modules/mcp_server.log
            __main__ -> logs/__main__.log
        """
        # 특수 케이스: __main__, app 등
        if logger_name in ['__main__', 'app']:
            return self.log_dir / f"{logger_name}.log"

        # 로거 이름을 점으로 분리
        parts = logger_name.split('.')

        # 최소 2개 부분이 있어야 디렉터리 구조 생성
        if len(parts) < 2:
            return self.log_dir / f"{logger_name}.log"

        # 디렉터리 구조 매핑
        # infra.core.* -> logs/infra/core.log (모두 하나의 파일)
        # modules.account.* -> logs/modules/account.log (모두 하나의 파일)
        # modules.auth.* -> logs/modules/auth.log (모두 하나의 파일)
        # modules.mail_query_without_db.mcp_server.* -> logs/modules/mcp_server.log (모두 하나의 파일)

        if parts[0] == 'infra':
            # infra.core.* -> logs/infra/core.log
            if len(parts) >= 2:
                log_dir = self.log_dir / parts[0]
                log_dir.mkdir(parents=True, exist_ok=True)
                return log_dir / f"{parts[1]}.log"
            else:
                return self.log_dir / 'infra' / 'infra.log'

        elif parts[0] == 'modules':
            # modules.mail_query_without_db.mcp_server.* -> logs/modules/mcp_server.log
            if 'mcp_server' in parts:
                log_dir = self.log_dir / 'modules'
                log_dir.mkdir(parents=True, exist_ok=True)
                return log_dir / 'mcp_server.log'

            # modules.account.*, modules.auth.*, modules.outlook_mail_query.* 등
            elif len(parts) >= 2:
                module_name = parts[1]  # account, auth, mail_query 등
                log_dir = self.log_dir / 'modules'
                log_dir.mkdir(parents=True, exist_ok=True)
                return log_dir / f"{module_name}.log"

        # 기본: 평면 구조로 폴백
        return self.log_dir / f"{logger_name.replace('.', '_')}.log"

    def get_formatter(self, format_type: Optional[LogFormat] = None) -> logging.Formatter:
        """로그 포매터 생성"""
        format_type = format_type or self.format_type

        if format_type == LogFormat.JSON:
            return StructuredFormatter()
        elif format_type == LogFormat.COLORED:
            return colorlog.ColoredFormatter(
                self.FORMATS[LogFormat.COLORED],
                log_colors=self.LOG_COLORS
            )
        else:
            format_string = self.FORMATS.get(format_type, self.FORMATS[LogFormat.DETAILED])
            return logging.Formatter(format_string)

    def configure_logger(
        self,
        logger_name: str,
        level: Optional[str] = None,
        format_type: Optional[LogFormat] = None,
        propagate: bool = False
    ) -> logging.Logger:
        """
        특정 로거 설정

        Args:
            logger_name: 로거 이름
            level: 로그 레벨 (None이면 기본값 사용)
            format_type: 로그 형식 (None이면 기본값 사용)
            propagate: 상위 로거로 전파 여부

        Returns:
            설정된 로거
        """
        logger = logging.getLogger(logger_name)

        # 이미 설정된 로거면 반환
        if logger_name in self._configured_loggers:
            return logger

        # 레벨 설정
        log_level = self._parse_level(level) if level else self.level
        logger.setLevel(log_level)
        logger.propagate = propagate

        # 기존 핸들러 제거
        logger.handlers.clear()

        # 콘솔 핸들러 추가
        if self.enable_console_logging:
            # MCP_STDIO_MODE 환경 변수가 설정되어 있으면 stderr 사용
            import os
            if os.getenv('MCP_STDIO_MODE') == '1':
                console_stream = sys.stderr
            else:
                console_stream = sys.stdout

            console_handler = logging.StreamHandler(console_stream)
            console_handler.setLevel(log_level)

            # 콘솔은 컬러 포맷 사용
            if console_stream.isatty() and not os.getenv('NO_COLOR'):  # TTY이고 NO_COLOR가 없는 경우만 컬러 사용
                console_handler.setFormatter(self.get_formatter(LogFormat.COLORED))
            else:
                console_handler.setFormatter(self.get_formatter(format_type))

            logger.addHandler(console_handler)

        # 파일 핸들러 추가
        if self.enable_file_logging:
            from logging.handlers import RotatingFileHandler

            # 로거 이름을 디렉터리 구조로 변환
            log_file = self._get_log_file_path(logger_name)

            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=self.max_bytes,
                backupCount=self.backup_count,
                encoding='utf-8'
            )
            file_handler.setLevel(log_level)
            file_handler.setFormatter(self.get_formatter(format_type or self.format_type))
            logger.addHandler(file_handler)

        self._configured_loggers.add(logger_name)
        return logger

    def configure_root_logger(self) -> None:
        """루트 로거 설정"""
        import os

        root_logger = logging.getLogger()
        root_logger.setLevel(self.level)
        root_logger.handlers.clear()

        # 콘솔 핸들러
        if self.enable_console_logging:
            # MCP_STDIO_MODE 환경 변수가 설정되어 있으면 stderr 사용
            if os.getenv('MCP_STDIO_MODE') == '1':
                console_stream = sys.stderr
            else:
                console_stream = sys.stdout

            console_handler = logging.StreamHandler(console_stream)
            console_handler.setLevel(self.level)

            # NO_COLOR 환경 변수 체크
            if console_stream.isatty() and not os.getenv('NO_COLOR'):
                console_handler.setFormatter(self.get_formatter(LogFormat.COLORED))
            else:
                console_handler.setFormatter(self.get_formatter(LogFormat.DETAILED))

            root_logger.addHandler(console_handler)

        # 파일 핸들러
        if self.enable_file_logging:
            from logging.handlers import RotatingFileHandler

            log_file = self.log_dir / "app.log"
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=self.max_bytes,
                backupCount=self.backup_count,
                encoding='utf-8'
            )
            file_handler.setLevel(self.level)
            file_handler.setFormatter(self.get_formatter())
            root_logger.addHandler(file_handler)

    def get_logger_config(self) -> Dict[str, Any]:
        """현재 로깅 설정을 딕셔너리로 반환"""
        return {
            "level": logging.getLevelName(self.level),
            "format": self.format_type.value,
            "log_directory": str(self.log_dir),
            "file_logging": self.enable_file_logging,
            "console_logging": self.enable_console_logging,
            "max_file_size": self.max_bytes,
            "backup_count": self.backup_count,
            "configured_loggers": list(self._configured_loggers)
        }

    @classmethod
    def from_env(cls) -> "LoggingConfig":
        """환경변수에서 로깅 설정 생성"""
        import os

        level = os.getenv("LOG_LEVEL", "INFO")
        log_format = os.getenv("LOG_FORMAT", "detailed")
        log_dir = os.getenv("LOG_DIR", "logs")
        enable_file = os.getenv("ENABLE_FILE_LOGGING", "true").lower() == "true"
        enable_console = os.getenv("ENABLE_CONSOLE_LOGGING", "true").lower() == "true"

        # 로그 형식 파싱
        try:
            format_type = LogFormat[log_format.upper()]
        except KeyError:
            format_type = LogFormat.DETAILED

        return cls(
            level=level,
            format_type=format_type,
            log_dir=Path(log_dir),
            enable_file_logging=enable_file,
            enable_console_logging=enable_console
        )


# 전역 로깅 설정 인스턴스
_logging_config: Optional[LoggingConfig] = None


def setup_logging(
    level: str = "INFO",
    format_type: LogFormat = LogFormat.DETAILED,
    log_dir: Optional[Path] = None
) -> LoggingConfig:
    """
    전역 로깅 설정 초기화

    Args:
        level: 로그 레벨
        format_type: 로그 형식
        log_dir: 로그 디렉토리

    Returns:
        LoggingConfig: 로깅 설정 인스턴스
    """
    global _logging_config

    _logging_config = LoggingConfig(
        level=level,
        format_type=format_type,
        log_dir=log_dir
    )
    _logging_config.configure_root_logger()

    return _logging_config


def get_logging_config() -> LoggingConfig:
    """현재 로깅 설정 반환"""
    global _logging_config

    if _logging_config is None:
        _logging_config = LoggingConfig.from_env()
        _logging_config.configure_root_logger()

    return _logging_config


def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    """
    설정된 로거 반환

    Args:
        name: 로거 이름
        level: 로그 레벨 (선택적)

    Returns:
        logging.Logger: 설정된 로거
    """
    config = get_logging_config()
    return config.configure_logger(name, level=level)