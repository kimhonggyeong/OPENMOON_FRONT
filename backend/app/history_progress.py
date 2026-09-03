"""Shared progress display for the host launcher and storage settings."""
from tkinter import ttk


def progress_text(state):
    total = state.get("total", 0)
    done = state.get("completed", 0)
    if state.get("phase") == "scanning" and state.get("status") == "running":
        headline = f"전체 파일 목록 확인 중 · 현재 {state.get('discovered', 0):,}개 발견"
    elif total:
        headline = f"파일 확인 {done:,} / {total:,}개 ({state.get('percent') or 0:g}%)"
    else:
        headline = "과거 견적 갱신 대기"
    if state.get("status") == "failed":
        headline += " · 갱신 실패 (기존 DB 유지)"
    elif state.get("status") == "complete":
        headline += " · DB 반영 완료"
    counts = (
        f"새로 분석 {state.get('parsed', 0):,}개 · 경로만 변경 {state.get('relocated', 0):,}개 · "
        f"내용 유지 {state.get('unchanged', 0) + state.get('metadata_updated', 0):,}개"
    )
    return headline, counts


class HistoryProgress(ttk.Frame):
    def __init__(self, parent, width=520):
        super().__init__(parent)
        self.headline = ttk.Label(self, wraplength=width)
        self.headline.pack(fill="x")
        self.bar = ttk.Progressbar(self, maximum=100, mode="determinate")
        self.bar.pack(fill="x", pady=5)
        self.counts = ttk.Label(self, wraplength=width)
        self.counts.pack(fill="x")
        self.detail = ttk.Label(self, wraplength=width)
        self.detail.pack(fill="x", pady=(4, 0))
        self.animating = False
        self.timer = None
        self.bind("<Destroy>", self._destroyed)
        self.poll()

    def _destroyed(self, event):
        if event.widget is self and self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None

    def poll(self):
        from .services.history_refresh import refresh_status
        state = refresh_status()
        headline, counts = progress_text(state)
        self.headline.configure(text=headline)
        self.counts.configure(text=counts)
        self.detail.configure(text=state["message"])
        unknown = state["status"] == "running" and not state.get("total")
        if unknown and not self.animating:
            self.bar.configure(mode="indeterminate")
            self.bar.start(15)
            self.animating = True
        elif not unknown:
            if self.animating:
                self.bar.stop()
                self.animating = False
            self.bar.configure(mode="determinate", value=state.get("percent") or 0)
        self.timer = self.after(500, self.poll)
