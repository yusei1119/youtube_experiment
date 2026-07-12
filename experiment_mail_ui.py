"""実験メール本文を番号選択で生成するデスクトップUI。"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import generate_experiment_mail as mail


CONDITION_KEYS = list(mail.CONDITION_NAMES)
DISPLAY_TO_KEY = {name: key for key, name in mail.CONDITION_NAMES.items()}


class ExperimentMailUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("実験参加案内メール生成")
        root.geometry("980x720")
        root.minsize(820, 620)

        self.participant_id = tk.StringVar(value=mail.PARTICIPANT_ID)
        self.order_vars = [
            tk.StringVar(value=mail.CONDITION_NAMES[key])
            for key in mail.CONDITION_ORDER
        ]
        self.trailer_vars = {
            key: tk.StringVar(value=str(mail.TRAILER_SELECTION[key]))
            for key in CONDITION_KEYS
        }
        self.daily_video = tk.StringVar(value=str(mail.DAILY_VIDEO_SELECTION))
        self.comprehension_test = tk.StringVar(
            value=str(mail.COMPREHENSION_TEST_SELECTION)
        )
        self.status = tk.StringVar(value="設定を選び、「本文を生成」を押してください。")

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

        ttk.Label(outer, text="参加案内メール生成", style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 18)
        )

        controls = ttk.Frame(outer, padding=(0, 0, 22, 0))
        controls.grid(row=1, column=0, sticky="nsew")

        ttk.Label(controls, text="参加者ID", style="Section.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        ttk.Entry(controls, textvariable=self.participant_id, width=28).grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=(6, 20)
        )

        ttk.Label(controls, text="条件の順序", style="Section.TLabel").grid(
            row=2, column=0, columnspan=3, sticky="w"
        )
        condition_names = list(DISPLAY_TO_KEY)
        for index, variable in enumerate(self.order_vars, start=1):
            ttk.Label(controls, text=f"実験{index}").grid(
                row=2 + index, column=0, sticky="w", pady=4
            )
            ttk.Combobox(
                controls,
                textvariable=variable,
                values=condition_names,
                state="readonly",
                width=18,
            ).grid(row=2 + index, column=1, columnspan=2, sticky="ew", pady=4)

        next_row = 7
        ttk.Label(controls, text="映画予告映像番号", style="Section.TLabel").grid(
            row=next_row, column=0, columnspan=3, sticky="w", pady=(18, 4)
        )
        trailer_numbers = [str(number) for number in mail.TRAILER_URLS]
        for offset, key in enumerate(CONDITION_KEYS, start=1):
            ttk.Label(controls, text=mail.CONDITION_NAMES[key]).grid(
                row=next_row + offset, column=0, sticky="w", pady=4
            )
            ttk.Combobox(
                controls,
                textvariable=self.trailer_vars[key],
                values=trailer_numbers,
                state="readonly",
                width=8,
            ).grid(row=next_row + offset, column=1, sticky="w", pady=4)

        next_row += 5
        ttk.Label(controls, text="日常動画条件", style="Section.TLabel").grid(
            row=next_row, column=0, columnspan=3, sticky="w", pady=(18, 4)
        )
        daily_numbers = [str(number) for number in mail.DAILY_VIDEO_URLS]
        test_numbers = [str(number) for number in mail.COMPREHENSION_TEST_URLS]
        ttk.Label(controls, text="日常動画").grid(row=next_row + 1, column=0, sticky="w")
        ttk.Combobox(
            controls,
            textvariable=self.daily_video,
            values=daily_numbers,
            state="readonly",
            width=8,
        ).grid(row=next_row + 1, column=1, sticky="w", pady=4)
        ttk.Label(controls, text="理解度テスト").grid(
            row=next_row + 2, column=0, sticky="w"
        )
        ttk.Combobox(
            controls,
            textvariable=self.comprehension_test,
            values=test_numbers,
            state="readonly",
            width=8,
        ).grid(row=next_row + 2, column=1, sticky="w", pady=4)

        ttk.Button(controls, text="本文を生成", command=self.generate).grid(
            row=next_row + 3, column=0, columnspan=3, sticky="ew", pady=(24, 8)
        )
        ttk.Button(controls, text="クリップボードへコピー", command=self.copy).grid(
            row=next_row + 4, column=0, columnspan=3, sticky="ew", pady=4
        )
        ttk.Button(controls, text="テキストファイルに保存", command=self.save).grid(
            row=next_row + 5, column=0, columnspan=3, sticky="ew", pady=4
        )

        preview_frame = ttk.Frame(outer)
        preview_frame.grid(row=1, column=1, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(1, weight=1)
        ttk.Label(preview_frame, text="生成された本文", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        self.preview = tk.Text(
            preview_frame,
            wrap="word",
            font=("Menlo", 11),
            padx=14,
            pady=14,
            undo=True,
        )
        scrollbar = ttk.Scrollbar(
            preview_frame, orient="vertical", command=self.preview.yview
        )
        self.preview.configure(yscrollcommand=scrollbar.set)
        self.preview.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")

        ttk.Label(outer, textvariable=self.status, style="Hint.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

    def _apply_settings(self) -> None:
        selected_names = [variable.get() for variable in self.order_vars]
        if len(set(selected_names)) != len(CONDITION_KEYS):
            raise ValueError("条件の順序には3条件を1回ずつ指定してください。")

        mail.PARTICIPANT_ID = self.participant_id.get()
        mail.CONDITION_ORDER = [DISPLAY_TO_KEY[name] for name in selected_names]
        mail.TRAILER_SELECTION = {
            key: int(variable.get()) for key, variable in self.trailer_vars.items()
        }
        mail.DAILY_VIDEO_SELECTION = int(self.daily_video.get())
        mail.COMPREHENSION_TEST_SELECTION = int(self.comprehension_test.get())

    def generate(self) -> None:
        try:
            self._apply_settings()
            text = mail.generate_mail()
        except (KeyError, ValueError) as error:
            messagebox.showerror("設定エラー", str(error))
            return

        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.status.set("本文を生成しました。実験後アンケートは常に最後に配置されます。")

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
            initialfile=f"experiment_mail_{self.participant_id.get() or 'XX'}.txt",
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as file:
            file.write(text)
        self.status.set(f"保存しました：{path}")


def main() -> None:
    root = tk.Tk()
    ExperimentMailUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
