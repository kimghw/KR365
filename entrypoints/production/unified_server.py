#!/usr/bin/env python3
"""
Unified Production Server

각 모듈의 FastAPI 서버를 서브프로세스로 실행하고
리버스 프록시로 라우팅하는 통합 서버입니다.
"""

import sys
import os
import asyncio
import subprocess
import signal
import time
import socket
from pathlib import Path
from typing import Dict, Optional

# 프로젝트 루트 경로 추가
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn
import httpx
from contextlib import asynccontextmanager

# 서버 설정
SERVERS = {
    "onenote": {
        "port": 8002,
        "script": PROJECT_ROOT / "modules" / "onenote_mcp" / "entrypoints" / "run_fastapi.py",
        "env": {"ONENOTE_SERVER_PORT": "8002"}
    },
    "outlook": {
        "port": 8001,
        "script": PROJECT_ROOT / "modules" / "outlook_mcp" / "entrypoints" / "run_fastapi.py",
        "env": {"MAIL_API_PORT": "8001"}
    },
    "teams": {
        "port": 8003,
        "script": PROJECT_ROOT / "modules" / "teams_mcp" / "entrypoints" / "run_fastapi.py",
        "env": {"TEAMS_API_PORT": "8003"}
    },
    "dashboard": {
        "port": 8004,
        "script": PROJECT_ROOT / "modules" / "web_dashboard" / "standalone_server.py",
        "env": {"DASHBOARD_PORT": "8004"}
    }
}

# 실행중인 프로세스 저장
running_processes: Dict[str, subprocess.Popen] = {}
existing_services: Dict[str, bool] = {}  # 기존에 실행중인 서비스

def is_port_open(port: int) -> bool:
    """포트가 사용 중인지 확인"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('localhost', port))
    sock.close()
    return result == 0

@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 생명주기 관리"""
    # 시작: 서비스 상태 확인 및 필요시 실행
    print("🔍 Checking existing services...")

    for service_name, config in SERVERS.items():
        port = config["port"]

        # 포트가 이미 사용중인지 확인
        if is_port_open(port):
            print(f"✅ {service_name} is already running on port {port} (using existing)")
            existing_services[service_name] = True
        else:
            # 서비스 시작
            print(f"🚀 Starting {service_name} on port {port}...")
            try:
                env = os.environ.copy()
                env.update(config["env"])

                process = subprocess.Popen(
                    [sys.executable, str(config["script"])],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    preexec_fn=os.setsid if os.name != 'nt' else None
                )

                running_processes[service_name] = process
                existing_services[service_name] = False
                print(f"✅ Started {service_name} (PID: {process.pid})")

            except Exception as e:
                print(f"❌ Failed to start {service_name}: {e}")
                existing_services[service_name] = False

    # 새로 시작한 서버들이 준비될 때까지 대기
    if running_processes:
        print("⏳ Waiting for new services to be ready...")
        await asyncio.sleep(3)

    yield

    # 종료: 새로 시작한 프로세스만 종료
    print("\n🛑 Stopping services...")
    for service_name, process in running_processes.items():
        if not existing_services.get(service_name, False):
            try:
                if os.name != 'nt':
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                else:
                    process.terminate()
                process.wait(timeout=5)
                print(f"✅ Stopped {service_name} (was started by unified server)")
            except Exception as e:
                print(f"⚠️ Error stopping {service_name}: {e}")
                try:
                    process.kill()
                except:
                    pass
        else:
            print(f"ℹ️ {service_name} was already running, keeping it alive")

