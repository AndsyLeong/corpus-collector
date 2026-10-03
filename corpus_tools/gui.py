import os
from pathlib import Path
import queue
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .cli import search_items
from .inputs import MEDIA, attach_text, timestamp
from .media import collect
from .providers import Qwen, Settings
from .transcription import transcribe_many
from .ui import (BACKGROUND, WHITE, BLUE, NAVY, MUTED, BORDER, PALE,
                 Button, Card, Check, Pill, Progress, Table, font, icon, rounded)

CONVERSIONS = {"保持原文": "none", "繁体转简体": "t2s", "简体转香港繁体": "s2hk"}


def enable_dpi_awareness():
    if os.name == "nt":
        import ctypes
        try:
            function = ctypes.windll.user32.SetProcessDpiAwarenessContext
            function.argtypes = [ctypes.c_void_p]
            function(ctypes.c_void_p(-4))
        except AttributeError:
            ctypes.windll.user32.SetProcessDPIAware()


def create_root():
    root = tk.Tk()
    try:
        from tkinterdnd2 import TkinterDnD
        loader = getattr(TkinterDnD, "require", None) or TkinterDnD._require
        root.TkdndVersion = loader(root)
    except (ImportError, tk.TclError, RuntimeError, OSError):
        root.TkdndVersion = None
    return root


