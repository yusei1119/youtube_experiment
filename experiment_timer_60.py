"""最大5名を同時に計測する60分実験用タイマー。

起動方法:
    python3 experiment_timer_60.py

ショート動画の視聴時間は5〜30分（5分刻み）から選択し、
5名全員に同じ時間を適用します。
"""

from __future__ import annotations

import math
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk


MAX_PARTICIPANTS = 5
SHORT_VIDEO_OPTIONS = (5, 10, 15, 20, 25, 30)

EXPLANATION_SECONDS = 5 * 60
SURVEY_SECONDS = 2 * 60
TRAILER_SECONDS = 2 * 60 + 30
WRITING_SECONDS = 8 * 60
FINAL_SURVEY_SECONDS = 10 * 60


@dataclass(frozen=True)
class Step:
    name: str
    seconds: int
    category: str


def build_schedule(short_video_minutes: int) -> list[Step]:
    """選択した視聴時間から60分実験の全手順を作る。"""
    if short_video_minutes not in SHORT_VIDEO_OPTIONS:
        raise ValueError("ショート動画時間は5〜30分の5分刻みで指定してください。")
    return [
        Step("実験の説明", EXPLANATION_SECONDS, "common"),
        Step("ショート動画視聴", short_video_minutes * 60, "short"),
        Step("ショート動画後のアンケート", SURVEY_SECONDS, "short"),
        Step("映画予告映像", TRAILER_SECONDS, "short"),
        Step("記述タスク", WRITING_SECONDS, "short"),
        Step("実験後のアンケート", FINAL_SURVEY_SECONDS, "common"),
    ]


def format_duration(seconds: float) -> str:
    whole_seconds = max(0, math.ceil(seconds))
    minutes, remainder = divmod(whole_seconds, 60)
    return f"{minutes:02d}:{remainder:02d}"


class TimerState:
    """1名分の独立したカウントダウン状態。"""

    def __init__(self, short_video_minutes: int) -> None:
        self.short_video_minutes = short_video_minutes
        self.schedule = build_schedule(short_video_minutes)
        self.step_index = 0
        self.remaining = float(self.schedule[0].seconds)
        self.running = False
        self.last_tick: float | None = None
        self.alert_pending = False

    @property
    def finished(self) -> bool:
        return self.step_index >= len(self.schedule)

    @property
    def current_step(self) -> Step | None:
        return None if self.finished else self.schedule[self.step_index]

    @property
    def has_progress(self) -> bool:
        if self.finished or self.step_index > 0:
            return True
        return self.remaining < self.schedule[0].seconds

    def start(self, now: float | None = None) -> None:
        if self.finished or self.running:
            return
        self.running = True
        self.last_tick = time.monotonic() if now is None else now

    def pause(self, now: float | None = None) -> None:
        if not self.running:
            return
        self.tick(time.monotonic() if now is None else now)
        self.running = False
        self.last_tick = None

    def tick(self, now: float | None = None) -> None:
        if not self.running or self.last_tick is None or self.finished:
            return
        current_time = time.monotonic() if now is None else now
        delta = max(0.0, current_time - self.last_tick)
        was_positive = self.remaining > 0
        self.remaining -= delta
        self.last_tick = current_time
        if was_positive and self.remaining <= 0:
            self.alert_pending = True

    def go_next(self) -> None:
        if self.finished:
            return
        was_running = self.running
        self.running = False
        self.last_tick = None
        self.alert_pending = False
        self.step_index += 1
        if self.finished:
            self.remaining = 0.0
            return
        self.remaining = float(self.schedule[self.step_index].seconds)
        if was_running:
            self.start()

    def go_previous(self) -> None:
        if self.step_index <= 0:
            return
        was_running = self.running
        self.running = False
        self.last_tick = None
        self.alert_pending = False
        self.step_index -= 1
        self.remaining = float(self.schedule[self.step_index].seconds)
        if was_running:
            self.start()

    def reset(self, short_video_minutes: int | None = None) -> None:
        if short_video_minutes is not None:
            self.short_video_minutes = short_video_minutes
        self.schedule = build_schedule(self.short_video_minutes)
        self.step_index = 0
        self.remaining = float(self.schedule[0].seconds)
        self.running = False
        self.last_tick = None
        self.alert_pending = False


