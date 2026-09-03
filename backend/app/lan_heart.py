from __future__ import annotations

import base64
from contextlib import closing
import json
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .config import runtime_root


HEART_PORT = 54837
DISCOVERY_MESSAGE = b"OPENMOON_HEART_DISCOVER_V1"
API_VERSION = "1"
DISCOVERY_TIMEOUT_SECONDS = 2.2


def get_lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        sock.close()


def normalize_heart_server_url(value: str) -> str:
    address = value.strip()
    for prefix in ("http://", "https://"):
        if address.lower().startswith(prefix):
            address = address[len(prefix):]
            break
    address = address.rstrip("/")
    if not address:
        raise ValueError("서버 IP를 입력하세요.")
    if ":" not in address:
        address += f":{HEART_PORT}"
    return "http://" + address


def _heart_data_dir() -> Path:
    path = runtime_root() / "backend" / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def server_identifier() -> str:
    path = _heart_data_dir() / "heart_server_id.txt"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        value = ""
    if value:
        return value
    value = str(uuid.uuid4())
    try:
        path.write_text(value, encoding="utf-8")
    except OSError:
        pass
    return value


class HeartUpdate(BaseModel):
    mail_key: str = Field(min_length=1, max_length=1000)
    hearted: bool
    user_id: str | None = Field(default=None, max_length=100)
    user_name: str | None = Field(default=None, max_length=50)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


class HeartStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else _heart_data_dir() / "heart_sync.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self.lock, closing(self._connect()) as connection, connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS mail_hearts (
                    mail_key TEXT PRIMARY KEY,
                    hearted INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    user_id TEXT,
                    user_name TEXT,
                    color TEXT
                )
            """)
            existing = {str(row[1]) for row in connection.execute("PRAGMA table_info(mail_hearts)")}
            for name in ("user_id", "user_name", "color"):
                if name not in existing:
                    connection.execute(f"ALTER TABLE mail_hearts ADD COLUMN {name} TEXT")

    def all(self) -> dict[str, dict[str, Any]]:
        with self.lock, closing(self._connect()) as connection, connection:
            rows = connection.execute("SELECT mail_key,hearted,user_id,user_name,color,updated_at FROM mail_hearts WHERE hearted=1").fetchall()
        return {
            str(mail_key): {
                "hearted": bool(hearted),
                "user_id": user_id,
                "user_name": user_name or "기존 사용자",
                "color": color or "#DF7134",
                "updated_at": updated_at,
            }
            for mail_key, hearted, user_id, user_name, color, updated_at in rows
        }

    def set(
        self,
        mail_key: str,
        hearted: bool,
        *,
        user_id: str | None = None,
        user_name: str | None = None,
        color: str | None = None,
    ) -> dict[str, Any]:
        key = mail_key.strip()
        if not key:
            raise ValueError("메일 식별값이 비어 있습니다.")
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.lock, closing(self._connect()) as connection, connection:
            if hearted:
                connection.execute("""
                    INSERT INTO mail_hearts(mail_key,hearted,updated_at,user_id,user_name,color)
                    VALUES(?,1,?,?,?,?)
                    ON CONFLICT(mail_key) DO UPDATE SET
                        hearted=1,updated_at=excluded.updated_at,user_id=excluded.user_id,
                        user_name=excluded.user_name,color=excluded.color
                """, (key, now, user_id, user_name, color))
            else:
                connection.execute("DELETE FROM mail_hearts WHERE mail_key=?", (key,))
        return {
            "hearted": hearted,
            "user_id": user_id if hearted else None,
            "user_name": user_name if hearted else None,
            "color": color if hearted else None,
            "updated_at": now,
        }

def create_heart_app(store: HeartStore | None = None) -> FastAPI:
    heart_store = store or HeartStore()
    app = FastAPI(title="OPENMOON LAN Heart", version=API_VERSION)

    @app.get("/health")
    def health():
        return {
            "ok": True,
            "api_version": API_VERSION,
            "pc_name": socket.gethostname(),
            "ip": get_lan_ip(),
            "port": HEART_PORT,
            "server_id": server_identifier(),
        }

    @app.get("/hearts", response_model=dict[str, dict[str, Any]])
    def hearts():
        return heart_store.all()

    @app.put("/hearts")
    def update_heart(request: HeartUpdate):
        return {"mail_key": request.mail_key, **heart_store.set(request.mail_key, request.hearted, user_id=request.user_id, user_name=request.user_name, color=request.color)}

    return app


class DiscoveryResponder:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", HEART_PORT))
            sock.settimeout(0.5)
            while not self.stop_event.is_set():
                try:
                    data, address = sock.recvfrom(2048)
                except socket.timeout:
                    continue
                if data != DISCOVERY_MESSAGE:
                    continue
                payload = json.dumps({
                    "api_version": API_VERSION,
                    "pc_name": socket.gethostname(),
                    "ip": get_lan_ip(),
                    "port": HEART_PORT,
                    "server_id": server_identifier(),
                }).encode("utf-8")
                sock.sendto(payload, address)
        except OSError:
            return
        finally:
            sock.close()


def discover_heart_servers(timeout: float = DISCOVERY_TIMEOUT_SECONDS) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.25)
    deadline = time.monotonic() + timeout
    targets = [("255.255.255.255", HEART_PORT), ("127.0.0.1", HEART_PORT)]
    try:
        while time.monotonic() < deadline:
            for target in targets:
                try:
                    sock.sendto(DISCOVERY_MESSAGE, target)
                except OSError:
                    pass
            wait_until = min(deadline, time.monotonic() + 0.35)
            while time.monotonic() < wait_until:
                try:
                    data, address = sock.recvfrom(4096)
                    info = json.loads(data.decode("utf-8"))
                    if str(info.get("api_version")) != API_VERSION:
                        continue
                    info["ip"] = info.get("ip") or address[0]
                    info["port"] = int(info.get("port") or HEART_PORT)
                    key = str(info.get("server_id") or f"{info['ip']}:{info['port']}")
                    found[key] = info
                except socket.timeout:
                    break
                except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
    finally:
        sock.close()
    return sorted(found.values(), key=lambda row: (str(row.get("pc_name") or ""), str(row.get("ip") or "")))


class HeartServerConnectionError(RuntimeError):
    pass


_selected_server_lock = threading.Lock()
_selected_server_url: str | None = None


def set_selected_heart_server(url: str | None) -> None:
    global _selected_server_url
    with _selected_server_lock:
        _selected_server_url = normalize_heart_server_url(url) if url else None


def selected_heart_server() -> str | None:
    with _selected_server_lock:
        return _selected_server_url


def _request_json(method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 2.0) -> Any:
    server_url = selected_heart_server()
    if not server_url:
        raise HeartServerConnectionError("공유 서버가 선택되지 않았습니다.")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        server_url + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, ValueError) as error:
        raise HeartServerConnectionError(
            "서버에 연결할 수 없습니다. 서버 PC와 사내 네트워크 연결을 확인해 주세요."
        ) from error


def heart_server_health(url: str, timeout: float = 2.0) -> dict[str, Any]:
    normalized = normalize_heart_server_url(url)
    request = urllib.request.Request(normalized + "/api/health", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError) as error:
        raise HeartServerConnectionError(
            "서버에 연결할 수 없습니다. 서버 PC와 사내 네트워크 연결을 확인해 주세요."
        ) from error
    if value.get("status") != "ok":
        raise HeartServerConnectionError("공유 서버 버전이 현재 프로그램과 맞지 않습니다.")
    return value


def fetch_remote_hearts() -> dict[str, bool]:
    value = _request_json("GET", "/hearts")
    return {str(key): bool(hearted) for key, hearted in dict(value).items()}


def set_remote_heart(mail_key: str, hearted: bool) -> bool:
    value = _request_json("PUT", "/hearts", {"mail_key": mail_key, "hearted": hearted})
    return bool(value.get("hearted"))


def install_private_firewall_rules() -> bool:
    """관리자 권한 PowerShell을 띄워 사설망 LocalSubnet 규칙 두 개만 만든다."""
    if not hasattr(__import__("ctypes"), "windll"):
        return False
    import ctypes

    script = f"""
$ErrorActionPreference = 'Stop'
$rules = @(
  @{{Name='OPENMOON Shared Server TCP {HEART_PORT}'; Protocol='TCP'}},
  @{{Name='OPENMOON Shared Server UDP {HEART_PORT}'; Protocol='UDP'}}
)
foreach ($rule in $rules) {{
  if (-not (Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue)) {{
    New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound -Action Allow -Profile Private -RemoteAddress LocalSubnet -Protocol $rule.Protocol -LocalPort {HEART_PORT} | Out-Null
  }}
}}
""".strip()
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    parameters = f"-NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}"
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", parameters, None, 0)
    return int(result) > 32


def private_firewall_rules_ready() -> bool:
    """Return True when enabled TCP and UDP rules for the shared port exist."""
    if sys.platform != "win32":
        return False

    def rule_exists(name: str) -> bool:
        try:
            result = subprocess.run(
                ["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=4,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0 and name.casefold() in result.stdout.casefold()

    current = (
        rule_exists(f"OPENMOON Shared Server TCP {HEART_PORT}")
        and rule_exists(f"OPENMOON Shared Server UDP {HEART_PORT}")
    )
    if current:
        return True
    return (
        rule_exists(f"OPENMOON Heart TCP {HEART_PORT}")
        and rule_exists(f"OPENMOON Heart UDP {HEART_PORT}")
    )
