from __future__ import annotations

import queue
import socket
import sys
import threading
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from pathlib import Path
from tkinter import BOTH, CENTER, END, LEFT, Button, Entry, Frame, Label, StringVar, Tk, messagebox

import uvicorn

from backend.app.lan_heart import (
    HEART_PORT,
    DiscoveryResponder,
    discover_heart_servers,
    get_lan_ip,
    heart_server_health,
    install_private_firewall_rules,
    normalize_heart_server_url,
    private_firewall_rules_ready,
    set_selected_heart_server,
)
from backend.app.guest_proxy import clear_guest_temp, set_guest_upstream, stop_guest_upstream


BG, CARD, TEXT, MUTED, ACCENT = "#f6f3ee", "#ffffff", "#222222", "#6f6a63", "#df7134"
GUEST_PROXY_PORT = 54838


class LauncherWindow:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("열린문디자인 견적 업무 보조")
        self.root.geometry("620x570")
        self.root.minsize(570, 520)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.heart_server: uvicorn.Server | None = None
        self.heart_thread: threading.Thread | None = None
        self.discovery_responder: DiscoveryResponder | None = None
        self.selected_heart_url: str | None = None
        self.selected_server_info: dict | None = None
        self.is_heart_host = False
        self.server_error: BaseException | None = None
        self.guest_proxy_server: uvicorn.Server | None = None
        self.guest_proxy_thread: threading.Thread | None = None
        self.events: queue.Queue = queue.Queue()
        self.stopping = False
        self.closing = False
        self.status = StringVar(value="")
        self.search_generation = 0
        self.user_id = uuid.uuid4().hex
        self.user_name = ""
        self.user_color = "#DF7134"
        self.profile_colors = ("#DF7134", "#E53935", "#D81B60", "#8E24AA", "#3949AB", "#1E88E5", "#00897B", "#43A047", "#F9A825", "#6D4C41")
        self.color_buttons: list[Button] = []

        self.page = Frame(self.root, bg=BG)
        self.page.pack(fill=BOTH, expand=True)
        self.root.after(80, self.drain_events)
        self.show_home()

    def drain_events(self) -> None:
        try:
            while True:
                callback, result, error = self.events.get_nowait()
                callback(result, error)
                if self.closing and self.heart_thread is None and self.guest_proxy_thread is None:
                    return
        except queue.Empty:
            pass
        self.root.after(80, self.drain_events)

    def run_background(self, task, callback) -> None:
        def worker() -> None:
            try:
                self.events.put((callback, task(), None))
            except BaseException as error:
                self.events.put((callback, None, error))

        threading.Thread(target=worker, daemon=True).start()

    def clear(self) -> None:
        for child in self.page.winfo_children():
            child.destroy()

    def heading(self, text: str, size: int = 22) -> Label:
        return Label(self.page, text=text, bg=BG, fg=TEXT, font=("맑은 고딕", size, "bold"))

    def description(self, text: str, color: str = MUTED) -> Label:
        return Label(self.page, text=text, bg=BG, fg=color, font=("맑은 고딕", 10), justify=CENTER, wraplength=530)

    def action_button(self, parent: Frame, text: str, command, primary: bool = False, width: int = 20) -> Button:
        return Button(
            parent, text=text, command=command, bg=ACCENT if primary else CARD,
            fg="white" if primary else TEXT, activebackground="#c85e28" if primary else "#f1ece5",
            activeforeground="white" if primary else TEXT, relief="flat", bd=0,
            font=("맑은 고딕", 11, "bold"), cursor="hand2", width=width, height=2,
        )

    def show_home(self) -> None:
        self.search_generation += 1
        self.clear()
        self.heading("열린문디자인").pack(pady=(86, 8))
        self.heading("사내 공유 업무", 17).pack()
        self.description("공유 서버에 접속하거나 이 PC에서 서버를 열 수 있습니다.").pack(pady=(14, 28))
        self.action_button(self.page, "서버 찾기", self.show_find_menu, True, 27).pack(pady=7)
        self.action_button(self.page, "서버 열기", self.open_shared_server, width=27).pack(pady=7)

    def show_find_menu(self) -> None:
        self.search_generation += 1
        self.clear()
        self.heading("서버 찾기", 21).pack(pady=(78, 12))
        self.description("같은 사내 네트워크의 서버를 자동으로 찾거나 IP로 연결합니다.").pack(pady=(0, 25))
        self.action_button(self.page, "자동 서버 찾기", self.show_search, True, 27).pack(pady=7)
        self.action_button(self.page, "IP 검색", self.show_direct_input, width=27).pack(pady=7)
        self.action_button(self.page, "처음으로", self.show_home, width=27).pack(pady=(22, 7))

    def show_search(self) -> None:
        self.search_generation += 1
        generation = self.search_generation
        self.clear()
        self.heading("열린문디자인").pack(pady=(62, 5))
        self.heading("사내 공유 서버 검색", 17).pack()
        self.description("같은 회사 네트워크에서 실행 중인 서버를 찾고 있습니다.").pack(pady=(13, 25))
        self.search_label = Label(self.page, text="검색 중…", bg=BG, fg=ACCENT, font=("맑은 고딕", 14, "bold"))
        self.search_label.pack(pady=18)
        self.action_button(self.page, "서버 찾기로 돌아가기", self.show_find_menu, width=27).pack(pady=(35, 0))
        self.run_background(
            discover_heart_servers,
            lambda servers, error: self.discovery_finished(generation, servers, error),
        )

    def discovery_finished(self, generation: int, servers, error) -> None:
        if generation != self.search_generation:
            return
        if error:
            self.show_no_servers()
            return
        if len(servers) == 1:
            self.connect_to_server(servers[0])
        elif len(servers) > 1:
            self.show_server_list(servers)
        else:
            self.show_no_servers()

    def show_no_servers(self) -> None:
        self.clear()
        self.heading("실행 중인 서버가 없습니다", 19).pack(pady=(80, 12))
        self.description("서버 PC가 켜져 있는지와 사내 네트워크 연결을 확인해 주세요.").pack(pady=8)
        self.action_button(self.page, "다시 검색", self.show_search, True).pack(pady=(30, 8))
        self.action_button(self.page, "IP 검색", self.show_direct_input, width=27).pack(pady=8)
        self.action_button(self.page, "처음으로", self.show_home, width=27).pack(pady=8)

    def show_server_list(self, servers: list[dict]) -> None:
        self.clear()
        self.heading("접속할 서버 선택", 20).pack(pady=(42, 8))
        self.description(f"서버 {len(servers)}개를 찾았습니다.").pack(pady=(0, 16))
        room_frame = Frame(self.page, bg=BG)
        room_frame.pack()
        for info in servers:
            pc_name = str(info.get("pc_name") or "이름 없는 PC")
            ip = str(info.get("ip") or "IP 미확인")
            self.action_button(
                room_frame,
                f"{pc_name}\n{ip}",
                lambda selected=info: self.connect_to_server(selected),
                width=30,
            ).pack(pady=6)
        self.action_button(self.page, "다시 검색", self.show_search, True).pack(pady=(18, 5))
        self.action_button(self.page, "서버 찾기로 돌아가기", self.show_find_menu, width=27).pack(pady=5)

    def show_direct_input(self) -> None:
        self.clear()
        self.heading("IP 검색", 20).pack(pady=(68, 12))
        self.description("서버 PC의 IP를 입력하세요. 포트는 생략할 수 있습니다.").pack(pady=(0, 14))
        self.ip_entry = Entry(self.page, justify=CENTER, font=("Consolas", 15), bg=CARD, fg=TEXT, relief="solid", bd=1, width=27)
        self.ip_entry.pack(ipady=10, pady=8)
        self.ip_entry.insert(END, "192.168.0.")
        self.action_button(self.page, "연결", self.connect_direct, True).pack(pady=18)
        self.action_button(self.page, "뒤로", self.show_find_menu).pack(pady=6)

    def connect_direct(self) -> None:
        try:
            url = normalize_heart_server_url(self.ip_entry.get())
        except ValueError as error:
            messagebox.showerror("입력 확인", str(error))
            return
        self.connect_to_server({"pc_name": "직접 입력 서버", "ip": url.split("://", 1)[1].split(":", 1)[0], "port": HEART_PORT})

    def connect_to_server(self, info: dict) -> None:
        ip = str(info.get("ip") or "").strip()
        port = int(info.get("port") or HEART_PORT)
        url = normalize_heart_server_url(f"{ip}:{port}")
        self.clear()
        self.heading("서버 연결 중", 20).pack(pady=(100, 15))
        self.description(f"{info.get('pc_name') or ip}\n{ip}").pack(pady=8)
        self.description("연결을 확인하고 있습니다…", ACCENT).pack(pady=18)
        self.run_background(lambda: heart_server_health(url), lambda result, error: self.heart_connection_finished(url, info, result, error))

    def heart_connection_finished(self, url: str, info: dict, result, error) -> None:
        if error:
            messagebox.showerror("접속 실패", str(error))
            self.show_search()
            return
        self.selected_heart_url = url
        self.selected_server_info = {**info, **dict(result or {})}
        set_selected_heart_server(url)
        self.start_guest_proxy()

    def start_guest_proxy(self) -> None:
        assert self.selected_heart_url is not None
        clear_guest_temp()
        set_guest_upstream(self.selected_heart_url, self.user_id)
        from backend.app.guest_proxy import app as guest_proxy_app

        self.guest_proxy_server = uvicorn.Server(
            uvicorn.Config(
                guest_proxy_app,
                host="127.0.0.1",
                port=GUEST_PROXY_PORT,
                reload=False,
                log_config=None,
                access_log=False,
                timeout_graceful_shutdown=5,
            )
        )

        def run() -> None:
            try:
                assert self.guest_proxy_server is not None
                self.guest_proxy_server.run()
            except BaseException as error:
                self.server_error = error

        self.guest_proxy_thread = threading.Thread(target=run, daemon=True)
        self.guest_proxy_thread.start()
        self.wait_attempt = 0
        self.root.after(150, self.wait_for_guest_proxy)

    def wait_for_guest_proxy(self) -> None:
        if self.stopping or self.closing:
            return
        if self.guest_proxy_server and self.guest_proxy_server.started:
            self.show_user_profile()
            return
        if self.guest_proxy_thread and not self.guest_proxy_thread.is_alive():
            messagebox.showerror("게스트 실행 실패", str(self.server_error or f"로컬 포트 {GUEST_PROXY_PORT}를 사용할 수 없습니다."))
            self.stop_servers()
            return
        self.wait_attempt += 1
        if self.wait_attempt >= 50:
            messagebox.showerror("게스트 실행 실패", "게스트 임시 파일 기능을 시작하지 못했습니다.")
            self.stop_servers()
            return
        self.root.after(150, self.wait_for_guest_proxy)

    def open_shared_server(self) -> None:
        self.clear()
        self.heading("서버 준비 중", 20).pack(pady=(105, 14))
        self.description("Windows 인바운드 규칙을 확인하고 있습니다…", ACCENT).pack(pady=12)
        self.run_background(private_firewall_rules_ready, self.firewall_check_finished)

    def firewall_check_finished(self, ready, error) -> None:
        if not error and ready:
            self.start_heart_host()
            return
        if not messagebox.askyesno(
            "인바운드 규칙 필요",
            "공유 서버용 TCP/UDP 54837 인바운드 규칙이 설정되어 있지 않습니다.\n\n지금 설정하시겠습니까? Windows 관리자 권한 확인 창이 표시됩니다.",
        ):
            self.show_home()
            return
        if not install_private_firewall_rules():
            messagebox.showerror("방화벽 설정 실패", "관리자 권한 요청을 시작하지 못했습니다.")
            self.show_home()
            return
        self.show_firewall_wait()

    def show_firewall_wait(self) -> None:
        self.clear()
        self.heading("인바운드 규칙 설정", 20).pack(pady=(100, 14))
        self.description("Windows 관리자 권한 창에서 예를 눌러주세요.\n설정이 확인되면 서버가 자동으로 열립니다.", ACCENT).pack(pady=12)
        buttons = Frame(self.page, bg=BG)
        buttons.pack(pady=(22, 0))
        self.action_button(buttons, "설정 완료 확인", self.wait_for_firewall_rules, True, 17).pack(side=LEFT, padx=6)
        self.action_button(buttons, "취소", self.cancel_firewall_wait, width=12).pack(side=LEFT, padx=6)
        self.firewall_wait_attempt = 0
        self.firewall_wait_active = True
        self.firewall_check_in_progress = False
        self.root.after(700, self.wait_for_firewall_rules)

    def wait_for_firewall_rules(self) -> None:
        if not self.firewall_wait_active or self.firewall_check_in_progress:
            return
        self.firewall_check_in_progress = True
        self.run_background(private_firewall_rules_ready, self.firewall_wait_finished)

    def firewall_wait_finished(self, ready, error) -> None:
        self.firewall_check_in_progress = False
        if not self.firewall_wait_active:
            return
        if not error and ready:
            self.firewall_wait_active = False
            self.start_heart_host()
            return
        self.firewall_wait_attempt += 1
        if self.firewall_wait_attempt >= 30:
            messagebox.showwarning("설정 확인 필요", "인바운드 규칙을 확인하지 못했습니다. 설정을 마친 뒤 서버 열기를 다시 눌러주세요.")
            self.show_home()
            return
        self.root.after(700, self.wait_for_firewall_rules)

    def cancel_firewall_wait(self) -> None:
        self.firewall_wait_active = False
        self.show_home()

    def start_heart_host(self) -> None:
        if self.heart_thread and self.heart_thread.is_alive():
            messagebox.showwarning("중복 실행", "이 PC에서 공유 서버가 이미 실행 중입니다.")
            return
        self.clear()
        self.heading("공유 서버 시작 중", 20).pack(pady=(95, 12))
        self.description(f"{socket.gethostname()}\n{get_lan_ip()}:{HEART_PORT}").pack(pady=8)
        self.description("서버를 준비하고 있습니다…", ACCENT).pack(pady=16)
        self.server_error = None
        from backend.app.main import app as main_app

        self.heart_server = uvicorn.Server(
            uvicorn.Config(main_app, host="0.0.0.0", port=HEART_PORT, reload=False, log_config=None, access_log=False, timeout_graceful_shutdown=5)
        )

        def run() -> None:
            try:
                assert self.heart_server is not None
                self.heart_server.run()
            except BaseException as error:
                self.server_error = error

        self.heart_thread = threading.Thread(target=run, daemon=True)
        self.heart_thread.start()
        self.wait_attempt = 0
        self.root.after(200, self.wait_for_heart_host)

    def wait_for_heart_host(self) -> None:
        if self.stopping or self.closing:
            return
        local_url = f"http://127.0.0.1:{HEART_PORT}"
        if self.heart_server and self.heart_server.started:
            try:
                info = heart_server_health(local_url, timeout=0.5)
            except Exception:
                info = None
            if info:
                self.is_heart_host = True
                self.discovery_responder = DiscoveryResponder()
                self.discovery_responder.start()
                self.selected_heart_url = local_url
                self.selected_server_info = {
                    **info,
                    "pc_name": socket.gethostname(),
                    "ip": get_lan_ip(),
                    "port": HEART_PORT,
                }
                set_selected_heart_server(local_url)
                self.show_user_profile()
                return
        if self.heart_thread and not self.heart_thread.is_alive():
            messagebox.showerror("서버 시작 실패", str(self.server_error or f"포트 {HEART_PORT}가 이미 사용 중입니다."))
            self.heart_server = None
            self.show_home()
            return
        self.wait_attempt += 1
        if self.wait_attempt >= 50:
            messagebox.showerror("서버 시작 실패", f"TCP {HEART_PORT} 포트 사용 여부를 확인하세요.")
            self.stop_servers()
            return
        self.root.after(200, self.wait_for_heart_host)

    def show_user_profile(self) -> None:
        self.clear()
        self.heading("사용자 선택", 20).pack(pady=(48, 10))
        self.description("웹을 열기 전에 사용할 이름과 하트 색상을 선택하세요.").pack(pady=(0, 18))
        self.user_name_entry = Entry(self.page, justify=CENTER, font=("맑은 고딕", 14), bg=CARD, fg=TEXT, relief="solid", bd=1, width=24)
        self.user_name_entry.pack(ipady=8, pady=(5, 18))
        if self.user_name:
            self.user_name_entry.insert(END, self.user_name)
        self.user_name_entry.focus_set()
        self.description("하트 색상", TEXT).pack(pady=(0, 8))
        colors = Frame(self.page, bg=BG)
        colors.pack()
        self.color_buttons = []
        for color in self.profile_colors:
            button = Button(
                colors,
                bg=color,
                activebackground=color,
                width=3,
                height=1,
                relief="solid",
                bd=3 if color == self.user_color else 1,
                cursor="hand2",
                command=lambda selected=color: self.select_profile_color(selected),
            )
            button.pack(side=LEFT, padx=4, pady=7)
            self.color_buttons.append(button)
        self.action_button(self.page, "선택 완료", self.confirm_user_profile, True, 24).pack(pady=(24, 7))
        self.action_button(self.page, "연결 종료", self.stop_servers, width=24).pack(pady=5)
        self.user_name_entry.bind("<Return>", lambda _event: self.confirm_user_profile())

    def select_profile_color(self, color: str) -> None:
        self.user_color = color
        for button, value in zip(self.color_buttons, self.profile_colors):
            button.configure(bd=3 if value == color else 1)

    def confirm_user_profile(self) -> None:
        name = self.user_name_entry.get().strip()
        if not name:
            messagebox.showwarning("이름 입력", "사용자 이름을 입력해 주세요.")
            self.user_name_entry.focus_set()
            return
        self.user_name = name[:30]
        self.show_connected()

    def show_connected(self) -> None:
        self.clear()
        info = self.selected_server_info or {}
        role = "서버장" if self.is_heart_host else "게스트"
        self.heading("업무 프로그램 실행 중", 20).pack(pady=(62, 10))
        self.description(role, ACCENT).pack(pady=3)
        self.description(f"{self.user_name}  ●", self.user_color).pack(pady=3)
        self.description(f"{info.get('pc_name') or '서버 PC'}\n{info.get('ip') or self.selected_heart_url}").pack(pady=(5, 22))
        buttons = Frame(self.page, bg=BG)
        buttons.pack()
        web_url = (
            f"http://127.0.0.1:{GUEST_PROXY_PORT}"
            if not self.is_heart_host
            else (self.selected_heart_url or f"http://127.0.0.1:{HEART_PORT}")
        )
        profile_query = urllib.parse.urlencode({
            "user_id": self.user_id,
            "user": self.user_name,
            "color": self.user_color,
        })
        profiled_url = f"{web_url}?{profile_query}"
        self.action_button(buttons, "웹 열기", lambda: webbrowser.open(profiled_url), True, width=12).pack(side=LEFT, padx=7)
        if self.is_heart_host:
            from backend.app.storage_dialog import show_storage_dialog
            self.action_button(buttons, "저장소 설정", lambda: show_storage_dialog(self), width=12).pack(side=LEFT, padx=7)
        self.action_button(buttons, "공유 서버 종료" if self.is_heart_host else "서버 연결 종료", self.stop_servers, width=14).pack(side=LEFT, padx=7)
        self.description("메일, 분석 결과, 품목 수정 내용과 하트 상태를 함께 사용합니다.").pack(pady=(28, 5))
        if self.is_heart_host:
            from backend.app.history_progress import HistoryProgress
            HistoryProgress(self.page).pack(fill="x", padx=35, pady=5)

    def stop_servers(self) -> None:
        if self.stopping:
            return
        self.stopping = True
        self.clear()
        self.heading("서버 연결 종료 중", 20).pack(pady=(80, 16))
        self.description("접속자와 실시간 연결을 정리하고 있습니다.").pack()

        def shutdown():
            if self.heart_server:
                from backend.app.main import server_stopping
                server_stopping.set()
            if self.guest_proxy_server:
                stop_guest_upstream()
            if self.selected_heart_url:
                request = urllib.request.Request(
                    f"{self.selected_heart_url}/api/lan-presence/{urllib.parse.quote(self.user_id, safe='')}",
                    method="DELETE",
                )
                try:
                    with urllib.request.urlopen(request, timeout=3):
                        pass
                except (OSError, urllib.error.URLError):
                    pass  # An unreachable host expires presence automatically.
            if self.discovery_responder:
                self.discovery_responder.stop()
            for server in (self.heart_server, self.guest_proxy_server):
                if server:
                    server.config.timeout_graceful_shutdown = 5
                    server.should_exit = True
            for thread in (self.heart_thread, self.guest_proxy_thread):
                if thread:
                    thread.join(timeout=8)
                    if thread.is_alive():
                        raise RuntimeError("서버 종료가 아직 완료되지 않았습니다. 잠시 후 다시 시도해 주세요.")
            clear_guest_temp()

        self.run_background(shutdown, self.shutdown_finished)

    def shutdown_finished(self, _result, error) -> None:
        self.stopping = False
        if error:
            messagebox.showerror("연결 종료 확인", str(error))
            self.action_button(self.page, "종료 다시 시도", self.stop_servers).pack(pady=15)
            return
        set_selected_heart_server(None)
        self.heart_server = None
        self.heart_thread = None
        self.discovery_responder = None
        self.guest_proxy_server = None
        self.guest_proxy_thread = None
        self.selected_heart_url = None
        self.selected_server_info = None
        self.is_heart_host = False
        self.user_id = uuid.uuid4().hex
        if self.closing:
            self.root.destroy()
        else:
            self.show_home()

    def close(self) -> None:
        self.closing = True
        self.stop_servers()

    def run(self) -> None:
        self.root.mainloop()


def run_server_only() -> None:
    """Start the bundled LAN server without the GUI for diagnostics."""
    try:
        from backend.app.main import app as main_app

        uvicorn.run(
            main_app,
            host="0.0.0.0",
            port=HEART_PORT,
            reload=False,
            log_config=None,
            access_log=False,
        )
    except BaseException:
        log_path = Path(sys.executable).resolve().parent / "server_start_error.log"
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":
    if "--server-only" in sys.argv:
        run_server_only()
    else:
        LauncherWindow().run()