class ParticipantTimer:
    CATEGORY_COLORS = {
        "short": "#fce7df",
        "common": "#e8e8ee",
    }

    def __init__(
        self,
        parent: ttk.Frame,
        participant_number: int,
        on_alert,
        short_video_minutes: int,
    ) -> None:
        self.participant_number = participant_number
        self.on_alert = on_alert
        self.state = TimerState(short_video_minutes)

        self.participant_id = tk.StringVar(value=f"P{participant_number:02d}")
        self.condition_text = tk.StringVar()
        self.step_text = tk.StringVar()
        self.timer_text = tk.StringVar()
        self.detail_text = tk.StringVar()
        self.next_text = tk.StringVar()
        self.start_button_text = tk.StringVar(value="開始")
        self.progress_value = tk.DoubleVar(value=0)
        self.video_time_text = tk.StringVar(value=f"ショート動画 {short_video_minutes}分")

        self._last_running: bool | None = None
        self._last_step_index: int | None = None
        self._last_timer_display: str | None = None
        self._last_overtime: bool | None = None

        self.frame = ttk.Frame(parent, style="Card.TFrame", padding=(12, 8))
        self.frame.columnconfigure(2, weight=1)
        self._build_widgets()
        self.refresh(force=True)

    def _build_widgets(self) -> None:
        identity = ttk.Frame(self.frame, style="Card.TFrame")
        identity.grid(row=0, column=0, sticky="nw", padx=(0, 18))
        ttk.Label(
            identity,
            text=f"参加者 {self.participant_number}",
            style="CardTitle.TLabel",
        ).pack(anchor="w")
        ttk.Entry(identity, textvariable=self.participant_id, width=14).pack(
            anchor="w", pady=(3, 5)
        )
        ttk.Label(identity, text="全員共通条件", style="Small.TLabel").pack(anchor="w")
        ttk.Label(
            identity,
            textvariable=self.video_time_text,
            style="Small.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        clock = ttk.Frame(self.frame, style="Card.TFrame", width=210)
        clock.grid(row=0, column=1, sticky="n", padx=(0, 22))
        self.condition_label = tk.Label(
            clock,
            textvariable=self.condition_text,
            font=("Helvetica", 11, "bold"),
            padx=10,
            pady=3,
            borderwidth=0,
        )
        self.condition_label.pack()
        self.timer_label = ttk.Label(
            clock, textvariable=self.timer_text, style="Timer.TLabel"
        )
        self.timer_label.pack(pady=(2, 0))
        ttk.Label(clock, textvariable=self.detail_text, style="Small.TLabel").pack()

        details = ttk.Frame(self.frame, style="Card.TFrame")
        details.grid(row=0, column=2, sticky="nsew", padx=(0, 18))
        ttk.Label(details, textvariable=self.step_text, style="Step.TLabel").pack(
            anchor="w", pady=(2, 4)
        )
        ttk.Progressbar(
            details,
            variable=self.progress_value,
            maximum=100,
            mode="determinate",
        ).pack(fill="x", pady=(0, 5))
        ttk.Label(details, textvariable=self.next_text, style="Small.TLabel").pack(
            anchor="w"
        )

        buttons = ttk.Frame(self.frame, style="Card.TFrame")
        buttons.grid(row=0, column=3, sticky="ne")
        ttk.Button(
            buttons,
            textvariable=self.start_button_text,
            command=self.toggle_start_pause,
            width=9,
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        ttk.Button(buttons, text="← 前へ", command=self.previous, width=9).grid(
            row=1, column=0, padx=(0, 3), pady=3
        )
        ttk.Button(buttons, text="次へ →", command=self.next, width=9).grid(
            row=1, column=1, padx=(3, 0), pady=3
        )
        ttk.Button(buttons, text="リセット", command=self.reset).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(5, 0)
        )

    def toggle_start_pause(self) -> None:
        if self.state.running:
            self.state.pause()
        else:
            self.state.start()
        self.refresh()

    def start(self) -> None:
        self.state.start()
        self.refresh()

    def pause(self) -> None:
        self.state.pause()
        self.refresh()

    def next(self) -> None:
        self.state.go_next()
        self.refresh()

    def previous(self) -> None:
        self.state.go_previous()
        self.refresh()

    def reset(self, ask: bool = True) -> None:
        if ask and self.state.has_progress:
            if not messagebox.askyesno(
                "タイマーをリセット",
                f"{self.participant_id.get()} のタイマーを最初に戻しますか？",
            ):
                return
        self.state.reset()
        self.refresh(force=True)

    def set_short_video_minutes(self, minutes: int) -> None:
        self.state.reset(minutes)
        self.video_time_text.set(f"ショート動画 {minutes}分")
        self.refresh(force=True)

    def tick(self, now: float) -> None:
        if not self.state.running:
            return
        self.state.tick(now)
        if self.state.alert_pending:
            self.state.alert_pending = False
            self.on_alert(self)
        self.refresh()

    def refresh(self, force: bool = False) -> None:
        state = self.state
        if force or self._last_running != state.running:
            self.start_button_text.set("一時停止" if state.running else "開始")
            self._last_running = state.running

        if state.finished:
            if force or self._last_step_index != state.step_index:
                self.condition_text.set("完了")
                self.condition_label.configure(
                    background="#d9ead3", foreground="#245522"
                )
                self.timer_text.set("00:00")
                self.timer_label.configure(style="Timer.TLabel")
                self.step_text.set("すべての手順が完了しました")
                self.detail_text.set(f"全{len(state.schedule)}手順")
                self.next_text.set("次の手順：なし")
                self.progress_value.set(100)
                self._last_step_index = state.step_index
                self._last_timer_display = "00:00"
                self._last_overtime = False
            return

        step = state.current_step
        assert step is not None
        step_changed = force or self._last_step_index != state.step_index
        if step_changed:
            condition_name = "共通手順" if step.category == "common" else "ショート動画条件"
            self.condition_text.set(condition_name)
            self.condition_label.configure(
                background=self.CATEGORY_COLORS[step.category], foreground="#20302a"
            )
            self.step_text.set(step.name)
            self.detail_text.set(
                f"予定 {format_duration(step.seconds)}  ／  "
                f"手順 {state.step_index + 1}/{len(state.schedule)}"
            )
            if state.step_index + 1 < len(state.schedule):
                next_step = state.schedule[state.step_index + 1]
                self.next_text.set(
                    f"次：{next_step.name}（{format_duration(next_step.seconds)}）"
                )
            else:
                self.next_text.set("次：実験完了")
            self._last_step_index = state.step_index

        overtime = state.remaining < 0
        timer_display = (
            format_duration(state.remaining)
            if not overtime
            else f"+{format_duration(-state.remaining)}"
        )
        if force or self._last_timer_display != timer_display:
            self.timer_text.set(timer_display)
            self._last_timer_display = timer_display
        if force or self._last_overtime != overtime:
            self.timer_label.configure(
                style="Overtime.TLabel" if overtime else "Timer.TLabel"
            )
            if overtime:
                self.next_text.set("⚠ 予定時間終了。「次へ」を押してください")
            self._last_overtime = overtime

        elapsed_ratio = (step.seconds - max(0, state.remaining)) / step.seconds
        self.progress_value.set(min(100, max(0, elapsed_ratio * 100)))


class ExperimentTimer60App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("60分実験タイマー（最大5名）")
        root.geometry("1380x900")
        root.minsize(1120, 780)
        root.configure(background="#edf1f5")

        self._configure_styles()
        self.short_video_minutes = 10
        self.short_time_var = tk.StringVar(value=f"{self.short_video_minutes}分")
        self.total_time_var = tk.StringVar()
        self.participant_timers: list[ParticipantTimer] = []
        self._build_layout()
        self._update_total_time()
        self._update_loop()

    def _configure_styles(self) -> None:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("App.TFrame", background="#edf1f5")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure(
            "Title.TLabel",
            background="#edf1f5",
            foreground="#15231c",
            font=("Helvetica", 24, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background="#edf1f5",
            foreground="#5f6b65",
            font=("Helvetica", 11),
        )
        style.configure(
            "CardTitle.TLabel",
            background="#ffffff",
            foreground="#15231c",
            font=("Helvetica", 13, "bold"),
        )
        style.configure(
            "Timer.TLabel",
            background="#ffffff",
            foreground="#16211b",
            font=("Menlo", 31, "bold"),
        )
        style.configure(
            "Overtime.TLabel",
            background="#ffffff",
            foreground="#c9382b",
            font=("Menlo", 31, "bold"),
        )
        style.configure(
            "Step.TLabel",
            background="#ffffff",
            foreground="#15231c",
            font=("Helvetica", 15, "bold"),
        )
        style.configure(
            "Small.TLabel",
            background="#ffffff",
            foreground="#66716b",
            font=("Helvetica", 10),
        )

    def _build_layout(self) -> None:
        page = ttk.Frame(self.root, style="App.TFrame", padding=20)
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)

        header = ttk.Frame(page, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="60分実験タイマー", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            textvariable=self.total_time_var,
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        toolbar = ttk.Frame(header, style="App.TFrame")
        toolbar.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Label(
            toolbar,
            text="全員共通 ショート動画時間",
            style="Subtitle.TLabel",
        ).pack(side="left", padx=(0, 5))
        self.short_time_box = ttk.Combobox(
            toolbar,
            textvariable=self.short_time_var,
            values=[f"{minutes}分" for minutes in SHORT_VIDEO_OPTIONS],
            state="readonly",
            width=7,
        )
        self.short_time_box.pack(side="left", padx=(0, 12))
        self.short_time_box.bind("<<ComboboxSelected>>", self.change_short_time)

        ttk.Button(toolbar, text="全員開始", command=self.start_all).pack(
            side="left", padx=3
        )
        ttk.Button(toolbar, text="全員一時停止", command=self.pause_all).pack(
            side="left", padx=3
        )
        ttk.Button(toolbar, text="全員前へ", command=self.previous_all).pack(
            side="left", padx=3
        )
        ttk.Button(toolbar, text="全員次へ", command=self.next_all).pack(
            side="left", padx=3
        )
        ttk.Button(toolbar, text="全員リセット", command=self.reset_all).pack(
            side="left", padx=3
        )
        ttk.Button(toolbar, text="手順と時間", command=self.show_schedule).pack(
            side="left", padx=(12, 3)
        )

        ttk.Separator(page, orient="horizontal").grid(
            row=1, column=0, sticky="ew", pady=(0, 12)
        )

        cards = ttk.Frame(page, style="App.TFrame")
        cards.grid(row=2, column=0, sticky="nsew")
        cards.columnconfigure(0, weight=1)
        for index in range(MAX_PARTICIPANTS):
            cards.rowconfigure(index, weight=1, uniform="participant")
            timer = ParticipantTimer(
                cards,
                index + 1,
                self.alert,
                self.short_video_minutes,
            )
            timer.frame.grid(
                row=index,
                column=0,
                sticky="nsew",
                pady=(0, 6 if index < MAX_PARTICIPANTS - 1 else 0),
            )
            self.participant_timers.append(timer)

    def _update_loop(self) -> None:
        now = time.monotonic()
        for timer in self.participant_timers:
            timer.tick(now)
        self.root.after(250, self._update_loop)

    def _update_total_time(self) -> None:
        total_seconds = sum(
            step.seconds for step in build_schedule(self.short_video_minutes)
        )
        self.total_time_var.set(
            f"最大5名を独立計測  ／  ショート動画 {self.short_video_minutes}分  ／  "
            f"予定時間 {format_duration(total_seconds)}"
        )

    def change_short_time(self, _event=None) -> None:
        selected_minutes = int(self.short_time_var.get().removesuffix("分"))
        if selected_minutes == self.short_video_minutes:
            return
        has_progress = any(timer.state.has_progress for timer in self.participant_timers)
        if has_progress and not messagebox.askyesno(
            "ショート動画時間を変更",
            "全員の進行をリセットして、視聴時間を一括変更しますか？",
        ):
            self.short_time_var.set(f"{self.short_video_minutes}分")
            return
        self.short_video_minutes = selected_minutes
        for timer in self.participant_timers:
            timer.set_short_video_minutes(selected_minutes)
        self._update_total_time()

    def alert(self, _timer: ParticipantTimer) -> None:
        self.root.bell()
        self.root.after(180, self.root.bell)

    def start_all(self) -> None:
        for timer in self.participant_timers:
            timer.start()

    def pause_all(self) -> None:
        for timer in self.participant_timers:
            timer.pause()

    def previous_all(self) -> None:
        for timer in self.participant_timers:
            timer.previous()

    def next_all(self) -> None:
        for timer in self.participant_timers:
            timer.next()

    def reset_all(self) -> None:
        if not messagebox.askyesno(
            "全員リセット", "5名すべてのタイマーを最初に戻しますか？"
        ):
            return
        for timer in self.participant_timers:
            timer.reset(ask=False)

    def show_schedule(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("60分実験の手順と時間")
        window.geometry("520x420")
        window.transient(self.root)

        frame = ttk.Frame(window, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="60分実験の手順と時間", style="CardTitle.TLabel").pack(
            anchor="w", pady=(0, 12)
        )
        tree = ttk.Treeview(
            frame,
            columns=("number", "step", "time"),
            show="headings",
            height=8,
        )
        tree.heading("number", text="#")
        tree.heading("step", text="手順")
        tree.heading("time", text="時間")
        tree.column("number", width=40, anchor="center")
        tree.column("step", width=290, anchor="w")
        tree.column("time", width=90, anchor="center")
        tree.pack(fill="both", expand=True)
        schedule = build_schedule(self.short_video_minutes)
        for index, step in enumerate(schedule, start=1):
            tree.insert(
                "",
                "end",
                values=(index, step.name, format_duration(step.seconds)),
            )
        total_seconds = sum(step.seconds for step in schedule)
        ttk.Label(
            frame,
            text=f"合計予定時間：{format_duration(total_seconds)}",
        ).pack(anchor="e", pady=(10, 0))


def main() -> None:
    root = tk.Tk()
    ExperimentTimer60App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
