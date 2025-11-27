"""Configuration module for MCP Server"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from infra.core.logger import get_logger

logger = get_logger(__name__)


class Config:
    """Configuration manager for MCP Server"""

    def __init__(self, config_path: str = None):
        self._config = {}
        self._user_config = {}
        self._load_config(config_path)
        self._process_paths()

    def _load_config(self, config_path: str = None):
        """Load configuration from file"""
        if config_path is None:
            # Check environment variable first
            env_path = os.getenv("MCP_CONFIG_PATH")
            if env_path:
                config_path = Path(env_path)
            else:
                # Default path relative to this file
                config_path = Path(__file__).parent.parent / "config.json"

        try:
            # Load main config
            with open(config_path, "r", encoding="utf-8") as f:
                config_str = f.read()
            self._config = json.loads(config_str)

            # Try to load user config (optional)
            user_config_path = config_path.parent / "config.user.json"
            if user_config_path.exists():
                try:
                    with open(user_config_path, "r", encoding="utf-8") as f:
                        self._user_config = json.load(f)
                    logger.info(f"Loaded user config from {user_config_path}")
                except Exception as e:
                    logger.warning(f"Failed to load user config: {e}")

        except FileNotFoundError:
            # Use default configuration if file not found
            self._config = self._get_default_config()
        except Exception as e:
            logger.info(f"Error loading config: {e}")
            self._config = self._get_default_config()

    def _process_paths(self):
        """Process path configurations and replace environment variables"""
        # Merge user config over main config
        if self._user_config:
            self._merge_configs(self._config, self._user_config)

        # Process environment variables in paths
        if "paths" in self._config:
            paths = self._config["paths"]
            for key, value in paths.items():
                # Skip metadata keys (starting with _ or named 'comment')
                if key.startswith("_") or key in [
                    "comment",
                    "create_if_not_exists",
                    "use_absolute_paths",
                ]:
                    continue

                if isinstance(value, str):
                    # Replace environment variables
                    value = self._expand_env_vars(value)
                    paths[key] = value

                    # Create directories if needed (except for log files)
                    if paths.get("create_if_not_exists", True) and not key.endswith(
                        "_file"
                    ):
                        path = Path(value)
                        if not path.suffix:  # It's a directory, not a file
                            path.mkdir(parents=True, exist_ok=True)

    def _expand_env_vars(self, path_str: str) -> str:
        """Expand environment variables in path string"""
        # Replace ${VAR} or $VAR with environment variable values
        import re

        def replace_var(match):
            var_name = match.group(1) or match.group(2)
            return os.environ.get(var_name, match.group(0))

        # Handle ${VAR} format
        path_str = re.sub(r"\$\{([^}]+)\}", replace_var, path_str)
        # Handle $VAR format
        path_str = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", replace_var, path_str)

        # Expand user home directory
        path_str = os.path.expanduser(path_str)

        # Convert to absolute path if relative
        path = Path(path_str)
        if not path.is_absolute():
            path = Path.cwd() / path

        return str(path)

    def _merge_configs(self, base: dict, override: dict):
        """Recursively merge override config into base config"""
        for key, value in override.items():
            if key == "comment":  # Skip comment fields
                continue
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_configs(base[key], value)
            else:
                base[key] = value

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration"""
        # Use data directory within the module
        module_dir = Path(__file__).parent.parent
        base_dir = module_dir / "data"

        return {
            "mcp": {
                "server_name": "email-mcp-server",
                "command": "python",
                "args": ["-m", "modules.mail_query_without_db.mcp_server.http_server"],
            },
            "paths": {
                "base_dir": str(base_dir),
                "attachments_dir": str(base_dir / "attachments"),
                "emails_dir": str(base_dir / "emails"),
                "exports_dir": str(base_dir / "exports"),
                "temp_dir": str(base_dir / "temp"),
                "log_file": str(base_dir / "logs" / "mcp_mail_server.log"),
                "use_absolute_paths": True,
                "create_if_not_exists": True,
            },
            "server": {"default_host": "0.0.0.0", "default_port": 8001},
            "email": {
                "blocked_senders": [],
                "default_days_back": 30,
                "default_max_mails": 300,
                "csv_encoding": "utf-8-sig",
            },
            "file_handling": {
                "max_preview_length": 3000,
                "max_filename_length": 200,
                "max_file_size_mb": 50,
                "cleanup_after_query": True,
            },
        }

    # Path properties
    @property
    def base_dir(self) -> Path:
        """Get base directory path"""
        return Path(
            self._config.get("paths", {}).get("base_dir", Path.home() / "mcp_data")
        )

    @property
    def attachments_dir(self) -> Path:
        """Get attachments directory path"""
        return Path(
            self._config.get("paths", {}).get(
                "attachments_dir", self.base_dir / "attachments"
            )
        )

    @property
    def emails_dir(self) -> Path:
        """Get emails directory path"""
        return Path(
            self._config.get("paths", {}).get("emails_dir", self.base_dir / "emails")
        )

    @property
    def exports_dir(self) -> Path:
        """Get exports directory path"""
        return Path(
            self._config.get("paths", {}).get("exports_dir", self.base_dir / "exports")
        )

    @property
    def temp_dir(self) -> Path:
        """Get temp directory path"""
        return Path(
            self._config.get("paths", {}).get("temp_dir", self.base_dir / "temp")
        )

    @property
    def log_file(self) -> Path:
        """Get log file path"""
        return Path(
            self._config.get("paths", {}).get(
                "log_file", self.base_dir / "logs" / "mcp_mail_server.log"
            )
        )

    # Backward compatibility - keep existing properties
    @property
    def save_directory(self) -> str:
        """Get save directory (backward compatibility)"""
        return str(self.emails_dir)

    # Email configuration
    @property
    def blocked_senders(self) -> list:
        """Get blocked senders list from environment variable or config"""
        # 1순위: 환경변수 BLOCKED_SENDER_PATTERNS
        env_blocked = os.getenv("BLOCKED_SENDER_PATTERNS", "").strip()
        if env_blocked:
            # 쉼표로 구분된 패턴을 리스트로 변환
            return [
                pattern.strip() for pattern in env_blocked.split(",") if pattern.strip()
            ]

        # 2순위: config.json의 blocked_senders
        return self._config.get("email", {}).get("blocked_senders", [])

    @property
    def default_days_back(self) -> int:
        """Get default days back"""
        return self._config.get("email", {}).get("default_days_back", 30)

    @property
    def default_max_mails(self) -> int:
        """Get default max mails"""
        return self._config.get("email", {}).get("default_max_mails", 300)

    # File handling configuration
    @property
    def max_file_size_mb(self) -> int:
        """Get max file size in MB"""
        return self._config.get("file_handling", {}).get("max_file_size_mb", 50)

    @property
    def max_filename_length(self) -> int:
        """Get max filename length"""
        return self._config.get("file_handling", {}).get("max_filename_length", 200)

    @property
    def cleanup_after_query(self) -> bool:
        """Get cleanup after query flag"""
        return self._config.get("file_handling", {}).get("cleanup_after_query", True)

    # Server configuration
    @property
    def default_host(self) -> str:
        """Get default host"""
        return self._config.get("server", {}).get("default_host", "0.0.0.0")

    @property
    def default_port(self) -> int:
        """Get default port"""
        return self._config.get("server", {}).get("default_port", 8001)

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by key (dot notation supported)"""
        keys = key.split(".")
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def get_path_config(self) -> Dict[str, str]:
        """Get all path configurations"""
        return {
            "base_dir": str(self.base_dir),
            "attachments_dir": str(self.attachments_dir),
            "emails_dir": str(self.emails_dir),
            "exports_dir": str(self.exports_dir),
            "temp_dir": str(self.temp_dir),
            "log_file": str(self.log_file),
        }

    def print_config_info(self):
        """Print current configuration information"""
        print("\n" + "=" * 60)
        print("MCP Server Configuration")
        print("=" * 60)

        print("\nPath Settings:")
        for key, value in self.get_path_config().items():
            print(f"  {key:20}: {value}")

        print("\nEmail Settings:")
        print(f"  Default days back   : {self.default_days_back}")
        print(f"  Default max mails   : {self.default_max_mails}")
        print(f"  Blocked senders     : {len(self.blocked_senders)} configured")

        print("\nFile Handling:")
        print(f"  Max file size (MB)  : {self.max_file_size_mb}")
        print(f"  Max filename length : {self.max_filename_length}")
        print(f"  Cleanup after query : {self.cleanup_after_query}")

        print("\nServer Settings:")
        print(f"  Default host        : {self.default_host}")
        print(f"  Default port        : {self.default_port}")
        print("=" * 60 + "\n")