# 메인 앱 생성
app = FastAPI(
    title="KR365 Unified API Server",
    description="통합 API 서버 - OneNote, Outlook, Teams, Dashboard",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# HTTP 클라이언트
client = httpx.AsyncClient(timeout=30.0)

# 루트 엔드포인트
@app.get("/")
async def root():
    return {
        "message": "KR365 Unified API Server",
        "services": {
            "onenote": "/onenote",
            "outlook": "/outlook",
            "teams": "/teams",
            "dashboard": "/dashboard"
        },
        "docs": "/docs",
        "health": "/health"
    }

@app.get("/health")
async def health():
    """헬스체크 - 각 서비스 상태 확인"""
    status = {}
    for service_name, config in SERVERS.items():
        try:
            response = await client.get(f"http://localhost:{config['port']}/health", timeout=2.0)
            status[service_name] = "healthy" if response.status_code == 200 else "unhealthy"
        except:
            status[service_name] = "down"

    all_healthy = all(s == "healthy" for s in status.values())
    return {
        "status": "healthy" if all_healthy else "degraded",
        "services": status
    }

# 프록시 함수
async def proxy_request(service_name: str, path: str, request: Request):
    """요청을 해당 서비스로 프록시"""
    if service_name not in SERVERS:
        return JSONResponse(
            status_code=404,
            content={"error": f"Service '{service_name}' not found"}
        )

    config = SERVERS[service_name]
    target_url = f"http://localhost:{config['port']}/{path}"

    # 헤더 복사 (Host 헤더는 제외)
    headers = dict(request.headers)
    headers.pop("host", None)

    try:
        # 요청 프록시
        if request.method == "GET":
            response = await client.get(target_url, headers=headers, params=request.query_params)
        elif request.method == "POST":
            body = await request.body()
            response = await client.post(target_url, headers=headers, content=body)
        elif request.method == "PUT":
            body = await request.body()
            response = await client.put(target_url, headers=headers, content=body)
        elif request.method == "DELETE":
            response = await client.delete(target_url, headers=headers)
        elif request.method == "PATCH":
            body = await request.body()
            response = await client.patch(target_url, headers=headers, content=body)
        elif request.method == "HEAD":
            response = await client.head(target_url, headers=headers)
        elif request.method == "OPTIONS":
            response = await client.options(target_url, headers=headers)
        else:
            return JSONResponse(
                status_code=405,
                content={"error": f"Method {request.method} not allowed"}
            )

        # 응답 헤더 수정 (리다이렉트 처리)
        response_headers = dict(response.headers)

        # Location 헤더가 있고 상대 경로인 경우 서비스 프리픽스 추가
        if "location" in response_headers:
            location = response_headers["location"]
            if location.startswith("/") and not location.startswith(f"/{service_name}"):
                # 대시보드의 경우 특별 처리
                if service_name == "dashboard" and location.startswith("/dashboard"):
                    # 이미 /dashboard가 있으면 그대로 사용
                    pass
                else:
                    # 서비스 프리픽스 추가
                    response_headers["location"] = f"/{service_name}{location}"

        # 응답 반환
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=response_headers
        )

    except httpx.ConnectError:
        return JSONResponse(
            status_code=503,
            content={"error": f"Service '{service_name}' is not available"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Proxy error: {str(e)}"}
        )

# 각 서비스로 라우팅
@app.api_route("/onenote/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_onenote(path: str, request: Request):
    return await proxy_request("onenote", path, request)

@app.api_route("/onenote", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_onenote_root(request: Request):
    return await proxy_request("onenote", "", request)

@app.api_route("/outlook/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_outlook(path: str, request: Request):
    return await proxy_request("outlook", path, request)

@app.api_route("/outlook", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_outlook_root(request: Request):
    return await proxy_request("outlook", "", request)

@app.api_route("/teams/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_teams(path: str, request: Request):
    return await proxy_request("teams", path, request)

@app.api_route("/teams", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_teams_root(request: Request):
    return await proxy_request("teams", "", request)

@app.api_route("/dashboard/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_dashboard(path: str, request: Request):
    # 대시보드는 특별히 처리 - /dashboard 경로가 포함되어야 함
    return await proxy_request("dashboard", f"dashboard/{path}", request)

@app.api_route("/dashboard", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_dashboard_root(request: Request):
    return await proxy_request("dashboard", "dashboard", request)


def cleanup():
    """정리 함수 - 새로 시작한 서비스만 종료"""
    print("\n🧹 Cleaning up...")
    for service_name, process in running_processes.items():
        if not existing_services.get(service_name, False):
            try:
                process.terminate()
                print(f"  - Terminated {service_name} (was started by unified server)")
            except:
                pass
        else:
            print(f"  - Keeping {service_name} (was already running)")


if __name__ == "__main__":
    port = int(os.getenv("UNIFIED_PORT", "8080"))
    host = os.getenv("UNIFIED_HOST", "0.0.0.0")

    # 통합 서버 포트가 이미 사용중인지 확인
    if is_port_open(port):
        print(f"❌ Port {port} is already in use!")
        print(f"   Please stop the existing service or use a different port:")
        print(f"   UNIFIED_PORT=8090 python {__file__}")
        sys.exit(1)

    # Ctrl+C 핸들러 등록
    signal.signal(signal.SIGINT, lambda s, f: cleanup())

    print(f"🚀 Starting KR365 Unified Server on {host}:{port}")
    print(f"📝 API Docs: http://localhost:{port}/docs")
    print(f"🔗 Services will be available at:")
    print(f"   - OneNote: http://localhost:{port}/onenote")
    print(f"   - Outlook: http://localhost:{port}/outlook")
    print(f"   - Teams: http://localhost:{port}/teams")
    print(f"   - Dashboard: http://localhost:{port}/dashboard")
    print()

    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    except KeyboardInterrupt:
        cleanup()
    finally:
        asyncio.run(client.aclose())