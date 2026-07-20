"""60分実験の参加案内メールを選択式UIで生成する。"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import generate_experiment_mail_60 as mail


class ExperimentMail60UI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("60分実験 参加案内メール生成")
        root.geometry("1040x700")
        root.minsize(860, 600)

        self.participant_id = tk.StringVar(value="XX")
        self.short_video_minutes = tk.StringVar(value="5")
        self.trailer_number = tk.StringVar(value="1")
        self.status = tk.StringVar(
            value="参加者ID、動画視聴時間、映画予告映像を選択してください。"
        )

        self._configure_style()
        self._build_layout()
        self.generate()

    def _configure_style(self) -> None:
        style = ttk.Style()
        if "aqua" in style.theme_names():
            style.theme_use("aqua")
        style.configure("Title.TLabel", font=("Helvetica", 20, "bold"))
        style.configure("Section.TLabel", font=("Helvetica", 12, "bold"))
        style.configure("Hint.TLabel", foreground="#666666")

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, padding=20)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(1, weight=1)

        ttk.Label(
            outer,
            text="60分実験 参加案内メール生成",
            style="Title.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 18))

        controls = ttk.Frame(outer, padding=(0, 0, 24, 0))
        controls.grid(row=1, column=0, sticky="nsew")
        controls.columnconfigure(0, weight=1)

        ttk.Label(controls, text="実験参加者ID", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        participant_entry = ttk.Entry(
            controls,
            textvariable=self.participant_id,
            width=28,
        )
        participant_entry.grid(row=1, column=0, sticky="ew", pady=(6, 22))

        ttk.Label(controls, text="動画視聴時間", style="Section.TLabel").grid(
            row=2, column=0, sticky="w"
        )
        time_frame = ttk.Frame(controls)
        time_frame.grid(row=3, column=0, sticky="w", pady=(6, 22))
        self._add_number_buttons(
            time_frame,
            self.short_video_minutes,
            list(mail.SHORT_VIDEO_OPTIONS),
            suffix="分",
        )

        ttk.Label(
            controls,
            text="2分間の映画予告映像",
            style="Section.TLabel",
        ).grid(row=4, column=0, sticky="w")
        trailer_frame = ttk.Frame(controls)
        trailer_frame.grid(row=5, column=0, sticky="w", pady=(6, 4))
        self._add_number_buttons(
            trailer_frame,
            self.trailer_number,
            list(mail.TRAILER_URLS),
        )
        ttk.Label(
            controls,
            text="予告編番号 1〜8",
            style="Hint.TLabel",
        ).grid(row=6, column=0, sticky="w", pady=(0, 22))

        ttk.Button(controls, text="本文を生成", command=self.generate).grid(
            row=7, column=0, sticky="ew", pady=(0, 8)
        )
        ttk.Button(
            controls,
            text="クリップボードへコピー",
            command=self.copy,
        ).grid(row=8, column=0, sticky="ew", pady=4)
        ttk.Button(
            controls,
            text="テキストファイルに保存",
            command=self.save,
        ).grid(row=9, column=0, sticky="ew", pady=4)

        preview_frame = ttk.Frame(outer)
        preview_frame.grid(row=1, column=1, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(1, weight=1)
        ttk.Label(
            preview_frame,
            text="生成された本文",
            style="Section.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.preview = tk.Text(
            preview_frame,
            wrap="word",
            font=("Menlo", 11),
            padx=14,
            pady=14,
            undo=True,
        )
        scrollbar = ttk.Scrollbar(
            preview_frame,
            orient="vertical",
            command=self.preview.yview,
        )
        self.preview.configure(yscrollcommand=scrollbar.set)
        self.preview.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")

        ttk.Label(outer, textvariable=self.status, style="Hint.TLabel").grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(12, 0),
        )

    def _add_number_buttons(
        self,
        parent: ttk.Frame,
        variable: tk.StringVar,
        numbers: list[int],
        suffix: str = "",
    ) -> None:
        """クリック・ホバー・選択状態が分かる選択ボタンを配置する。"""
        buttons: dict[int, tk.Button] = {}

        def refresh_colors() -> None:
            selected = variable.get()
            for number, button in buttons.items():
                is_selected = str(number) == selected
                button.configure(
                    background="#1f4e79" if is_selected else "#f1f5f9",
                    foreground="#ffffff" if is_selected else "#172033",
                    relief="sunken" if is_selected else "flat",
                )

        def select(number: int) -> None:
            variable.set(str(number))
            refresh_colors()
            self.generate()

        def on_enter(number: int) -> None:
            if variable.get() != str(number):
                buttons[number].configure(
                    background="#bfdbfe",
                    foreground="#172033",
                )

        for index, number in enumerate(numbers):
            button = tk.Button(
                parent,
                text=f"{number}{suffix}",
                width=4 if suffix else 2,
                padx=4,
                pady=5,
                relief="flat",
                borderwidth=1,
                cursor="hand2",
                command=lambda value=number: select(value),
            )
            button.grid(row=0, column=index, padx=2, pady=2)
            buttons[number] = button
            button.bind("<Enter>", lambda _event, value=number: on_enter(value))
            button.bind("<Leave>", lambda _event: refresh_colors())

        refresh_colors()

    def generate(self) -> None:
        try:
            text = mail.generate_mail(
                participant_id=self.participant_id.get(),
                short_video_minutes=int(self.short_video_minutes.get()),
                trailer_number=int(self.trailer_number.get()),
            )
        except ValueError as error:
            messagebox.showerror("設定エラー", str(error))
            return

        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.status.set(
            "本文を生成しました。認知負荷アンケート・記述タスクはURLで案内されます。"
        )

    def copy(self) -> None:
        text = self.preview.get("1.0", "end-1c")
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status.set("本文をクリップボードへコピーしました。")

    def save(self) -> None:
        text = self.preview.get("1.0", "end-1c")
        if not text:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("テキストファイル", "*.txt"), ("すべてのファイル", "*.*")],
            initialfile=f"experiment_mail_60_{self.participant_id.get() or 'XX'}.txt",
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as file:
            file.write(text)
        self.status.set(f"保存しました：{path}")


def main() -> None:
    root = tk.Tk()
    ExperimentMail60UI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