class App:
    def __init__(self, root):
        self.root = root
        self.items = {}
        self.busy = False
        self.messages = queue.Queue()
        self.stop = threading.Event()
        self.buttons = []
        self.rows = []
        self.refreshing = False
        self.asr_settings = Settings()
        self.sort_column, self.sort_reverse = "文件名", False
        self.log_dialog = None
        root.title("视频与音频语料收集")
        width = min(1448, root.winfo_screenwidth()-60)
        height = min(1056, root.winfo_screenheight()-100)
        self.scale = s = min(1, width/1448, height/1056)
        self.p = lambda value: round(value*s)
        p = self.p
        root.geometry(f"{width}x{height}")
        root.minsize(min(width, p(1360)), min(height, p(1000)))
        root.configure(background=BACKGROUND)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.styles()
        outer = tk.Frame(root, background=BACKGROUND)
        outer.pack(fill="both", expand=True, padx=p(22), pady=(p(14), p(22)))

        header = tk.Frame(outer, background=BACKGROUND, height=p(84))
        header.pack(fill="x", pady=(0, p(10)))
        header.pack_propagate(False)
        logo = tk.Canvas(header, width=p(74), height=p(74), background=BACKGROUND,
                         bd=0, highlightthickness=0)
        logo.pack(side="left", padx=(p(12), p(27)))
        rounded(logo, 1, 1, p(73), p(73), p(20), fill=BLUE, outline="")
        rounded(logo, p(13), p(26), p(35), p(49), p(5), fill=WHITE, outline="")
        logo.create_polygon(p(20), p(31), p(20), p(44), p(30), p(37.5), fill=BLUE)
        for x, length in ((43, 20), (50, 30), (57, 15)):
            logo.create_line(p(x), p(37.5-length/2), p(x), p(37.5+length/2),
                             fill=WHITE, width=p(3), capstyle="round")
        titles = tk.Frame(header, background=BACKGROUND)
        titles.pack(side="left")
        self.label(titles, "视频与音频语料收集", 34, True,
                   background=BACKGROUND).pack(anchor="w")
        self.label(titles, "支持将视频/音频转写为文本，并进行关键词检索与导出",
                   19, color=MUTED, background=BACKGROUND).pack(anchor="w", pady=(p(5), 0))
        self.button(header, "阿里云 ASR 设置", self.settings_dialog,
                    symbol="gear", width=210, height=48).pack(side="right", padx=p(4))

        output_card = Card(outer, s, padding=16, height=p(102))
        output_card.pack(fill="x", pady=(0, p(14)))
        output_bar = output_card.content
        output_bar.columnconfigure(1, weight=1)
        save_title = tk.Frame(output_bar, background=WHITE)
        save_title.grid(row=0, column=0, sticky="w", padx=(p(8), p(22)))
        self.small_icon(save_title, "folder", BLUE).pack(side="left", padx=(0, p(10)))
        self.label(save_title, "保存位置", 17, True).pack(side="left")
        self.output = tk.StringVar()
        entry_box = tk.Frame(output_bar, background=WHITE, highlightbackground="#cfd9ea",
                             highlightthickness=1, height=p(43))
        entry_box.grid(row=0, column=1, sticky="ew", padx=(0, p(12)))
        entry_box.grid_propagate(False)
        entry_box.columnconfigure(0, weight=1)
        entry_box.rowconfigure(0, weight=1)
        self.output_entry = tk.Entry(entry_box, textvariable=self.output, font=font(17, scale=s),
                                     background=WHITE, foreground=NAVY, relief="flat", bd=0,
                                     insertbackground=BLUE, disabledbackground=PALE)
        self.output_entry.grid(row=0, column=0, sticky="nsew", padx=p(12), pady=p(7))
        self.output_hint = self.label(entry_box, "留空时保存在原文件旁", 17, color=MUTED)
        self.output_hint.bind("<Button-1>", lambda _: self.output_entry.focus_set())
        self.output.trace_add("write", lambda *_: self.update_output_hint())
        self.output_entry.bind("<FocusIn>", lambda _: self.update_output_hint())
        self.output_entry.bind("<FocusOut>", lambda _: self.update_output_hint())
        self.button(output_bar, "选择文件夹", self.choose_output, symbol="folder",
                    width=164, height=44).grid(row=0, column=2, padx=(0, p(10)))
        self.button(output_bar, "使用原文件位置", lambda: self.output.set(""),
                    symbol="folder-original", width=190, height=44).grid(row=0, column=3)
        self.label(output_bar, "每个媒体一个文件夹：媒体副本 + SRT + TXT + 检索表格。保存位置留空时位于原文件旁。",
                   15, color=MUTED).grid(row=1, column=1, columnspan=3, sticky="w", pady=(p(7), 0))
        self.update_output_hint()

        bottom = Card(outer, s, padding=10, height=p(56))
        bottom.pack(side="bottom", fill="x", pady=(p(12), 0))
        footer = bottom.content
        self.dot = tk.Canvas(footer, width=p(27), height=p(27), bg=WHITE, highlightthickness=0)
        self.dot.create_oval(p(3), p(3), p(24), p(24), fill="#bdc8d8", outline="", tags="dot")
        self.dot.pack(side="left", padx=(p(4), p(12)))
        self.status = self.label(footer, "就绪 · 添加媒体开始使用", 15, True, anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        self.progress = Progress(footer, s)
        self.progress.pack(side="left", padx=(p(8), p(16)))
        self.percent = self.label(footer, "0%", 15, color=MUTED, width=5)
        self.percent.pack(side="left", padx=(0, p(18)))
        self.log_button = Button(footer, "日志", self.show_logs, scale=s, width=60, height=36, compact=True)
        self.log_button.pack(side="left", padx=(0, p(10)))
        self.stop_button = Button(footer, "停止", self.request_stop, "stop", scale=s, width=116, height=38)
        self.stop_button.configure(state="disabled")
        self.stop_button.pack(side="left")
        self.logs = tk.Text(root, state="disabled")

        body = tk.Frame(outer, background=BACKGROUND)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=37, uniform="body")
        body.columnconfigure(1, weight=63, uniform="body")
        body.rowconfigure(0, weight=1)
        left_card = Card(body, s, padding=18)
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, p(14)))
        left = left_card.content
        left_header = tk.Frame(left, background=WHITE)
        left_header.pack(fill="x", pady=(0, p(14)))
        media_symbol = tk.Canvas(left_header, width=p(36), height=p(36), bg=WHITE, highlightthickness=0)
        rounded(media_symbol, 0, 0, p(36), p(36), p(5), fill=BLUE, outline="")
        icon(media_symbol, "play", p(7), p(7), p(22), WHITE)
        media_symbol.pack(side="left", padx=(0, p(12)))
        self.label(left_header, "媒体文件", 23, True).pack(side="left")
        self.file_count = Pill(left_header, "0 个文件", s)
        self.file_count.pack(side="right")
        add_bar = tk.Frame(left, background=WHITE)
        add_bar.pack(fill="x", pady=(0, p(16)))
        add_bar.columnconfigure((0, 1), weight=1, uniform="add")
        self.button(add_bar, "添加视频 / 音频", self.add_files, primary=True, symbol="plus",
                    width=225, height=54).grid(row=0, column=0, sticky="ew", padx=(0, p(12)))
        self.button(add_bar, "批量添加文件夹", self.add_folder, symbol="folder-plus",
                    width=225, height=54).grid(row=0, column=1, sticky="ew")
        media_footer = tk.Frame(left, background=WHITE)
        media_footer.pack(side="bottom", fill="x")
        left_actions = tk.Frame(media_footer, background=WHITE)
        left_actions.pack(fill="x", pady=(p(14), p(12)))
        for index, (text, command, symbol, width) in enumerate((
                ("全选", self.select_all, "check", 110),
                ("移出列表", self.remove_selected, "trash", 148),
                ("打开文件夹", self.open_selected_folder, "folder", 180))):
            left_actions.columnconfigure(index, weight=width, uniform="actions")
            self.button(left_actions, text, command, symbol=symbol, width=width, height=48,
                        compact=True).grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else p(10), 0))
        self.selected_label = self.label(media_footer, "点击选择媒体；Ctrl / Shift 可多选。", 15, color=MUTED)
        self.selected_label.pack(anchor="w")
        self.label(media_footer, "转写和检索作用于选中的文件。", 15, color=MUTED).pack(anchor="w", pady=(p(3), 0))
        self.media_table = Table(left, ("选择", "文件名", "状态"), (50, 240, 116), s,
                                 selectmode="extended", kind="media")
        self.media_table.pack(fill="both", expand=True)
        self.media_tree = self.media_table.tree
        self.media_tree.column("文件名", stretch=True)
        self.media_tree.column("状态", stretch=False)
        self.media_tree.column("选择", stretch=False, anchor="center")
        self.media_tree.heading("选择", text="☐", command=self.toggle_all)
        for name in ("文件名", "状态"):
            self.media_tree.heading(name, text=f"{name}  ↕", command=lambda key=name: self.sort_media(key))
        self.media_tree.bind("<<TreeviewSelect>>", self.selection_changed)
        self.media_tree.bind("<Button-1>", self.media_click, add="+")
        self.media_table.empty.command = self.add_files
        self.media_table.empty.bind("<Button-1>", lambda _: self.add_files() if not self.busy else None)

        right = tk.Frame(body, background=BACKGROUND)
        right.grid(row=0, column=1, sticky="nsew")
        first_card = Card(right, s, padding=18, height=p(162))
        first_card.pack(fill="x", pady=(0, p(14)))
        first = first_card.content
        self.step_header(first, "1", "转写文本", "将视频/音频转写为文本，或使用已有字幕 / TXT 文件")
        first_bar = tk.Frame(first, background=WHITE)
        first_bar.pack(fill="x", pady=(p(10), 0))
        self.button(first_bar, "开始 / 继续转写", self.start_transcription, primary=True,
                    symbol="play", width=200, height=54).pack(side="left")
        self.button(first_bar, "使用已有字幕 / TXT", self.use_text,
                    symbol="document", width=220, height=54).pack(side="left", padx=p(12))
        self.button(first_bar, "查看 TXT", self.open_text, symbol="search",
                    width=172, height=54).pack(side="left")
        tk.Frame(first_bar, background=BORDER, width=1).pack(side="left", fill="y", padx=p(15), pady=p(4))
        self.text_status = self.label(first_bar, "暂无文本", 16, color=MUTED)
        self.text_status.pack(side="left")

        second_card = Card(right, s, padding=18)
        second_card.pack(fill="both", expand=True)
        second = second_card.content
        self.step_header(second, "2", "检索词汇与导出表格", "输入关键词或短语，检索文本并导出结果表格")
        keyword_header = tk.Frame(second, background=WHITE)
        keyword_header.pack(fill="x", pady=(p(16), p(8)))
        self.label(keyword_header, "关键词或短语", 17, True).pack(side="left")
        self.label(keyword_header, "（每行一个，也可用逗号分隔）", 16, color=MUTED).pack(side="left")
        self.keyword_count = self.label(keyword_header, "0 行", 15, color=MUTED)
        self.keyword_count.pack(side="right")
        self.keyword_box = tk.Frame(second, background=WHITE, highlightbackground="#cfd9ea",
                                    highlightthickness=1, height=p(95))
        self.keyword_box.pack(fill="x")
        self.keyword_box.pack_propagate(False)
        self.keyword_text = tk.Text(self.keyword_box, height=3, wrap="word", relief="flat", bd=0,
                                    font=font(17, scale=s), foreground=NAVY, background=WHITE,
                                    insertbackground=BLUE, padx=p(12), pady=p(8), undo=True)
        self.keyword_text.pack(fill="both", expand=True)
        self.keyword_hint = self.label(self.keyword_box, "例如：人工智能\n大模型，语音识别\n会议记录",
                                        17, color=MUTED, justify="left")
        self.keyword_hint.bind("<Button-1>", lambda _: self.keyword_text.focus_set())
        self.keyword_text.bind("<<Modified>>", self.keyword_changed)
        self.keyword_text.bind("<FocusIn>", self.keyword_changed)
        self.keyword_text.bind("<FocusOut>", self.keyword_changed)
        expand = tk.Canvas(self.keyword_box, width=p(24), height=p(24), bg=WHITE,
                           highlightthickness=0, cursor="hand2", takefocus=1)
        icon(expand, "expand", 2, 2, p(18), MUTED)
        expand.place(relx=1, rely=1, x=-p(8), y=-p(6), anchor="se")
        expand.bind("<Button-1>", lambda _: self.expand_keywords())
        expand.bind("<Return>", lambda _: self.expand_keywords())
        self.keyword_changed()

        options = tk.Frame(second, background=WHITE)
        options.pack(fill="x", pady=p(10))
        self.label(options, "文本来源", 16).pack(side="left", padx=(0, p(14)))
        self.conversion = tk.StringVar(value="保持原文")
        self.conversion_box = ttk.Combobox(options, values=list(CONVERSIONS), textvariable=self.conversion,
                     state="readonly", width=17, font=font(16, scale=s), style="Corpus.TCombobox")
        self.conversion_box.pack(side="left", padx=(0, p(26)))
        self.ignore_case = tk.BooleanVar(value=True)
        case_check = Check(options, "忽略英文大小写", self.ignore_case, s, width=180)
        case_check.pack(side="left", padx=(0, p(18)))
        self.csv_only = tk.BooleanVar(value=False)
        csv_check = Check(options, "仅 CSV", self.csv_only, s, width=99)
        csv_check.pack(side="left", padx=(0, p(8)))
        self.option_checks = [case_check, csv_check]
        help_label = tk.Canvas(options, width=p(20), height=p(20), bg=WHITE, highlightthickness=0, cursor="hand2")
        help_label.create_oval(1, 1, p(19), p(19), fill="#a6b5cc", outline="")
        help_label.create_text(p(10), p(10), text="?", fill=WHITE, font=font(14, True, s))
        help_label.pack(side="left", padx=p(4))
        help_label.bind("<Button-1>", lambda _: messagebox.showinfo("检索选项",
            "文本来源可保持原文，或先转换繁简再检索。\n\n忽略英文大小写：Apple 与 apple 均可命中。\n\n仅 CSV：只导出 CSV；默认同时导出 CSV 和 Excel 表格。",
            parent=self.root))

        search_bar = tk.Frame(second, background=WHITE)
        search_bar.pack(fill="x", pady=(0, p(14)))
        self.button(search_bar, "检索预览", self.start_search, symbol="search",
                    width=181, height=54).pack(side="left")
        self.button(search_bar, "检索并导出表格", lambda: self.start_search(True), primary=True,
                    symbol="upload", width=242, height=54).pack(side="left", padx=p(12))
        result_box = tk.Frame(search_bar, background=PALE, height=p(54))
        result_box.pack(side="left", fill="both", expand=True)
        result_box.pack_propagate(False)
        self.small_icon(result_box, "folder", "#637ca1", background=PALE).pack(side="left", padx=(p(12), p(8)))
        self.result_label = self.label(result_box, "选择媒体后输入关键词", 15, color="#637ca1", background=PALE, anchor="w")
        self.result_label.pack(side="left", fill="both", expand=True)
        self.preview_box = tk.Frame(second, background=PALE, highlightbackground=BORDER, highlightthickness=1)
        self.preview = tk.Text(self.preview_box, height=2, wrap="word", state="disabled",
                               relief="flat", background=PALE, foreground=NAVY,
                               font=font(14, scale=s), padx=p(10), pady=p(6))
        self.preview.pack(fill="both", expand=True)
        self.result_table = Table(second, ("#", "来源文件", "时间段", "关键词", "文本"),
                                   (49, 200, 190, 130, 236), s)
        self.result_table.pack(fill="both", expand=True)
        self.hits = self.result_table.tree
        self.hits.bind("<<TreeviewSelect>>", self.show_hit)
        self.hits.bind("<Escape>", lambda _: self.preview_box.pack_forget())
        self.register_drop()
        self.media_table.update_empty()
        self.result_table.update_empty()
        root.after(100, self.poll)

    def styles(self):
        s = self.scale
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.layout("Corpus.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure("Corpus.Treeview", background=WHITE, fieldbackground=WHITE,
                        foreground=NAVY, borderwidth=0, relief="flat", font=font(16, scale=s),
                        rowheight=self.p(38), bordercolor=WHITE, lightcolor=WHITE, darkcolor=WHITE)
        style.map("Corpus.Treeview", background=[("selected", "#e7f1ff")],
                  foreground=[("selected", NAVY)])
        style.configure("Corpus.Treeview.Heading", background="#f3f7fc", foreground=NAVY,
                        font=font(16, True, s), padding=(self.p(8), self.p(10)),
                        borderwidth=0, relief="flat", bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        style.map("Corpus.Treeview.Heading", background=[("active", "#eaf2ff")])
        style.configure("Corpus.TCombobox", fieldbackground=WHITE, background=PALE,
                        foreground=NAVY, bordercolor="#cfd9ea", arrowcolor="#526c94",
                        padding=self.p(6), lightcolor=WHITE, darkcolor=WHITE)
        style.map("Corpus.TCombobox", fieldbackground=[("readonly", WHITE)],
                  foreground=[("readonly", NAVY)], selectbackground=[("readonly", WHITE)],
                  selectforeground=[("readonly", NAVY)])
        self.root.option_add("*TCombobox*Listbox.font", font(16, scale=s))
        for direction in ("Vertical", "Horizontal"):
            style.configure(f"Corpus.{direction}.TScrollbar", background="#cfdbed",
                            troughcolor="#f6f9fe", borderwidth=0, arrowsize=self.p(12))
        style.configure("TFrame", background=WHITE)
        style.configure("TLabel", background=WHITE, foreground=NAVY, font=font(16, scale=s))
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("TEntry", padding=6)
        style.configure("TButton", padding=(12, 8), font=font(16, scale=s))

    def label(self, parent, text, size=17, bold=False, color=NAVY, background=WHITE, **kwargs):
        kwargs.setdefault("padx", 0)
        kwargs.setdefault("pady", 0)
        return tk.Label(parent, text=text, font=font(size, bold, self.scale), foreground=color,
                        background=background, bd=0, **kwargs)

    def small_icon(self, parent, symbol, color=NAVY, background=WHITE):
        widget = tk.Canvas(parent, width=self.p(26), height=self.p(26),
                           bg=background, highlightthickness=0)
        icon(widget, symbol, self.p(1), self.p(1), self.p(24), color)
        return widget

    def step_header(self, parent, number, title, subtitle):
        header = tk.Frame(parent, background=WHITE)
        header.pack(fill="x")
        badge = tk.Canvas(header, width=self.p(43), height=self.p(43), bg=WHITE, highlightthickness=0)
        badge.create_oval(0, 0, self.p(42), self.p(42), fill=BLUE, outline="")
        badge.create_text(self.p(21), self.p(21), text=number, fill=WHITE, font=font(25, True, self.scale))
        badge.pack(side="left", anchor="n", padx=(0, self.p(14)))
        texts = tk.Frame(header, background=WHITE)
        texts.pack(side="left")
        self.label(texts, title, 23, True).pack(anchor="w")
        self.label(texts, subtitle, 17, color=MUTED).pack(anchor="w", pady=(self.p(4), 0))

    def button(self, parent, text, command, primary=False, symbol="", width=160, height=50, compact=False):
        def guarded():
            try:
                command()
            except Exception as error:
                messagebox.showerror("操作失败", self.asr_settings.safe_error(error), parent=self.root)
        button = Button(parent, text, guarded, symbol, primary, self.scale, width, height, compact)
        self.buttons.append(button)
        return button

    def update_output_hint(self):
        if not self.output.get() and self.root.focus_get() != self.output_entry:
            self.output_hint.place(x=self.p(12), rely=.5, anchor="w")
        else:
            self.output_hint.place_forget()

    def keyword_changed(self, event=None):
        value = self.keyword_text.get("1.0", "end-1c")
        count = sum(bool(line.strip()) for line in value.splitlines())
        self.keyword_count.configure(text=f"{count} 行")
        if not value and self.root.focus_get() != self.keyword_text:
            self.keyword_hint.place(x=self.p(12), y=self.p(8))
        else:
            self.keyword_hint.place_forget()
        if self.keyword_text.edit_modified():
            self.keyword_text.edit_modified(False)

    def expand_keywords(self):
        if self.busy:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("编辑关键词或短语")
        dialog.geometry("620x460")
        dialog.transient(self.root)
        panel = tk.Frame(dialog, bg=WHITE)
        panel.pack(fill="both", expand=True, padx=18, pady=18)
        editor = tk.Text(panel, wrap="word", font=font(17), undo=True, relief="solid", bd=1)
        editor.pack(fill="both", expand=True, pady=(0, 12))
        editor.insert("1.0", self.keyword_text.get("1.0", "end-1c"))
        def save():
            self.keyword_text.delete("1.0", "end")
            self.keyword_text.insert("1.0", editor.get("1.0", "end-1c"))
            self.keyword_changed()
            dialog.destroy()
        ttk.Button(panel, text="应用关键词", command=save).pack(anchor="e")
        dialog.grab_set()
        editor.focus_set()

    def register_drop(self):
        draggable = bool(getattr(self.root, "TkdndVersion", None))
        if draggable:
            from tkinterdnd2 import DND_FILES
            for widget in (self.media_tree, self.media_table.empty):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self.drop_files)
        self.media_table.empty.draggable = draggable
        self.media_table.empty.draw()

    def drop_files(self, event):
        if self.busy:
            return "refuse_drop"
        try:
            paths = list(self.root.tk.splitlist(event.data))
            supported = [path for path in paths if Path(path).is_dir() or Path(path).suffix.lower() in MEDIA]
            if not supported:
                raise ValueError("请拖入视频、音频或包含媒体的文件夹。")
            self.start_add(supported)
            return "copy"
        except Exception as error:
            messagebox.showerror("添加失败", self.asr_settings.safe_error(error), parent=self.root)
            return "refuse_drop"

    def select_all(self):
        self.media_tree.selection_set(self.media_tree.get_children())

    def toggle_all(self):
        if self.busy:
            return
        all_items = self.media_tree.get_children()
        if all_items and len(self.media_tree.selection()) == len(all_items):
            self.media_tree.selection_remove(all_items)
        else:
            self.select_all()

    def media_click(self, event):
        if self.media_tree.identify_region(event.x, event.y) == "cell" and self.media_tree.identify_column(event.x) == "#1":
            item = self.media_tree.identify_row(event.y)
            if item:
                if item in self.media_tree.selection():
                    self.media_tree.selection_remove(item)
                else:
                    self.media_tree.selection_add(item)
                return "break"

    def sort_media(self, column):
        self.sort_reverse = not self.sort_reverse if self.sort_column == column else False
        self.sort_column = column
        self.order_media()

    def order_media(self):
        children = sorted(self.media_tree.get_children(),
                          key=lambda sid: self.media_tree.set(sid, self.sort_column).casefold(),
                          reverse=self.sort_reverse)
        for index, sid in enumerate(children):
            self.media_tree.move(sid, "", index)
        for column in ("文件名", "状态"):
            arrow = ("↓" if self.sort_reverse else "↑") if column == self.sort_column else "↕"
            self.media_tree.heading(column, text=f"{column}  {arrow}")

    def request_stop(self):
        self.stop.set()
        self.stop_button.configure(state="disabled")
        self.status.configure(text="正在停止 · 等待当前操作结束")

    def show_logs(self):
        if self.log_dialog and self.log_dialog.winfo_exists():
            self.log_dialog.lift()
            return
        self.log_dialog = dialog = tk.Toplevel(self.root)
        dialog.title("任务日志")
        dialog.geometry("820x360")
        dialog.transient(self.root)
        self.visible_logs = tk.Text(dialog, wrap="word", font=font(15), bg=WHITE, fg=NAVY,
                                    padx=14, pady=12, relief="flat")
        self.visible_logs.pack(fill="both", expand=True)
        self.visible_logs.insert("1.0", self.logs.get("1.0", "end-1c") or "暂无任务日志")
        self.visible_logs.configure(state="disabled")

    def selected_items(self):
        items = [self.items[sid] for sid in self.media_tree.selection() if sid in self.items]
        if not items:
            raise ValueError("请先添加并选中视频或音频。")
        return items

    def choose_output(self):
        path = filedialog.askdirectory(title="选择媒体整理文件夹的保存位置", parent=self.root)
        if path:
            self.output.set(path)

    def add_files(self):
        paths = filedialog.askopenfilenames(title="添加视频或音频", parent=self.root,
                 filetypes=[("视频和音频", " ".join("*"+suffix for suffix in sorted(MEDIA)))])
        if paths:
            self.start_add(paths)

    def add_folder(self):
        path = filedialog.askdirectory(title="批量添加文件夹中的视频与音频", parent=self.root)
        if path:
            self.start_add([path])

    def start_add(self, paths):
        output = self.output.get().strip() or None
        def work():
            result = collect(paths, output, self.stop, log=lambda text: self.messages.put(("log", text)))
            self.messages.put(("log", f"添加 {len(result['items'])} 个媒体，失败 {len(result['errors'])} 个。"))
            return {"added": result["items"], "errors": result["errors"], "stopped": result["stopped"]}
        self.run_task("复制与添加媒体", work, cancellable=True)

    def remove_selected(self):
        for item in self.selected_items():
            self.items.pop(item.id)
        self.refresh()

    def settings_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("阿里云 ASR 设置")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        panel = ttk.Frame(dialog, padding=18)
        panel.pack(fill="both", expand=True)
        variables = {}
        fields = [("qwen_key", "API Key"), ("qwen_model", "模型"), ("language", "语言（留空自动识别）"),
                  ("qwen_base", "服务地址"), ("ffmpeg", "FFmpeg 路径"),
                  ("chunk_seconds", "每段秒数（5–120）"), ("rpm", "每分钟请求数"), ("timeout", "超时秒数")]
        for i, (key, label) in enumerate(fields):
            ttk.Label(panel, text=label).grid(row=i, column=0, sticky="w", padx=(0, 12), pady=4)
            variable = tk.StringVar(value=str(getattr(self.asr_settings, key)))
            variables[key] = variable
            ttk.Entry(panel, textvariable=variable, width=65, show="*" if key == "qwen_key" else "").grid(
                row=i, column=1, sticky="ew", pady=4)
        ttk.Label(panel, text="语言示例：zh 普通话、en 英语、yue 粤语。密钥仅在本次运行中使用。",
                  style="Muted.TLabel").grid(row=len(fields), column=0, columnspan=2, sticky="w", pady=10)
        def save():
            try:
                values = {key: var.get().strip() for key, var in variables.items()}
                for key in ("chunk_seconds", "rpm", "timeout"):
                    values[key] = int(values[key])
                if not 5 <= values["chunk_seconds"] <= 120 or values["rpm"] < 1 or values["timeout"] < 1:
                    raise ValueError("请检查分段秒数、请求数与超时秒数。")
                self.asr_settings = Settings(**values)
                dialog.destroy()
            except Exception as error:
                messagebox.showerror("设置错误", str(error), parent=dialog)
        ttk.Button(panel, text="保存设置", command=save).grid(row=len(fields)+1, column=1, sticky="e")
        dialog.grab_set()
        dialog.wait_window()

    def use_text(self):
        items = self.selected_items()
        if len(items) != 1:
            raise ValueError("使用已有字幕或 TXT 时，请只选中一个媒体。")
        file = filedialog.askopenfilename(title=f"为 {items[0].media_path.name} 选择已有文本", parent=self.root,
                                        filetypes=[("字幕、文本与表格", "*.srt *.txt *.csv *.xlsx")])
        if file:
            def work():
                count = attach_text(items[0], file)
                self.messages.put(("log", f"{items[0].media_path.name}：已使用 {count} 段已有文本。"))
                return {}
            self.run_task("读取已有文本", work)

    def start_transcription(self):
        items = self.selected_items()
        pending = [item for item in items if not item.read()["sources"][item.id]["transcribed"]]
        if not pending:
            self.append_log("所选媒体已有文本，可直接检索。")
            return
        if not self.asr_settings.qwen_key:
            self.settings_dialog()
        service = Qwen(self.asr_settings)
        settings = self.asr_settings
        def work():
            result = transcribe_many(pending, service, settings, self.stop,
                                    log=lambda text: self.messages.put(("log", text)))
            self.messages.put(("log", f"转写完成 {result['completed']} 个，失败 {result['failed']} 个。"))
            return result
        self.run_task("转写所选媒体", work, cancellable=True)

    def start_search(self, save=False):
        items = self.selected_items()
        keywords = re.split(r"[\n,，]+", self.keyword_text.get("1.0", "end"))
        if not any(word.strip() for word in keywords):
            raise ValueError("请输入至少一个关键词或短语。")
        conversion = CONVERSIONS[self.conversion.get()]
        ignore_case, xlsx = self.ignore_case.get(), not self.csv_only.get()
        def work():
            return search_items(items, keywords, conversion, ignore_case, xlsx, save,
                                log=lambda text: self.messages.put(("log", text)))
        self.run_task("检索并逐文件导出表格" if save else "检索词汇", work)

    def run_task(self, name, work, cancellable=False):
        if self.busy:
            raise ValueError("任务正在运行。")
        self.busy = True
        self.stop.clear()
        for button in self.buttons:
            button.configure(state="disabled")
        for check in self.option_checks:
            check.configure(state="disabled")
        self.keyword_text.configure(state="disabled")
        self.conversion_box.configure(state="disabled")
        self.output_entry.configure(state="disabled")
        self.stop_button.configure(state="normal" if cancellable else "disabled")
        self.status.configure(text=name + "…")
        self.percent.configure(text="进行中")
        self.dot.itemconfigure("dot", fill=BLUE)
        self.progress.start(12)
        settings = self.asr_settings
        def worker():
            try:
                self.messages.put(("done", work()))
            except Exception as error:
                self.messages.put(("error", settings.safe_error(error)))
        threading.Thread(target=worker, daemon=True).start()

    def append_log(self, value):
        self.logs.configure(state="normal")
        self.logs.insert("end", str(value) + "\n")
        self.logs.see("end")
        self.logs.configure(state="disabled")
        if self.log_dialog and self.log_dialog.winfo_exists():
            self.visible_logs.configure(state="normal")
            self.visible_logs.delete("1.0", "end")
            self.visible_logs.insert("1.0", self.logs.get("1.0", "end-1c"))
            self.visible_logs.see("end")
            self.visible_logs.configure(state="disabled")

    def poll(self):
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == "log":
                    self.append_log(value)
                elif kind in ("done", "error"):
                    self.busy = False
                    failed = kind == "error" or (isinstance(value, dict) and bool(value.get("errors") or value.get("failed")))
                    stopped = self.stop.is_set()
                    self.progress.finish(not failed and not stopped)
                    self.percent.configure(text="0%" if failed or stopped else "100%")
                    self.dot.itemconfigure("dot", fill="#d59649" if failed else "#bdc8d8" if stopped else BLUE)
                    for button in self.buttons:
                        button.configure(state="normal")
                    for check in self.option_checks:
                        check.configure(state="normal")
                    self.keyword_text.configure(state="normal")
                    self.conversion_box.configure(state="readonly")
                    self.output_entry.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.status.configure(text="已停止 · 可继续处理" if stopped else
                                          "任务结束 · 部分文件失败，请查看日志" if failed and kind == "done" else
                                          "任务失败 · 请查看日志" if failed else
                                          "任务完成 · 结果保存在各媒体文件夹")
                    select = None
                    if kind == "done" and "added" in value:
                        select = []
                        for item in value["added"]:
                            self.items[item.id] = item
                            select.append(item.id)
                        if select and not self.keyword_text.get("1.0", "end").strip():
                            previous = self.items[select[0]].read()["search"]
                            if previous["keywords"]:
                                self.keyword_text.insert("1.0", "\n".join(previous["keywords"]))
                                self.ignore_case.set(previous.get("ignore_case", False))
                                self.conversion.set(next(name for name, code in CONVERSIONS.items()
                                                         if code == previous.get("conversion", "none")))
                    if kind == "error":
                        self.append_log(value)
                        messagebox.showerror("任务失败", value, parent=self.root)
                    self.refresh(select)
                    self.keyword_changed()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def refresh(self, select=None):
        selected = self.media_tree.selection() if select is None else select
        self.refreshing = True
        self.media_tree.delete(*self.media_tree.get_children())
        for sid, item in self.items.items():
            source = item.read()["sources"][sid]
            state = "已有文本" if source.get("transcribed") else ("转写失败" if source.get("error") else "待转写")
            self.media_tree.insert("", "end", iid=sid, values=("☐", item.media_path.name, state))
        selected = [sid for sid in selected if sid in self.items]
        if not selected and self.items:
            selected = [next(iter(self.items))]
        self.media_tree.selection_set(selected)
        self.order_media()
        self.file_count.configure(text=f"{len(self.items)} 个文件")
        self.media_table.update_empty()
        self.refreshing = False
        self.selection_changed()

    def selection_changed(self, event=None):
        if self.refreshing:
            return
        selected = [self.items[sid] for sid in self.media_tree.selection() if sid in self.items]
        self.hits.delete(*self.hits.get_children())
        self.rows = []
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.configure(state="disabled")
        self.preview_box.pack_forget()
        selected_ids = set(self.media_tree.selection())
        for sid in self.media_tree.get_children():
            self.media_tree.set(sid, "选择", "☑" if sid in selected_ids else "☐")
        self.media_tree.heading("选择", text="☑" if self.items and len(selected_ids) == len(self.items) else "☐")
        if not selected:
            self.selected_label.configure(text="点击选择媒体；Ctrl / Shift 可多选。")
            self.text_status.configure(text="暂无文本")
            self.result_label.configure(text="选择媒体后输入关键词")
            self.result_table.update_empty()
            return
        first = selected[0]
        self.selected_label.configure(text=f"已选择 {len(selected)} 个媒体；Ctrl / Shift 可多选。")
        ready = sum(bool(item.read()["sources"][item.id].get("transcribed")) for item in selected)
        self.text_status.configure(text=f"已有文本 {ready} / {len(selected)}")
        for item in selected:
            self.rows.extend(item.rows())
        for i, row in enumerate(self.rows[:500]):
            timing = (timestamp(row["start_ms"])[:8] + " → " + timestamp(row["end_ms"])[:8]) if row["start_ms"] is not None and row["end_ms"] is not None else ""
            self.hits.insert("", "end", iid=str(i), values=(i+1, row["source_name"], timing, row["keyword"], row["text"]))
        searched = all(item.read()["search"]["performed"] for item in selected)
        self.result_label.configure(text=f"{len(self.rows)} 次命中 · {len(selected)} 个文件" if searched else "输入关键词后检索")
        self.result_table.update_empty(searched)

    def show_hit(self, event=None):
        selected = self.hits.selection()
        if not selected or int(selected[0]) >= len(self.rows):
            return
        row = self.rows[int(selected[0])]
        value = (f"{row['source_name']} · 第 {row['cue']} 段 · 本段第 {row['occurrence']} 次命中\n"
                 f"{row['left_context']}【{row['matched_term']}】{row['right_context']}\n"
                 f"原始文本：{row['original_text']}")
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", value)
        self.preview.configure(state="disabled")
        self.preview_box.pack(side="bottom", fill="x", before=self.result_table,
                              pady=(self.p(8), 0))

    def open_selected_folder(self):
        folder = self.selected_items()[0].root
        if os.name == "nt":
            os.startfile(str(folder))
        else:
            messagebox.showinfo("文件夹", str(folder), parent=self.root)

    def open_text(self):
        item = self.selected_items()[0]
        file = item.root / (item.media_path.stem + ".txt")
        if not file.is_file():
            raise ValueError("该媒体还没有 TXT，请转写或使用已有文本。")
        if os.name == "nt":
            os.startfile(str(file))
        else:
            messagebox.showinfo("转写文件", str(file), parent=self.root)

    def close(self):
        if self.busy:
            messagebox.showinfo("任务运行中", "请等待任务结束，或点击停止；当前识别请求返回后会停止。", parent=self.root)
            return
        self.root.destroy()


def main():
    enable_dpi_awareness()
    root = create_root()
    App(root)
    root.mainloop()
