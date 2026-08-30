#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rename_files.py

ファイル名を一括変更するデスクトップアプリ（tkinter 製）。

    python rename_files.py
    python rename_files.py "C:\\data"     # 対象フォルダを指定して起動

フォルダの選択・変更方法の指定・変更前後の確認・実行・取り消しを 1 画面で行う。
実際のリネーム処理は rename_core.py が担当する。
"""

import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

import rename_core as core

# 一覧のチェック欄に表示する記号
CHECK_ON = "☑"
CHECK_OFF = "☐"

# タブの並び順
TAB_REPLACE = 0
TAB_SEQUENCE = 1
TAB_AFFIX = 2

# 並び順コンボボックスの表示名
SORT_LABELS = {"名前順": core.SORT_NAME, "更新日時順": core.SORT_MTIME}

# 入力を変えてからプレビューを作り直すまでの待ち時間（ミリ秒）
PREVIEW_DELAY = 200


def enable_dpi_awareness():
    """Windows の高解像度ディスプレイで文字がぼやけないようにする。"""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def apply_font(root):
    """日本語が読みやすいフォントを全体に適用し、一覧の行間を文字が切れない高さにする。"""
    families = set(tkfont.families(root))
    for name in ("Meiryo UI", "Yu Gothic UI", "MS UI Gothic", "Hiragino Sans", "Noto Sans CJK JP"):
        if name in families:
            for key in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
                tkfont.nametofont(key).configure(family=name, size=10)
            break
    # 既定の行高だと日本語の下端が切れるため、フォントの高さに合わせて広げる
    line = tkfont.nametofont("TkDefaultFont").metrics("linespace")
    ttk.Style(root).configure("Treeview", rowheight=line + 8)


def to_int(value, default=0):
    """入力欄の文字列を整数にする。数字でなければ default を返す。"""
    try:
        return int(str(value).strip())
    except ValueError:
        return default


class RenameApp(ttk.Frame):
    """アプリの画面全体。"""

    def __init__(self, master, initial_folder=""):
        super().__init__(master, padding=10)

        self._files = []        # 対象フォルダから集めたファイル
        self._entries = []      # プレビュー中の変更計画
        self._history = []      # 直前の実行結果（元に戻す用）
        self._unchecked = set()  # 利用者が手動でチェックを外したファイル
        self._root_folder = None
        self._preview_job = None
        self._reload_job = None

        self._create_variables(initial_folder)
        self._create_widgets()
        self._bind_variables()

        if initial_folder:
            self._reload_files()
        else:
            self._refresh_preview()

    # ------------------------------------------------------------ 画面の組み立て

    def _create_variables(self, initial_folder):
        """入力欄と連動する変数をまとめて用意する。"""
        self.folder_var = tk.StringVar(value=initial_folder)
        self.pattern_var = tk.StringVar(value="*.*")
        self.recursive_var = tk.BooleanVar(value=False)
        self.sort_var = tk.StringVar(value="名前順")
        self.keep_ext_var = tk.BooleanVar(value=True)
        self.only_changed_var = tk.BooleanVar(value=False)

        # 文字列置換
        self.search_var = tk.StringVar()
        self.replace_var = tk.StringVar()
        self.ignore_case_var = tk.BooleanVar(value=False)

        # 連番
        self.seq_kind_var = tk.StringVar(value="number")
        self.seq_start_var = tk.StringVar(value="1")
        self.seq_step_var = tk.StringVar(value="1")
        self.seq_digits_var = tk.StringVar(value="3")
        self.seq_position_var = tk.StringVar(value="prefix")
        self.seq_sep_var = tk.StringVar(value="_")

        # 追加・削除
        self.prefix_var = tk.StringVar()
        self.suffix_var = tk.StringVar()
        self.trim_head_var = tk.StringVar(value="0")
        self.trim_tail_var = tk.StringVar(value="0")

    def _create_widgets(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)   # プレビュー欄だけが縦に伸びる

        self._create_target_frame()
        self._create_method_frame()
        self._create_preview_frame()
        self._create_action_frame()

    def _create_target_frame(self):
        frame = ttk.LabelFrame(self, text=" 1. 対象を選ぶ ", padding=8)
        frame.grid(row=0, column=0, sticky="ew")
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="フォルダ:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(frame, textvariable=self.folder_var).grid(row=0, column=1, columnspan=4, sticky="ew")
        ttk.Button(frame, text="参照...", command=self._choose_folder, width=8) \
            .grid(row=0, column=5, sticky="e", padx=(6, 0))

        ttk.Label(frame, text="ファイル名の条件:").grid(row=1, column=0, sticky="w", pady=(8, 0), padx=(0, 6))
        ttk.Entry(frame, textvariable=self.pattern_var, width=18) \
            .grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Checkbutton(frame, text="サブフォルダも含める", variable=self.recursive_var) \
            .grid(row=1, column=2, sticky="w", pady=(8, 0), padx=(12, 0))
        ttk.Label(frame, text="並び順:").grid(row=1, column=3, sticky="e", pady=(8, 0), padx=(12, 6))
        ttk.Combobox(frame, textvariable=self.sort_var, values=list(SORT_LABELS),
                     state="readonly", width=10).grid(row=1, column=4, sticky="w", pady=(8, 0))
        ttk.Button(frame, text="再読込", command=self._reload_files, width=8) \
            .grid(row=1, column=5, sticky="e", pady=(8, 0), padx=(6, 0))

    def _create_method_frame(self):
        frame = ttk.LabelFrame(self, text=" 2. 変更方法を指定する ", padding=8)
        frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        frame.columnconfigure(0, weight=1)

        self.notebook = ttk.Notebook(frame)
        self.notebook.grid(row=0, column=0, sticky="ew")
        self.notebook.add(self._build_replace_tab(), text="  文字列を置換  ")
        self.notebook.add(self._build_sequence_tab(), text="  連番を付ける  ")
        self.notebook.add(self._build_affix_tab(), text="  前後に追加・削除  ")
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self._schedule_preview())

        ttk.Checkbutton(frame, text="拡張子は変更しない（拡張子を除いた部分だけを対象にする）",
                        variable=self.keep_ext_var) \
            .grid(row=1, column=0, sticky="w", pady=(8, 0))

    def _build_replace_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        tab.columnconfigure(1, weight=1)

        ttk.Label(tab, text="検索する文字列:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(tab, textvariable=self.search_var).grid(row=0, column=1, sticky="ew")
        ttk.Label(tab, text="置換後の文字列:").grid(row=1, column=0, sticky="w", pady=(6, 0), padx=(0, 6))
        ttk.Entry(tab, textvariable=self.replace_var).grid(row=1, column=1, sticky="ew", pady=(6, 0))
        ttk.Checkbutton(tab, text="大文字と小文字を区別しない", variable=self.ignore_case_var) \
            .grid(row=2, column=1, sticky="w", pady=(6, 0))
        ttk.Label(tab, text="置換後を空欄にすると、その文字列を削除します。",
                  foreground="#666666").grid(row=3, column=1, sticky="w", pady=(6, 0))
        return tab

    def _build_sequence_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)

        row = ttk.Frame(tab)
        row.grid(row=0, column=0, sticky="w")
        ttk.Label(row, text="連番の種類:").pack(side="left", padx=(0, 6))
        ttk.Radiobutton(row, text="数字 (001, 002...)", variable=self.seq_kind_var,
                        value="number", command=self._on_seq_kind_changed).pack(side="left")
        ttk.Radiobutton(row, text="英字 (A, B, C...)", variable=self.seq_kind_var,
                        value="letter", command=self._on_seq_kind_changed) \
            .pack(side="left", padx=(10, 0))

        row2 = ttk.Frame(tab)
        row2.grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(row2, text="開始:").pack(side="left", padx=(0, 4))
        ttk.Entry(row2, textvariable=self.seq_start_var, width=8).pack(side="left")
        ttk.Label(row2, text="増分:").pack(side="left", padx=(12, 4))
        ttk.Spinbox(row2, textvariable=self.seq_step_var, from_=1, to=999, width=5).pack(side="left")
        ttk.Label(row2, text="桁数(数字のみ):").pack(side="left", padx=(12, 4))
        ttk.Spinbox(row2, textvariable=self.seq_digits_var, from_=1, to=10, width=5).pack(side="left")
        ttk.Label(row2, text="区切り文字:").pack(side="left", padx=(12, 4))
        ttk.Entry(row2, textvariable=self.seq_sep_var, width=5).pack(side="left")

        pos = ttk.LabelFrame(tab, text=" 付ける位置 ", padding=6)
        pos.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Radiobutton(pos, text="名前の先頭に付ける", variable=self.seq_position_var,
                        value="prefix").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(pos, text="名前の末尾に付ける", variable=self.seq_position_var,
                        value="suffix").grid(row=0, column=1, sticky="w", padx=(16, 0))
        ttk.Radiobutton(pos, text="名前を連番だけにする", variable=self.seq_position_var,
                        value="replace").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Radiobutton(pos, text="上の条件の * の部分を置き換える", variable=self.seq_position_var,
                        value="wildcard").grid(row=1, column=1, sticky="w", padx=(16, 0), pady=(4, 0))
        return tab

    def _build_affix_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        tab.columnconfigure(1, weight=1)
        tab.columnconfigure(3, weight=1)

        ttk.Label(tab, text="先頭に追加:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(tab, textvariable=self.prefix_var).grid(row=0, column=1, sticky="ew")
        ttk.Label(tab, text="末尾に追加:").grid(row=0, column=2, sticky="w", padx=(12, 6))
        ttk.Entry(tab, textvariable=self.suffix_var).grid(row=0, column=3, sticky="ew")

        ttk.Label(tab, text="先頭から削除:").grid(row=1, column=0, sticky="w", pady=(8, 0), padx=(0, 6))
        head = ttk.Frame(tab)
        head.grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Spinbox(head, textvariable=self.trim_head_var, from_=0, to=99, width=5).pack(side="left")
        ttk.Label(head, text="文字").pack(side="left", padx=(4, 0))

        ttk.Label(tab, text="末尾から削除:").grid(row=1, column=2, sticky="w", pady=(8, 0), padx=(12, 6))
        tail = ttk.Frame(tab)
        tail.grid(row=1, column=3, sticky="w", pady=(8, 0))
        ttk.Spinbox(tail, textvariable=self.trim_tail_var, from_=0, to=99, width=5).pack(side="left")
        ttk.Label(tail, text="文字").pack(side="left", padx=(4, 0))

        ttk.Label(tab, text="削除してから追加する順に処理します。",
                  foreground="#666666").grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))
        return tab

    def _create_preview_frame(self):
        frame = ttk.LabelFrame(self, text=" 3. 変更内容を確認する ", padding=8)
        frame.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        columns = ("sel", "old", "new", "status")
        # height は最低限見せたい行数。ここが広いほど確認しやすいので大きめに取る
        self.tree = ttk.Treeview(frame, columns=columns, show="headings",
                                 selectmode="browse", height=12)
        self.tree.heading("sel", text="")
        self.tree.heading("old", text="変更前", anchor="w")
        self.tree.heading("new", text="変更後", anchor="w")
        self.tree.heading("status", text="状態", anchor="w")
        self.tree.column("sel", width=34, anchor="center", stretch=False)
        self.tree.column("old", width=300, anchor="w")
        self.tree.column("new", width=300, anchor="w")
        self.tree.column("status", width=180, anchor="w", stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")

        self.tree.tag_configure("error", foreground="#c0392b")
        self.tree.tag_configure("skip", foreground="#909090")
        self.tree.tag_configure("off", foreground="#909090")

        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)

        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", self._on_tree_space)

        buttons = ttk.Frame(frame)
        buttons.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(buttons, text="すべて選択", command=lambda: self._select_all(True), width=12) \
            .pack(side="left")
        ttk.Button(buttons, text="すべて解除", command=lambda: self._select_all(False), width=12) \
            .pack(side="left", padx=(6, 0))
        ttk.Checkbutton(buttons, text="変更があるものだけ表示", variable=self.only_changed_var,
                        command=self._redraw_tree).pack(side="left", padx=(12, 0))
        ttk.Label(buttons, text="チェック欄のクリックで個別に切り替え",
                  foreground="#666666").pack(side="left", padx=(12, 0))

    def _create_action_frame(self):
        frame = ttk.Frame(self)
        frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        frame.columnconfigure(0, weight=1)

        self.status_label = ttk.Label(frame, text="")
        self.status_label.grid(row=0, column=0, sticky="w")

        self.undo_button = ttk.Button(frame, text="元に戻す", command=self._undo,
                                      state="disabled", width=12)
        self.undo_button.grid(row=0, column=1, padx=(6, 0))
        self.run_button = ttk.Button(frame, text="名前を変更する", command=self._execute, width=16)
        self.run_button.grid(row=0, column=2, padx=(6, 0))

    def _bind_variables(self):
        """入力が変わったら、ファイル一覧やプレビューを自動で更新する。"""
        for var in (self.folder_var, self.pattern_var, self.recursive_var, self.sort_var):
            var.trace_add("write", lambda *a: self._schedule_reload())
        for var in (self.keep_ext_var,
                    self.search_var, self.replace_var, self.ignore_case_var,
                    self.seq_kind_var, self.seq_start_var, self.seq_step_var,
                    self.seq_digits_var, self.seq_position_var, self.seq_sep_var,
                    self.prefix_var, self.suffix_var, self.trim_head_var, self.trim_tail_var):
            var.trace_add("write", lambda *a: self._schedule_preview())

    # ------------------------------------------------------------ 対象ファイル

    def _choose_folder(self):
        folder = filedialog.askdirectory(title="対象フォルダを選んでください",
                                         initialdir=self.folder_var.get() or None)
        if folder:
            self.folder_var.set(str(Path(folder)))

    def _schedule_reload(self):
        """入力中に何度も読み込まないよう、少し待ってからファイル一覧を取り直す。"""
        if self._reload_job is not None:
            self.after_cancel(self._reload_job)
        self._reload_job = self.after(PREVIEW_DELAY * 2, self._reload_files)

    def _reload_files(self):
        self._reload_job = None
        folder = self.folder_var.get().strip()
        if not folder:
            self._files = []
            self._root_folder = None
            self._refresh_preview("対象フォルダを選んでください。")
            return
        try:
            self._files = core.collect_files(
                folder,
                self.pattern_var.get(),
                self.recursive_var.get(),
                SORT_LABELS.get(self.sort_var.get(), core.SORT_NAME),
            )
            self._root_folder = Path(folder)
        except OSError as exc:
            self._files = []
            self._root_folder = None
            self._refresh_preview(str(exc), error=True)
            return
        self._unchecked.clear()
        self._refresh_preview()

    # ------------------------------------------------------------ プレビュー

    def _current_rule(self):
        """選択中のタブに対応する変更ルールを組み立てる。"""
        tab = self.notebook.index(self.notebook.select())
        keep_ext = self.keep_ext_var.get()

        if tab == TAB_REPLACE:
            return core.ReplaceRule(
                search=self.search_var.get(),
                replace=self.replace_var.get(),
                ignore_case=self.ignore_case_var.get(),
                keep_ext=keep_ext,
            )
        if tab == TAB_SEQUENCE:
            return core.SequenceRule(
                kind=self.seq_kind_var.get(),
                start=self.seq_start_var.get(),
                step=to_int(self.seq_step_var.get(), 1),
                digits=to_int(self.seq_digits_var.get(), 3),
                position=self.seq_position_var.get(),
                separator=self.seq_sep_var.get(),
                wildcard=self.pattern_var.get(),
                keep_ext=keep_ext,
            )
        return core.AffixRule(
            prefix=self.prefix_var.get(),
            suffix=self.suffix_var.get(),
            trim_head=to_int(self.trim_head_var.get(), 0),
            trim_tail=to_int(self.trim_tail_var.get(), 0),
            keep_ext=keep_ext,
        )

    def _on_seq_kind_changed(self):
        """連番の種類を切り替えたとき、開始欄がその種類に合わなければ既定値に直す。"""
        value = self.seq_start_var.get().strip()
        if self.seq_kind_var.get() == "letter":
            if not value.isalpha():
                self.seq_start_var.set("A")
        elif not value.isdigit():
            self.seq_start_var.set("1")

    def _schedule_preview(self):
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(PREVIEW_DELAY, self._refresh_preview)

    def _refresh_preview(self, message="", error=False):
        self._preview_job = None
        try:
            self._entries = core.build_plan(self._files, self._current_rule())
        except ValueError as exc:
            # 設定が正しくない間も対象ファイルは一覧に残し、理由は下部に赤字で示す
            self._entries = [
                core.RenameEntry(path=p, new_name="", status=core.STATUS_ERROR,
                                 message="変更できません", selected=False)
                for p in self._files
            ]
            self._redraw_tree()
            self._set_status(str(exc), error=True)
            return

        # 利用者が手動で外したチェックは、プレビューを作り直しても維持する
        for entry in self._entries:
            if str(entry.path) in self._unchecked:
                entry.selected = False

        self._redraw_tree()
        if message:
            self._set_status(message, error=error)
        else:
            self._update_status()

    def _display_name(self, path):
        """再帰的に集めた場合は、対象フォルダからの相対パスで表示する。"""
        if self.recursive_var.get() and self._root_folder is not None:
            try:
                return str(path.relative_to(self._root_folder))
            except ValueError:
                pass
        return path.name

    def _row_config(self, entry):
        """1 行分の表示内容と色分け用のタグを返す。追加時と切り替え時で共通に使う。"""
        if entry.status == core.STATUS_SKIP:
            mark, new_name, status, tag = "", "", entry.message, core.STATUS_SKIP
        elif entry.status == core.STATUS_ERROR:
            mark, new_name, status, tag = "", entry.new_name, entry.message, core.STATUS_ERROR
        elif entry.selected:
            mark, new_name, status, tag = CHECK_ON, entry.new_name, "変更します", core.STATUS_OK
        else:
            # チェックを外した行は、変更しないことが一目で分かるように薄く表示する
            mark, new_name, status, tag = CHECK_OFF, entry.new_name, "変更しません", "off"
        return (mark, self._display_name(entry.path), new_name, status), (tag,)

    def _redraw_tree(self):
        self.tree.delete(*self.tree.get_children())
        only_changed = self.only_changed_var.get()
        for index, entry in enumerate(self._entries):
            if only_changed and entry.status == core.STATUS_SKIP:
                continue          # 表示を絞るだけで、計画そのものからは外さない
            values, tags = self._row_config(entry)
            self.tree.insert("", "end", iid=str(index), values=values, tags=tags)

    # ------------------------------------------------------------ チェックの操作

    def _toggle(self, iid):
        entry = self._entries[int(iid)]
        if not entry.renamable:
            return
        entry.selected = not entry.selected
        if entry.selected:
            self._unchecked.discard(str(entry.path))
        else:
            self._unchecked.add(str(entry.path))
        values, tags = self._row_config(entry)
        self.tree.item(iid, values=values, tags=tags)
        self._update_status()

    def _on_tree_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        iid = self.tree.identify_row(event.y)
        if iid:
            self._toggle(iid)

    def _on_tree_space(self, event):
        for iid in self.tree.selection():
            self._toggle(iid)
        return "break"

    def _select_all(self, selected):
        for entry in self._entries:
            if entry.renamable:
                entry.selected = selected
                if selected:
                    self._unchecked.discard(str(entry.path))
                else:
                    self._unchecked.add(str(entry.path))
        self._redraw_tree()
        self._update_status()

    # ------------------------------------------------------------ 状態表示

    def _set_status(self, text, error=False):
        self.status_label.configure(text=text, foreground="#c0392b" if error else "#333333")

    def _update_status(self):
        total = len(self._entries)
        targets = sum(1 for e in self._entries if e.selected and e.renamable)
        problems = sum(1 for e in self._entries if e.status == core.STATUS_ERROR)
        if total == 0:
            self._set_status("対象のファイルがありません。")
            return
        text = "対象 {} 件 / 変更する {} 件".format(total, targets)
        if problems:
            text += " / 変更できない {} 件".format(problems)
        self._set_status(text, error=bool(problems) and targets == 0)

    def _update_undo_button(self):
        self.undo_button.configure(state="normal" if self._history else "disabled")

    # ------------------------------------------------------------ 実行と取り消し

    def _execute(self):
        targets = [e for e in self._entries if e.selected and e.renamable]
        if not targets:
            messagebox.showinfo("確認", "変更するファイルが選ばれていません。", parent=self)
            return
        if not messagebox.askyesno(
                "実行の確認",
                "{} 件のファイル名を変更します。\nよろしいですか？".format(len(targets)),
                parent=self):
            return

        done, errors = core.execute_plan(self._entries)
        if errors:
            detail = "\n".join("{}: {}".format(p.name, m) for p, m in errors[:10])
            messagebox.showerror(
                "エラー",
                "変更できなかったため、元の状態に戻しました。\n\n" + detail,
                parent=self)
        else:
            self._history = done
            messagebox.showinfo("完了",
                                "{} 件のファイル名を変更しました。".format(len(done)),
                                parent=self)
        self._update_undo_button()
        self._reload_files()

    def _undo(self):
        if not self._history:
            return
        if not messagebox.askyesno(
                "確認",
                "直前に変更した {} 件を元の名前に戻します。\nよろしいですか？".format(len(self._history)),
                parent=self):
            return

        done, errors = core.undo(self._history)
        if errors:
            detail = "\n".join("{}: {}".format(p.name, m) for p, m in errors[:10])
            messagebox.showerror("エラー", "元に戻せませんでした。\n\n" + detail, parent=self)
        else:
            messagebox.showinfo("完了",
                                "{} 件のファイル名を元に戻しました。".format(len(done)),
                                parent=self)
            self._history = []
        self._update_undo_button()
        self._reload_files()


def main():
    enable_dpi_awareness()
    root = tk.Tk()
    root.title("ファイル名 一括変更")
    root.geometry("960x780")
    root.minsize(860, 620)
    apply_font(root)

    initial_folder = sys.argv[1] if len(sys.argv) > 1 else ""
    app = RenameApp(root, initial_folder)
    app.pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    main()
