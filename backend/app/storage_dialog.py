"""Local host launcher UI; no remotely accessible administration endpoint."""
from datetime import datetime
from pathlib import Path
from tkinter import Toplevel, StringVar, filedialog, messagebox, simpledialog, ttk

from .config import get_settings
from .quotation_storage import check_storage, save_storage


def show_storage_dialog(launcher):
    if not launcher.is_heart_host or launcher.stopping:
        return
    previous = getattr(launcher, "storage_window", None)
    if previous is not None and previous.winfo_exists():
        previous.lift()
        return
    settings = get_settings()
    window = Toplevel(launcher.root)
    launcher.storage_window = window
    window.title("견적서 저장소 설정 · 서버장")
    window.geometry("760x680")
    window.minsize(720, 640)
    window.transient(launcher.root)
    window.grab_set()
    frame = ttk.Frame(window, padding=20)
    frame.pack(fill="both", expand=True)
    root_value = StringVar(value=str(settings.quotation_files_path))
    status = StringVar(value="기본 폴더 안에서 연도별 폴더를 선택하세요. 파일은 자동 이동하지 않습니다.")
    ttk.Label(frame, text="NAS 또는 견적서 기본 폴더").pack(anchor="w")
    row = ttk.Frame(frame)
    row.pack(fill="x", pady=(5, 12))
    root_entry = ttk.Entry(row, textvariable=root_value)
    root_entry.pack(side="left", fill="x", expand=True)

    def browse_root():
        folder = filedialog.askdirectory(parent=window, title="견적서 기본 폴더 선택", mustexist=True)
        if folder:
            root_value.set(folder)

    browse_button = ttk.Button(row, text="폴더 찾아보기", command=browse_root)
    browse_button.pack(side="right", padx=(6, 0))
    ttk.Label(frame, text=r"예: \\192.168.0.29\backup-1\1. 견적서").pack(anchor="w")
    table = ttk.Treeview(frame, columns=("year", "folder"), show="headings", height=8, selectmode="browse")
    table.heading("year", text="연도")
    table.heading("folder", text="기본 폴더 안의 위치")
    table.column("year", width=80, stretch=False)
    table.column("folder", width=530)
    table.pack(fill="both", expand=True, pady=12)
    for year, folder in sorted(settings.quotation_year_folders.items()):
        table.insert("", "end", iid=year, values=(year, folder))

    def choose_year(edit=False):
        selection = table.selection()
        if edit and not selection:
            messagebox.showinfo("폴더 선택", "변경할 연도를 선택해주세요.", parent=window)
            return
        year = selection[0] if edit else simpledialog.askinteger(
            "연도 추가", "연도를 입력해주세요.", initialvalue=datetime.now().year,
            minvalue=1900, maxvalue=2199, parent=window)
        if year is None:
            return
        year = str(year)
        if not edit and table.exists(year):
            messagebox.showwarning("연도 중복", "이미 등록된 연도입니다. 폴더 변경을 사용해주세요.", parent=window)
            return
        folder = filedialog.askdirectory(parent=window, title=f"{year}년 폴더 선택 (새 폴더 만들기도 가능)",
                                         initialdir=root_value.get(), mustexist=True)
        if not folder:
            return
        try:
            relative = Path(folder).resolve().relative_to(Path(root_value.get()).resolve())
            if relative == Path("."):
                raise ValueError()
        except ValueError:
            messagebox.showerror("폴더 위치 확인", "기본 폴더 안의 하위 폴더를 선택해주세요.", parent=window)
            return
        if edit:
            table.item(year, values=(year, str(relative)))
        else:
            table.insert("", "end", iid=year, values=(year, str(relative)))

    def remove_year():
        selected = table.selection()
        if selected and messagebox.askyesno("연도 연결 해제", "선택한 연도의 연결만 해제합니다. 실제 폴더와 파일은 삭제하지 않습니다.", parent=window):
            table.delete(selected[0])

    actions = ttk.Frame(frame)
    actions.pack(fill="x")
    add_button = ttk.Button(actions, text="＋ 연도 추가", command=choose_year)
    edit_button = ttk.Button(actions, text="폴더 변경", command=lambda: choose_year(True))
    remove_button = ttk.Button(actions, text="연결 해제", command=remove_year)
    for button in (add_button, edit_button, remove_button):
        button.pack(side="left", padx=(0, 6))
    ttk.Label(frame, textvariable=status, wraplength=700).pack(fill="x", pady=14)
    from .history_progress import HistoryProgress
    HistoryProgress(frame, width=690).pack(fill="x", pady=(0, 14))
    bottom = ttk.Frame(frame)
    bottom.pack(fill="x")
    busy = False

    def close():
        if not busy:
            window.destroy()

    def run_check(apply=False):
        nonlocal busy
        if busy:
            return
        if not launcher.is_heart_host or launcher.stopping:
            messagebox.showerror("서버 상태", "서버가 실행 중일 때만 적용할 수 있습니다.", parent=window)
            return
        root = root_value.get()
        years = {item: str(table.item(item, "values")[1]) for item in table.get_children()}
        if not years and not messagebox.askyesno("연도 구분 없음", "연도별 폴더 없이 기본 폴더에 저장합니다. 계속할까요?", parent=window):
            return
        if apply and not messagebox.askyesno("저장소 적용", "모든 사용자의 견적서 저장 위치에 적용합니다.\n기존 자료는 새 위치로 자동 이동하지 않습니다.\n필요한 파일을 복사했는지 확인 후 적용해주세요.", parent=window):
            return
        busy = True
        for widget in controls:
            widget.configure(state="disabled")
        status.set("서버 PC에서 폴더 연결과 읽기·쓰기 권한을 확인하고 있습니다…")

        def finished(_result, error):
            nonlocal busy
            busy = False
            if not window.winfo_exists():
                return
            for widget in controls:
                widget.configure(state="normal")
            if error:
                status.set(f"확인 실패: {error}" + ("\n서버 PC의 탐색기에서 NAS 폴더를 열어 로그인과 권한을 확인해주세요." if isinstance(error, OSError) else ""))
            else:
                if apply:
                    from .services.history_refresh import start_history_refresh
                    from .main import server_stopping
                    start_history_refresh(settings, server_stopping)
                status.set("저장하고 적용했습니다. 과거 견적 DB 갱신을 시작합니다." if apply else "연결 정상 · 모든 지정 폴더 읽기/쓰기 가능")

        launcher.run_background(lambda: save_storage(settings, root, years) if apply else check_storage(root, years), finished)

    check_button = ttk.Button(bottom, text="연결 확인", command=run_check)
    check_button.pack(side="left")
    def refresh_now():
        from .services.history_refresh import start_history_refresh
        from .main import server_stopping
        start_history_refresh(settings, server_stopping)
        status.set("저장된 폴더로 과거 견적 갱신을 요청했습니다.")
    refresh_button = ttk.Button(bottom, text="과거 견적 갱신", command=refresh_now)
    refresh_button.pack(side="left", padx=8)
    save_button = ttk.Button(bottom, text="저장 후 적용", command=lambda: run_check(True))
    save_button.pack(side="right")
    close_button = ttk.Button(bottom, text="닫기", command=close)
    close_button.pack(side="right", padx=8)
    controls = (root_entry, browse_button, add_button, edit_button, remove_button, check_button, refresh_button, save_button, close_button)
    window.protocol("WM_DELETE_WINDOW", close)
