"""Tests for web dashboard functionality"""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from modules.web_dashboard.dashboard import DashboardService


class TestDashboardService:
    """Test DashboardService functionality"""

    @patch('modules.web_dashboard.dashboard.UNIFIED_PID_FILE')
    @patch('subprocess.run')
    def test_get_server_status_running(self, mock_run, mock_pid_file):
        """Test getting server status when running"""
        mock_pid_file.exists.return_value = True
        mock_pid_file.read_text.return_value = "12345"

        mock_run.return_value = Mock(returncode=0, stdout="python3")

        status = DashboardService.get_server_status()

        assert status["status"] == "running"
        assert status["pid"] == 12345
        assert "endpoint" in status

    @patch('modules.web_dashboard.dashboard.UNIFIED_PID_FILE')
    def test_get_server_status_stopped(self, mock_pid_file):
        """Test getting server status when stopped"""
        mock_pid_file.exists.return_value = False

        status = DashboardService.get_server_status()

        assert status["status"] == "stopped"

    @patch('modules.web_dashboard.dashboard.QUICK_TUNNEL_PID_FILE')
    @patch('subprocess.run')
    def test_get_tunnel_status_running(self, mock_run, mock_pid_file):
        """Test getting tunnel status when running"""
        mock_pid_file.exists.return_value = True
        mock_pid_file.read_text.return_value = "54321"

        mock_run.return_value = Mock(returncode=0)

        # Mock log file
        with patch('modules.web_dashboard.dashboard.LOG_DIR') as mock_log_dir:
            mock_log_file = Mock()
            mock_log_file.exists.return_value = True
            mock_log_file.read_text.return_value = "Tunnel URL: https://test-tunnel.trycloudflare.com"
            mock_log_dir.__truediv__ = Mock(return_value=mock_log_file)

            status = DashboardService.get_tunnel_status()

        assert status["status"] == "running"
        assert status["pid"] == 54321

    @patch('modules.web_dashboard.dashboard.ENV_FILE')
    def test_get_env_variables(self, mock_env_file):
        """Test reading environment variables"""
        mock_env_file.exists.return_value = True
        mock_env_file.read_text.return_value = """
# Comment
DATABASE_PATH=./data/test.db
LOG_LEVEL=DEBUG
ENABLE_OAUTH_AUTH=true
"""

        env_vars = DashboardService.get_env_variables()

        assert env_vars["DATABASE_PATH"] == "./data/test.db"
        assert env_vars["LOG_LEVEL"] == "DEBUG"
        assert env_vars["ENABLE_OAUTH_AUTH"] == "true"

    @patch('modules.web_dashboard.dashboard.ENV_FILE')
    def test_update_env_variable_existing(self, mock_env_file):
        """Test updating existing environment variable"""
        mock_env_file.exists.return_value = True
        mock_env_file.read_text.return_value = "LOG_LEVEL=INFO\nDATABASE_PATH=./db"
        mock_env_file.write_text = Mock()

        result = DashboardService.update_env_variable("LOG_LEVEL", "DEBUG")

        assert result is True
        mock_env_file.write_text.assert_called_once()
        written_content = mock_env_file.write_text.call_args[0][0]
        assert "LOG_LEVEL=DEBUG" in written_content

    @patch('modules.web_dashboard.dashboard.ENV_FILE')
    def test_update_env_variable_new(self, mock_env_file):
        """Test adding new environment variable"""
        mock_env_file.exists.return_value = True
        mock_env_file.read_text.return_value = "LOG_LEVEL=INFO"
        mock_env_file.write_text = Mock()

        result = DashboardService.update_env_variable("NEW_VAR", "new_value")

        assert result is True
        mock_env_file.write_text.assert_called_once()
        written_content = mock_env_file.write_text.call_args[0][0]
        assert "NEW_VAR=new_value" in written_content

    @patch('modules.web_dashboard.dashboard.LOG_DIR')
    def test_get_log_files(self, mock_log_dir):
        """Test getting list of log files"""
        mock_log_file1 = Mock()
        mock_log_file1.name = "app.log"
        mock_log_file1.stat.return_value.st_size = 1024 * 1024  # 1MB

        mock_log_file2 = Mock()
        mock_log_file2.name = "unified_server.log"
        mock_log_file2.stat.return_value.st_size = 2048 * 1024  # 2MB

        mock_log_dir.exists.return_value = True
        mock_log_dir.glob.return_value = [mock_log_file1, mock_log_file2]

        log_files = DashboardService.get_log_files()

        assert len(log_files) == 2
        assert log_files[0]["name"] == "app.log"
        assert log_files[0]["size_mb"] == 1.0
        assert log_files[1]["name"] == "unified_server.log"
        assert log_files[1]["size_mb"] == 2.0

    @patch('subprocess.run')
    @patch('modules.web_dashboard.dashboard.LOG_DIR')
    def test_get_log_content(self, mock_log_dir, mock_run):
        """Test reading log file content"""
        mock_log_file = Mock()
        mock_log_file.exists.return_value = True
        mock_log_dir.__truediv__ = Mock(return_value=mock_log_file)

        mock_run.return_value = Mock(
            stdout="Line 1\nLine 2\nLine 3"
        )

        content = DashboardService.get_log_content("app.log", lines=100)

        assert "Line 1" in content
        assert "Line 2" in content
        assert "Line 3" in content

    def test_get_endpoints_info_local(self):
        """Test getting endpoints info without tunnel"""
        info = DashboardService.get_endpoints_info()

        assert info["base_url"] == "http://localhost:8000"
        assert len(info["services"]) == 5
        assert "oauth" in info
        assert info["oauth"]["authorize"] == "http://localhost:8000/oauth/authorize"

    def test_get_endpoints_info_with_tunnel(self):
        """Test getting endpoints info with tunnel URL"""
        tunnel_url = "https://test-tunnel.trycloudflare.com"
        info = DashboardService.get_endpoints_info(tunnel_url)

        assert info["base_url"] == tunnel_url
        assert info["services"][0]["url"] == f"{tunnel_url}/mail-query/"
        assert info["oauth"]["authorize"] == f"{tunnel_url}/oauth/authorize"


@pytest.mark.asyncio
class TestDashboardAPI:
    """Test dashboard API endpoints"""

    async def test_dashboard_page_loads(self):
        """Test that dashboard HTML page loads"""
        from modules.web_dashboard.dashboard import create_dashboard_routes
        routes = create_dashboard_routes()

        # Find dashboard route
        dashboard_route = None
        for route in routes:
            if hasattr(route, 'path') and route.path == "/dashboard":
                dashboard_route = route
                break

        assert dashboard_route is not None
        assert dashboard_route.methods == ["GET"]

    async def test_api_endpoints_exist(self):
        """Test that all API endpoints are created"""
        from modules.web_dashboard.dashboard import create_dashboard_routes
        routes = create_dashboard_routes()

        expected_paths = [
            "/dashboard",
            "/dashboard/api/status",
            "/dashboard/api/endpoints",
            "/dashboard/api/env",
            "/dashboard/api/logs",
        ]

        route_paths = []
        for route in routes:
            if hasattr(route, 'path'):
                route_paths.append(route.path)

        for expected_path in expected_paths:
            assert any(expected_path in path for path in route_paths), \
                f"Expected path {expected_path} not found in routes"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
