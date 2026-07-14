"""最大5人を同時に計測できる実験進行タイマー。

起動方法:
    python3 experiment_timer.py

時間が0になっても自動では次の手順へ進まず、超過時間を表示します。
実験者が内容の完了を確認してから「次へ」を押してください。
"""

from __future__ import annotations

import itertools
import math
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk


MAX_PARTICIPANTS = 5

CONDITION_NAMES = {
    "short": "ショート動画",
    "meditation": "瞑想",
    "daily": "日常動画",
}

# 添付の実験手順に基づく時間設定（秒）
EXPLANATION_SECONDS = 5 * 60
BETWEEN_CONDITIONS_BREAK_SECONDS = 3 * 60
FINAL_SURVEY_SECONDS = 10 * 60

CONDITION_STEPS = {
    "short": (
        ("ショート動画視聴", 10 * 60),
        ("アンケート", 2 * 60),
        ("映画予告映像", 2 * 60 + 30),
        ("記述タスク", 8 * 60),
    ),
    "meditation": (
        ("瞑想動画視聴", 6 * 60 + 30),
        ("瞑想後の休息", 3 * 60 + 30),
        ("アンケート", 2 * 60),
        ("映画予告映像", 2 * 60 + 30),
        ("記述タスク", 8 * 60),
    ),
    "daily": (
        ("日常動画視聴", 9 * 60),
        ("理解度テスト", 1 * 60),
        ("アンケート", 2 * 60),
        ("映画予告映像", 2 * 60 + 30),
        ("記述タスク", 8 * 60),
    ),
}


@dataclass(frozen=True)
class Step:
    name: str
    seconds: int
    condition: str


def build_schedule(order: tuple[str, str, str]) -> list[Step]:
    """条件順から、説明・休憩・最終アンケートを含む全手順を作る。"""
    if len(order) != 3 or set(order) != set(CONDITION_NAMES):
        raise ValueError("条件順には3条件を1回ずつ指定してください。")

    schedule = [Step("実験の説明", EXPLANATION_SECONDS, "common")]
    for condition_index, condition in enumerate(order):
        schedule.extend(
            Step(name, seconds, condition)
            for name, seconds in CONDITION_STEPS[condition]
        )
        if condition_index < len(order) - 1:
            next_condition = CONDITION_NAMES[order[condition_index + 1]]
            schedule.append(
                Step(
                    f"条件間休憩（次：{next_condition}条件）",
                    BETWEEN_CONDITIONS_BREAK_SECONDS,
                    "break",
                )
            )
    schedule.append(Step("実験後のアンケート", FINAL_SURVEY_SECONDS, "common"))
    return schedule


def format_duration(seconds: float) -> str:
    """秒数をMM:SSで表示する。"""
    whole_seconds = max(0, math.ceil(seconds))
    minutes, remainder = divmod(whole_seconds, 60)
    return f"{minutes:02d}:{remainder:02d}"


class TimerState:
    """画面から独立した、1人分のタイマー状態。"""

    def __init__(self, order: tuple[str, str, str]) -> None:
        self.order = order
        self.schedule = build_schedule(order)
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
        was_running = self.running
        self.running = False
        self.last_tick = None
        self.alert_pending = False
        self.step_index += 1
        if not self.finished:
            self.remaining = float(self.schedule[self.step_index].seconds)
            if was_running:
                self.start()
        else:
            self.remaining = 0.0

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

    def reset(self, order: tuple[str, str, str] | None = None) -> None:
        if order is not None:
            self.order = order
        self.schedule = build_schedule(self.order)
        self.step_index = 0
        self.remaining = float(self.schedule[0].seconds)
        self.running = False
        self.last_tick = None
        self.alert_pending = False


ORDER_OPTIONS = list(itertools.permutations(CONDITION_NAMES))


def order_label(order: tuple[str, str, str]) -> str:
    return " → ".join(CONDITION_NAMES[key] for key in order)


ORDER_BY_LABEL = {order_label(order): order for order in ORDER_OPTIONS}


