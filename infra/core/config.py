"""
IACSGraph 프로젝트의 설정 관리 시스템

환경 변수(.env)를 안전하게 로드하고 관리하는 설정 클래스를 제공합니다.
레이지 싱글톤 패턴으로 구현되어 어디서든 동일한 설정 객체를 참조할 수 있습니다.
"""

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from cryptography.fernet import Fernet
from dotenv import load_dotenv

from .exceptions import ConfigurationError
from .env_validator import EnvValidator
from .error_messages import ErrorCode, StandardError
from .logging_config import get_logger


logger = get_logger(__name__)

class Config:
    """애플리케이션 설정을 관리하는 클래스"""

    def __init__(self):
        """설정 초기화 및 환경 변수 로드"""
        self._load_environment()
        self._validate_with_new_system()
        self._validate_required_settings()

    def _load_environment(self) -> None:
        """환경 변수 파일(.env)을 로드"""
        # 프로젝트 루트에서 .env 파일 찾기
        project_root = Path(__file__).parent.parent.parent
        env_file = project_root / ".env"

        if env_file.exists():
            load_dotenv(env_file)
            logger.debug(f"✅ .env 파일 로드 완료: {env_file}")
        else:
            # .env 파일이 없는 경우 경고만 출력
            logger.warning(f"⚠️ .env 파일을 찾을 수 없습니다: {env_file}")

    def _validate_with_new_system(self) -> None:
        """새로운 환경변수 검증 시스템 사용"""
        validator = EnvValidator()
        success, result = validator.validate()

        if not success:
            logger.error("❌ 환경변수 검증 실패")
            validator.print_report(sys.stderr)

            # 필수 환경변수가 누락된 경우 예외 발생
            if result.get("required_missing"):
                raise StandardError(
                    ErrorCode.ENV_VAR_MISSING,
                    context={"missing": result["required_missing"]}
                )
        else:
            logger.info("✅ 환경변수 검증 성공")

            # 권장 환경변수 누락 경고
            if result.get("recommended_missing"):
                logger.warning(
                    f"⚠️ 권장 환경변수 누락 (일부 기능 제한): {', '.join(result['recommended_missing'])}"
                )

    def _validate_required_settings(self) -> None:
        """필수 설정값들이 있는지 검증"""
        required_settings = [
            "DATABASE_PATH",
            "ENCRYPTION_KEY",
        ]

        missing_settings = []
        for setting in required_settings:
            if not getattr(self, setting.lower(), None):
                missing_settings.append(setting)

        if missing_settings:
            raise ConfigurationError(
                f"필수 설정값이 누락되었습니다: {', '.join(missing_settings)}",
                details={"missing_settings": missing_settings},
            )

    # 데이터베이스 설정
    @property
    def database_path(self) -> str:
        """SQLite 데이터베이스 파일 경로"""
        path = os.getenv("DATABASE_PATH")

        # OnRender 환경 감지 및 특별 처리
        if os.getenv("RENDER"):
            # OnRender에서는 /opt/render/project/src가 작업 디렉토리
            if not path or path.startswith("./"):
                default_path = "/opt/render/project/src/data/graphapi.db"
                logger.info(f"OnRender 환경 감지: 데이터베이스 경로를 {default_path}로 설정")
                path = default_path
        elif not path:
            default_path = "./data/iacsgraph.db"
            logger.warning(
                f"\n{'='*60}\n"
                f"⚠️  DATABASE_PATH 환경변수가 설정되지 않았습니다.\n"
                f"    기본값을 사용합니다: {default_path}\n"
                f"    .env 파일에 DATABASE_PATH를 설정하려면:\n"
                f"    DATABASE_PATH=./data/your_database.db\n"
                f"{'='*60}"
            )
            path = default_path

        # 상대 경로를 절대 경로로 변환 (OnRender가 아닌 경우)
        if not Path(path).is_absolute() and not os.getenv("RENDER"):
            project_root = Path(__file__).parent.parent.parent
            path = str(project_root / path)

        # 디렉터리가 없으면 생성
        db_dir = Path(path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def dcr_database_path(self) -> str:
        """DCR 전용 SQLite 데이터베이스 파일 경로"""
        path = os.getenv("DCR_DATABASE_PATH")

        # OnRender 환경 감지 및 특별 처리
        if os.getenv("RENDER"):
            # OnRender에서는 /opt/render/project/src가 작업 디렉토리
            if not path or path.startswith("./"):
                default_path = "/opt/render/project/src/data/dcr.db"
                logger.info(f"OnRender 환경 감지: DCR 데이터베이스 경로를 {default_path}로 설정")
                path = default_path
        elif not path:
            default_path = "./data/dcr.db"
            logger.info(f"DCR_DATABASE_PATH 미설정. 기본값 사용: {default_path}")
            path = default_path

        # 상대 경로를 절대 경로로 변환 (OnRender가 아닌 경우)
        if not Path(path).is_absolute() and not os.getenv("RENDER"):
            project_root = Path(__file__).parent.parent.parent
            path = str(project_root / path)

        # 디렉터리가 없으면 생성
        db_dir = Path(path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        return path

    # 로깅 설정
    @property
    def log_level(self) -> str:
        """로그 레벨"""
        return os.getenv("LOG_LEVEL", "INFO").upper()

    # OpenAI 설정
    @property
    def openai_api_key(self) -> Optional[str]:
        """OpenAI API 키"""
        return os.getenv("OPENAI_API_KEY")

    # Azure OAuth 설정
    @property
    def azure_client_id(self) -> Optional[str]:
        """Azure AD 클라이언트 ID"""
        return os.getenv("AZURE_CLIENT_ID")

    @property
    def azure_client_secret(self) -> Optional[str]:
        """Azure AD 클라이언트 시크릿"""
        return os.getenv("AZURE_CLIENT_SECRET")

    @property
    def azure_tenant_id(self) -> str:
        """Azure AD 테넌트 ID"""
        return os.getenv("AZURE_TENANT_ID", "common")

    @property
    def azure_authority(self) -> str:
        """Azure AD 인증 엔드포인트"""
        return f"https://login.microsoftonline.com/{self.azure_tenant_id}"

    @property
    def azure_scopes(self) -> List[str]:
        """Azure Graph API 스코프"""
        scopes = os.getenv("AZURE_SCOPES", "User.Read Mail.Read offline_access")
        return [scope.strip() for scope in scopes.split()]

    @property
    def dcr_oauth_scope(self) -> str:
        """DCR OAuth scope (공백으로 구분된 문자열)"""
        return os.getenv(
            "DCR_OAUTH_SCOPE",
            "offline_access User.Read Mail.Read Mail.ReadWrite Mail.Send "
            "Files.Read Files.ReadWrite Calendars.Read Calendars.ReadWrite "
            "Chat.Read Chat.ReadWrite Notes.Read Notes.ReadWrite Notes.Create"
        )

    @property
    def dcr_oauth_scopes(self) -> List[str]:
        """DCR OAuth scope 리스트"""
        return [scope.strip() for scope in self.dcr_oauth_scope.split() if scope.strip()]

    @property
    def dcr_access_token_ttl_seconds(self) -> int:
        """DCR Bearer 토큰 기본 TTL(초)"""
        return int(os.getenv("DCR_ACCESS_TOKEN_TTL_SECONDS", "3600"))

    # OAuth 리다이렉트 설정
    @property
    def oauth_redirect_port(self) -> int:
        """OAuth 리다이렉트 포트"""
        return int(os.getenv("OAUTH_REDIRECT_PORT", "5000"))

    @property
    def oauth_redirect_path(self) -> str:
        """OAuth 리다이렉트 경로"""
        return os.getenv("OAUTH_REDIRECT_PATH", "/auth/callback")

    @property
    def oauth_redirect_uri(self) -> str:
        """OAuth 리다이렉트 URI"""
        # DCR_OAUTH_REDIRECT_URI 환경변수가 있으면 사용, 없으면 기본값 생성
        dcr_redirect_uri = os.getenv("DCR_OAUTH_REDIRECT_URI")
        if dcr_redirect_uri:
            return dcr_redirect_uri
        # AUTO_REGISTER_OAUTH_REDIRECT_URI도 확인
        auto_redirect_uri = os.getenv("AUTO_REGISTER_OAUTH_REDIRECT_URI")
        if auto_redirect_uri:
            return auto_redirect_uri
        # 둘 다 없으면 기본값 (레거시 호환성)
        return f"http://localhost:{self.oauth_redirect_port}{self.oauth_redirect_path}"

    # 애플리케이션 설정
    @property
    def batch_size(self) -> int:
        """배치 처리 크기"""
        return int(os.getenv("BATCH_SIZE", "20"))

    @property
    def token_refresh_buffer_minutes(self) -> int:
        """토큰 갱신 버퍼 시간(분)"""
        return int(os.getenv("TOKEN_REFRESH_BUFFER_MINUTES", "10"))

    # Microsoft Graph API 설정
    @property
    def graph_api_endpoint(self) -> str:
        """Microsoft Graph API 엔드포인트"""
        return os.getenv("GRAPH_API_ENDPOINT", "https://graph.microsoft.com/v1.0/")

    # 개발/디버그 설정
    @property
    def debug_mode(self) -> bool:
        """디버그 모드 여부"""
        return os.getenv("DEBUG", "False").lower() in ("true", "1", "yes", "on")

    @property
    def environment(self) -> str:
        """실행 환경 (development, production, test)"""
        return os.getenv("ENVIRONMENT", "development").lower()

    # 타임아웃 설정
    @property
    def http_timeout(self) -> int:
        """HTTP 요청 타임아웃(초)"""
        return int(os.getenv("HTTP_TIMEOUT", "30"))

    # Account 모듈 설정
    @property
    def encryption_key(self) -> str:
        """데이터 암호화 키 (Fernet 키)"""
        key = os.getenv("ENCRYPTION_KEY")
        if not key:
            # 자동으로 키 생성하여 사용자에게 제공
            generated_key = Fernet.generate_key().decode()
            logger.warning(
                f"\n{'='*60}\n"
                f"⚠️  ENCRYPTION_KEY가 설정되지 않았습니다.\n"
                f"    .env 파일에 아래 라인을 추가하세요:\n\n"
                f"    ENCRYPTION_KEY={generated_key}\n"
                f"{'='*60}"
            )
            raise ConfigurationError("ENCRYPTION_KEY가 설정되지 않았습니다")
        return key

    @property
    def enrollment_directory(self) -> str:
        """Enrollment 파일들이 위치한 디렉터리"""
        default_path = str(Path(__file__).parent.parent.parent / "enrollment")
        return os.getenv("ENROLLMENT_DIRECTORY", default_path)

    # 검증 메서드
    def is_oauth_configured(self) -> bool:
        """OAuth 설정이 완료되었는지 확인"""
        return bool(self.azure_client_id and self.azure_client_secret)

    def is_openai_configured(self) -> bool:
        """OpenAI 설정이 완료되었는지 확인"""
        return bool(self.openai_api_key)

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """임의의 환경 변수 값을 가져오기"""
        return os.getenv(key, default)

    # Mail Processor 설정
    @property
    def max_keywords_per_mail(self) -> int:
        """메일당 최대 키워드 수"""
        return int(os.getenv("MAX_KEYWORDS_PER_MAIL", "5"))

    @property
    def max_mails_per_account(self) -> int:
        """계정당 최대 메일 처리 수"""
        return int(os.getenv("MAX_MAILS_PER_ACCOUNT", "200"))

    # OpenRouter 설정
    @property
    def openrouter_api_key(self) -> Optional[str]:
        """OpenRouter API 키"""
        return os.getenv("OPENROUTER_API_KEY")

    @property
    def openrouter_model(self) -> str:
        """OpenRouter 모델"""
        return os.getenv("OPENROUTER_MODEL", "openai/gpt-3.5-turbo")

    @property
    def process_duplicate_mails(self) -> bool:
        """중복 메일도 다음 단계로 처리할지 여부"""
        return os.getenv("PROCESS_DUPLICATE_MAILS", "true").lower() in (
            "true",
            "1",
            "yes",
            "on",
        )

    # Attachment Manager 설정
    @property
    def attachment_default_save_path(self) -> str:
        """첨부파일 기본 저장 경로"""
        default_path = os.getenv("ATTACHMENT_DEFAULT_SAVE_PATH", "./filtered_attachments")
        # 디렉터리가 없으면 생성 (안전하게 처리)
        try:
            Path(default_path).mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as e:
            logger.warning(f"첨부파일 저장 경로 생성 실패 ({default_path}): {e}")
        return default_path

    @property
    def attachment_save_enabled(self) -> bool:
        """첨부파일 저장 활성화 여부"""
        return os.getenv("ATTACHMENT_SAVE_ENABLED", "true").lower() in (
            "true",
            "1",
            "yes",
            "on",
        )

    @property
    def attachment_text_extraction_enabled(self) -> bool:
        """첨부파일 텍스트 추출 후 LLM 전달 활성화 여부"""
        return os.getenv("ATTACHMENT_TEXT_EXTRACTION_ENABLED", "false").lower() in (
            "true",
            "1",
            "yes",
            "on",
        )

    def to_dict(self) -> dict:
        """설정을 딕셔너리로 반환 (민감한 정보 제외)"""
        return {
            "database_path": self.database_path,
            "log_level": self.log_level,
            "azure_tenant_id": self.azure_tenant_id,
            "azure_authority": self.azure_authority,
            "azure_scopes": self.azure_scopes,
            "oauth_redirect_port": self.oauth_redirect_port,
            "oauth_redirect_path": self.oauth_redirect_path,
            "oauth_redirect_uri": self.oauth_redirect_uri,
            "batch_size": self.batch_size,
            "token_refresh_buffer_minutes": self.token_refresh_buffer_minutes,
            "graph_api_endpoint": self.graph_api_endpoint,
            "debug_mode": self.debug_mode,
            "environment": self.environment,
            "http_timeout": self.http_timeout,
            "enrollment_directory": self.enrollment_directory,
            "max_keywords_per_mail": self.max_keywords_per_mail,
            "max_mails_per_account": self.max_mails_per_account,
            "openai_configured": self.is_openai_configured(),
            "oauth_configured": self.is_oauth_configured(),
        }


@lru_cache(maxsize=1)
def get_config() -> Config:
    """
    설정 인스턴스를 반환하는 레이지 싱글톤 함수

    Returns:
        Config: 설정 인스턴스
    """
    return Config()


# 편의를 위한 전역 설정 인스턴스
config = get_config()