class ParticipantTimer:
    CONDITION_COLORS = {
        "short": "#fce7df",
        "meditation": "#e4f1df",
        "daily": "#e1edf3",
        "break": "#fff1c9",
        "common": "#e8e8ee",
    }

    def __init__(
        self,
        parent: ttk.Frame,
        participant_number: int,
        on_alert,
        initial_order: tuple[str, str, str],
    ) -> None:
        self.participant_number = participant_number
        self.on_alert = on_alert
        self.state = TimerState(initial_order)

        self.participant_id = tk.StringVar(value=f"P{participant_number:02d}")
        self.order_text = tk.StringVar(value=order_label(initial_order))
        self.condition_text = tk.StringVar()
        self.step_text = tk.StringVar()
        self.timer_text = tk.StringVar()
        self.detail_text = tk.StringVar()
        self.next_text = tk.StringVar()
        self.start_button_text = tk.StringVar(value="開始")
        self.progress_value = tk.DoubleVar(value=0)
        self._last_running: bool | None = None
        self._last_step_index: int | None = None
        self._last_timer_display: str | None = None
        self._last_overtime: bool | None = None

        self.frame = ttk.Frame(parent, style="Card.TFrame", padding=(12, 8))
        self.frame.columnconfigure(2, weight=1)
        self._build_widgets()
        self.refresh()

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
        ttk.Label(identity, text="共通の条件順", style="Small.TLabel").pack(anchor="w")
        ttk.Label(
            identity,
            textvariable=self.order_text,
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
        if self.state.finished:
            return
        self.state.go_next()
        self.refresh()

    def previous(self) -> None:
        self.state.go_previous()
        self.refresh()

    def reset(self, ask: bool = True) -> None:
        if ask and self.state.has_progress:
            confirmed = messagebox.askyesno(
                "タイマーをリセット",
                f"{self.participant_id.get()} のタイマーを最初に戻しますか？",
            )
            if not confirmed:
                return
        self.state.reset()
        self.refresh(force=True)

    def set_order(self, order: tuple[str, str, str]) -> None:
        """共通条件順を適用し、タイマーを最初に戻す。"""
        self.state.reset(order)
        self.order_text.set(order_label(order))
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
            if step.condition == "common":
                condition_name = "共通手順"
            elif step.condition == "break":
                condition_name = "休憩"
            else:
                condition_name = f"{CONDITION_NAMES[step.condition]}条件"
            self.condition_text.set(condition_name)
            self.condition_label.configure(
                background=self.CONDITION_COLORS[step.condition], foreground="#20302a"
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
        if state.remaining >= 0:
            timer_display = format_duration(state.remaining)
        else:
            timer_display = f"+{format_duration(-state.remaining)}"
        if force or self._last_timer_display != timer_display:
            self.timer_text.set(timer_display)
            self._last_timer_display = timer_display
        if force or self._last_overtime != overtime:
            self.timer_label.configure(
                style="Overtime.TLabel" if overtime else "Timer.TLabel"
            )
            if overtime:
                self.next_text.set("⚠ 予定時間終了。「次へ」を押してください")
            elif not step_changed and state.step_index + 1 < len(state.schedule):
                next_step = state.schedule[state.step_index + 1]
                self.next_text.set(
                    f"次：{next_step.name}（{format_duration(next_step.seconds)}）"
                )
            self._last_overtime = overtime

        elapsed_ratio = (step.seconds - max(0, state.remaining)) / step.seconds
        self.progress_value.set(min(100, max(0, elapsed_ratio * 100)))


class ExperimentTimerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("実験進行タイマー（最大5人）")
        root.geometry("1380x900")
        root.minsize(1120, 780)
        root.configure(background="#edf1f5")

        self._configure_styles()
        self.shared_order = ORDER_OPTIONS[0]
        self.order_var = tk.StringVar(value=order_label(self.shared_order))
        self.participant_timers: list[ParticipantTimer] = []
        self._build_layout()
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
        ttk.Label(header, text="実験進行タイマー", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        total_seconds = sum(step.seconds for step in build_schedule(ORDER_OPTIONS[0]))
        ttk.Label(
            header,
            text=(
                f"最大5人を独立計測  ／  予定時間 {format_duration(total_seconds)}  ／  "
                "時間終了後は超過表示"
            ),
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        toolbar = ttk.Frame(header, style="App.TFrame")
        toolbar.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Label(
            toolbar,
            text="全員共通の条件順",
            style="Subtitle.TLabel",
        ).pack(side="left", padx=(0, 5))
        self.order_box = ttk.Combobox(
            toolbar,
            textvariable=self.order_var,
            values=list(ORDER_BY_LABEL),
            state="readonly",
            width=29,
        )
        self.order_box.pack(side="left", padx=(0, 12))
        self.order_box.bind("<<ComboboxSelected>>", self.change_shared_order)
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

        separator = ttk.Separator(page, orient="horizontal")
        separator.grid(row=1, column=0, sticky="ew", pady=(0, 12))

        cards = ttk.Frame(page, style="App.TFrame")
        cards.grid(row=2, column=0, sticky="nsew")
        cards.columnconfigure(0, weight=1)

        for index in range(MAX_PARTICIPANTS):
            cards.rowconfigure(index, weight=1, uniform="participant")
            timer = ParticipantTimer(
                cards,
                index + 1,
                self.alert,
                self.shared_order,
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
        # 4回/秒で十分滑らかに見え、Tkのクリック処理を圧迫しにくい。
        self.root.after(250, self._update_loop)

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
        """5人全員を1つ前の手順へ戻す。"""
        for timer in self.participant_timers:
            timer.previous()

    def next_all(self) -> None:
        """5人全員を次の手順へ進める。"""
        for timer in self.participant_timers:
            timer.next()

    def change_shared_order(self, _event=None) -> None:
        """選択した条件順を5人全員へ一括適用する。"""
        selected_order = ORDER_BY_LABEL[self.order_var.get()]
        if selected_order == self.shared_order:
            return

        has_progress = any(timer.state.has_progress for timer in self.participant_timers)
        if has_progress and not messagebox.askyesno(
            "共通の条件順を変更",
            "全員の進行をリセットして、条件順を一括変更しますか？",
        ):
            self.order_var.set(order_label(self.shared_order))
            return

        self.shared_order = selected_order
        for timer in self.participant_timers:
            timer.set_order(selected_order)

    def reset_all(self) -> None:
        if not messagebox.askyesno(
            "全員リセット", "5人すべてのタイマーを最初に戻しますか？"
        ):
            return
        for timer in self.participant_timers:
            timer.reset(ask=False)

    def show_schedule(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("実験手順と時間")
        window.geometry("560x670")
        window.transient(self.root)

        frame = ttk.Frame(window, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="実験手順と時間", style="CardTitle.TLabel").pack(
            anchor="w", pady=(0, 12)
        )

        tree = ttk.Treeview(
            frame,
            columns=("condition", "step", "time"),
            show="headings",
            height=23,
        )
        tree.heading("condition", text="区分")
        tree.heading("step", text="手順")
        tree.heading("time", text="時間")
        tree.column("condition", width=100, anchor="w")
        tree.column("step", width=270, anchor="w")
        tree.column("time", width=80, anchor="center")
        tree.pack(fill="both", expand=True)

        rows = [("共通", "実験の説明", EXPLANATION_SECONDS)]
        for condition in ("short", "meditation", "daily"):
            rows.extend(
                (CONDITION_NAMES[condition], name, seconds)
                for name, seconds in CONDITION_STEPS[condition]
            )
        rows.extend(
            [
                ("条件間", "休憩（各条件の間）", BETWEEN_CONDITIONS_BREAK_SECONDS),
                ("共通", "実験後のアンケート", FINAL_SURVEY_SECONDS),
            ]
        )
        for condition, name, seconds in rows:
            tree.insert("", "end", values=(condition, name, format_duration(seconds)))

        ttk.Label(
            frame,
            text="※ 条件間休憩は3条件の間に2回入ります。",
        ).pack(anchor="w", pady=(10, 0))


def main() -> None:
    root = tk.Tk()
    ExperimentTimerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
