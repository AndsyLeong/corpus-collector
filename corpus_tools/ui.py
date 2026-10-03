"""Small native Tk widgets and vector artwork for the desktop interface."""
import math
import tkinter as tk
from tkinter import ttk

BACKGROUND = "#f5f9ff"
WHITE = "#ffffff"
BLUE = "#0877ff"
NAVY = "#102858"
MUTED = "#8192af"
BORDER = "#dce8f7"
PALE = "#f3f8ff"
FONT = "Microsoft YaHei UI"


def font(size=17, bold=False, scale=1):
    return (FONT, -max(10, round(size * scale)), "bold" if bold else "normal")


def rounded(canvas, x1, y1, x2, y2, radius=10, **options):
    radius = min(2*radius, (x2-x1)/2, (y2-y1)/2)
    return canvas.create_polygon(
        x1+radius, y1, x2-radius, y1, x2, y1, x2, y1+radius,
        x2, y2-radius, x2, y2, x2-radius, y2, x1+radius, y2,
        x1, y2, x1, y2-radius, x1, y1+radius, x1, y1,
        smooth=True, splinesteps=24, **options)


def icon(canvas, name, x, y, size=24, color=NAVY):
    """Draw icons from coordinates so they remain crisp at every screen scale."""
    k = size / 24
    def points(values):
        return [x+v*k if i % 2 == 0 else y+v*k for i, v in enumerate(values)]
    def line(*values, **extra):
        canvas.create_line(*points(values), fill=color, width=max(1.6, 2*k),
                           capstyle="round", joinstyle="round", **extra)
    def polygon(values, fill="", **extra):
        canvas.create_polygon(*points(values), fill=fill, outline=color,
                              width=max(1.6, 2*k), joinstyle="round", **extra)
    def oval(values, fill=""):
        canvas.create_oval(*points(values), fill=fill, outline=color, width=max(1.6, 2*k))
    if name in ("folder", "folder-plus", "folder-original"):
        polygon([2, 19, 2, 5, 9, 5, 12, 8, 21, 8, 21, 19])
        polygon([2, 19, 5, 10, 23, 10, 20, 19], fill=canvas.cget("background"))
        if name != "folder":
            line(13, 11, 13, 17)
            line(10, 14, 16, 14)
    elif name == "play":
        polygon([6, 3, 21, 12, 6, 21], fill=color)
    elif name in ("document", "file"):
        polygon([5, 2, 14, 2, 20, 8, 20, 22, 5, 22])
        line(14, 2, 14, 8, 20, 8)
        line(8, 12, 16, 12)
        line(8, 16, 16, 16)
        line(8, 19, 13, 19)
    elif name == "search":
        oval([2, 2, 17, 17])
        line(15, 15, 23, 23)
    elif name == "plus":
        oval([1, 1, 23, 23], fill=color)
        contrast = BLUE if color == WHITE else WHITE
        canvas.create_line(*points([12, 6, 12, 18]), fill=contrast, width=2*k)
        canvas.create_line(*points([6, 12, 18, 12]), fill=contrast, width=2*k)
    elif name == "check":
        polygon([3, 2, 21, 2, 21, 22, 3, 22])
        line(7, 12, 11, 16, 18, 7)
    elif name == "trash":
        line(3, 6, 21, 6)
        line(9, 6, 9, 3, 15, 3, 15, 6)
        polygon([6, 6, 7, 22, 17, 22, 18, 6])
        line(10, 10, 10, 18)
        line(14, 10, 14, 18)
    elif name == "upload":
        line(12, 16, 12, 2)
        line(7, 7, 12, 2, 17, 7)
        line(3, 14, 3, 22, 21, 22, 21, 14)
    elif name == "stop":
        rounded(canvas, x+4*k, y+4*k, x+20*k, y+20*k, 2*k, fill=color, outline=color)
    elif name == "expand":
        line(4, 15, 4, 21, 10, 21)
        line(4, 21, 10, 15)
        line(14, 3, 20, 3, 20, 9)
        line(14, 9, 20, 3)
    elif name == "gear":
        values = []
        for i in range(32):
            angle = math.pi*i/16
            radius = 11 if i % 4 in (0, 3) else 8.5
            values.extend([12+radius*math.cos(angle), 12+radius*math.sin(angle)])
        polygon(values)
        oval([8, 8, 16, 16])


class Card(tk.Canvas):
    def __init__(self, parent, scale=1, padding=16, **kwargs):
        self.scale = scale
        self.padding = round(padding*scale)
        super().__init__(parent, bg=parent.cget("background"), highlightthickness=0,
                         bd=0, **kwargs)
        self.content = tk.Frame(self, background=WHITE)
        self.window = self.create_window(self.padding, self.padding,
                                         window=self.content, anchor="nw")
        self.bind("<Configure>", self.layout)

    def layout(self, event):
        self.delete("surface")
        rounded(self, 1, 1, event.width-1, event.height-1, 12*self.scale,
                fill=WHITE, outline=BORDER, width=1, tags="surface")
        self.tag_lower("surface")
        self.itemconfigure(self.window, width=max(1, event.width-2*self.padding),
                           height=max(1, event.height-2*self.padding))


class Pill(tk.Canvas):
    def __init__(self, parent, text, scale=1):
        self.text, self.scale = text, scale
        super().__init__(parent, bg=WHITE, width=round(84*scale), height=round(30*scale),
                         highlightthickness=0, bd=0)
        self.bind("<Configure>", lambda _: self.draw())

    def cget(self, key):
        return self.text if key == "text" else super().cget(key)

    def configure(self, cnf=None, **kwargs):
        options = dict(cnf or {}, **kwargs)
        if "text" in options:
            self.text = options.pop("text")
            from tkinter.font import Font
            width = Font(self, font=font(16, scale=self.scale)).measure(self.text) + round(22*self.scale)
            options["width"] = max(round(84*self.scale), width)
        if options:
            super().configure(**options)
        self.draw()

    config = configure

    def draw(self):
        self.delete("all")
        w, h, s = self.winfo_width(), self.winfo_height(), self.scale
        rounded(self, 0, 0, w, h, 10*s, fill="#edf5ff", outline="")
        self.create_text(w/2, h/2, text=self.text, fill="#6d89b7", font=font(16, scale=s))


class Button(tk.Canvas):
    def __init__(self, parent, text, command, symbol="", primary=False,
                 scale=1, width=160, height=50, compact=False):
        self.text, self.command, self.symbol = text, command, symbol
        self.primary, self.scale = primary, scale
        self.disabled = False
        self.hovered = False
        self.focused = False
        self.compact = compact
        super().__init__(parent, width=round(width*scale), height=round(height*scale),
                         bg=parent.cget("background"), bd=0, highlightthickness=0,
                         takefocus=1, cursor="hand2")
        self.bind("<Configure>", lambda _: self.draw())
        self.bind("<Enter>", lambda _: self.hover(True))
        self.bind("<Leave>", lambda _: self.hover(False))
        self.bind("<Button-1>", lambda _: self.invoke())
        self.bind("<Return>", lambda _: self.invoke())
        self.bind("<space>", lambda _: self.invoke())
        self.bind("<FocusIn>", lambda _: self.focus(True))
        self.bind("<FocusOut>", lambda _: self.focus(False))
        self.draw()

    def cget(self, key):
        if key == "text":
            return self.text
        if key == "state":
            return "disabled" if self.disabled else "normal"
        return super().cget(key)

    def configure(self, cnf=None, **kwargs):
        options = dict(cnf or {}, **kwargs)
        if "state" in options:
            self.disabled = options.pop("state") == "disabled"
        if "text" in options:
            self.text = options.pop("text")
        if options:
            super().configure(**options)
        self.draw()

    config = configure

    def hover(self, value):
        self.hovered = value
        self.draw()

    def focus(self, value):
        self.focused = value
        self.draw()

    def invoke(self):
        if not self.disabled:
            self.focus_set()
            return self.command()

    def draw(self):
        self.delete("all")
        width = max(self.winfo_width(), int(super().cget("width")))
        if self.winfo_width() > 1:
            width = self.winfo_width()
        height = self.winfo_height() if self.winfo_height() > 1 else int(super().cget("height"))
        if self.disabled:
            fill, foreground, border = "#edf1f6", "#b0bac9", "#dce4ef"
        elif self.primary:
            fill, foreground, border = ("#0068ea" if self.hovered else BLUE), WHITE, BLUE
        else:
            fill, foreground, border = ("#eaf3ff" if self.hovered else PALE), NAVY, "#c6dafa"
        if self.focused and not self.disabled:
            border = "#4a98ff"
        rounded(self, 1, 1, width-1, height-1, 6*self.scale,
                fill=fill, outline=border, width=1)
        from tkinter.font import Font
        face = font(16 if self.compact else 17, True, self.scale)
        text_width = Font(self, font=face).measure(self.text)
        icon_size = 23*self.scale if self.symbol else 0
        gap = 12*self.scale if self.symbol else 0
        start = (width-text_width-icon_size-gap)/2
        if self.symbol:
            accent = (self.symbol == "folder-plus" or self.text in ("选择文件夹", "检索预览"))
            icon_color = BLUE if accent and not self.primary and not self.disabled else foreground
            icon(self, self.symbol, start, (height-icon_size)/2, icon_size, icon_color)
        self.create_text(start+icon_size+gap, height/2, text=self.text,
                         anchor="w", fill=foreground, font=face)


class Check(tk.Canvas):
    def __init__(self, parent, text, variable, scale=1, width=160):
        self.variable, self.text, self.scale = variable, text, scale
        self.disabled = False
        super().__init__(parent, width=round(width*scale), height=round(32*scale),
                         bg=WHITE, highlightthickness=0, bd=0, cursor="hand2", takefocus=1)
        variable.trace_add("write", lambda *_: self.draw())
        self.bind("<Configure>", lambda _: self.draw())
        self.bind("<Button-1>", lambda _: self.toggle())
        self.bind("<space>", lambda _: self.toggle())
        self.bind("<Return>", lambda _: self.toggle())
        self.draw()

    def toggle(self):
        if not self.disabled:
            self.variable.set(not self.variable.get())

    def configure(self, cnf=None, **kwargs):
        options = dict(cnf or {}, **kwargs)
        if "state" in options:
            self.disabled = options.pop("state") == "disabled"
        if options:
            super().configure(**options)
        self.draw()

    config = configure

    def draw(self):
        self.delete("all")
        s = self.scale
        color = "#b0bac9" if self.disabled else NAVY
        checked = self.variable.get()
        rounded(self, 2*s, 7*s, 21*s, 26*s, 3*s,
                fill=BLUE if checked else WHITE, outline=BLUE if checked else "#cfdaea")
        if checked:
            self.create_line(6*s, 16*s, 10*s, 20*s, 17*s, 12*s,
                             fill=WHITE, width=2*s, capstyle="round")
        self.create_text(34*s, 16*s, text=self.text, anchor="w",
                         font=font(16, scale=s), fill=color)
        if self.focus_get() == self:
            self.create_rectangle(1, 1, self.winfo_width()-1, self.winfo_height()-1,
                                  outline=BORDER, dash=(2, 2))


class EmptyState(tk.Canvas):
    def __init__(self, parent, kind, scale=1, command=None, draggable=False):
        self.kind, self.scale = kind, scale
        self.command, self.draggable = command, draggable
        self.searched = False
        super().__init__(parent, bg=WHITE, bd=0, highlightthickness=0,
                         cursor="hand2" if command else "")
        self.bind("<Configure>", lambda _: self.draw())
        if command:
            self.bind("<Button-1>", lambda _: command())

    def draw(self):
        self.delete("all")
        w, h, s = self.winfo_width(), self.winfo_height(), self.scale
        if w < 5 or h < 5:
            return
        cx, cy = w/2, h/2
        if self.kind == "media":
            rounded(self, 18*s, 28*s, w-18*s, h-26*s, 10*s,
                    fill=WHITE, outline="#c8ddff", width=1, dash=(6, 4))
            cy -= 45*s
            x, y = cx-34*s, cy-42*s
            self.document(x, y, 62*s, 82*s)
            self.create_polygon(x+24*s, y+31*s, x+24*s, y+53*s, x+40*s, y+42*s,
                                fill="#bdcbdc", smooth=True)
            self.create_oval(cx+12*s, cy+8*s, cx+54*s, cy+50*s,
                             fill="#89b8f9", outline=WHITE, width=4*s)
            self.create_line(cx+33*s, cy+20*s, cx+33*s, cy+38*s,
                             fill=WHITE, width=4*s, capstyle="round")
            self.create_line(cx+24*s, cy+29*s, cx+42*s, cy+29*s,
                             fill=WHITE, width=4*s, capstyle="round")
            self.create_text(cx, cy+82*s, text="暂无文件", fill=NAVY, font=font(20, True, s))
            hint = "点击“添加视频 / 音频”或拖拽文件到此处" if self.draggable else "点击“添加视频 / 音频”开始使用"
            self.create_text(cx, cy+116*s, text=hint, fill=MUTED, font=font(16, scale=s))
            self.create_text(cx, cy+140*s, text="支持常见的视频、音频格式",
                             fill=MUTED, font=font(16, scale=s))
        else:
            compact = h < 150*s
            cy -= (26 if compact else 32)*s
            self.document(cx-20*s, cy-24*s, 36*s, 46*s)
            for offset in (12, 19, 26):
                self.create_line(cx-13*s, cy+(-24+offset)*s, cx+2*s,
                                 cy+(-24+offset)*s, fill="#b7c4d7", width=2*s)
            icon(self, "search", cx+6*s, cy+3*s, 25*s, "#a4b4cd")
            title = "没有匹配的结果" if self.searched else "暂无检索结果"
            hint = "可调整关键词或文本来源后重新检索" if self.searched else "请输入关键词并点击“检索预览”或“检索并导出表格”"
            self.create_text(cx, cy+48*s, text=title, fill=NAVY, font=font(16, scale=s))
            self.create_text(cx, cy+75*s, text=hint, fill=MUTED, font=font(15, scale=s))

    def document(self, x, y, w, h):
        rounded(self, x, y, x+w, y+h, w*.13, fill="#e9eef6", outline="")
        self.create_polygon(x+w*.66, y, x+w, y+h*.27, x+w, y+h*.27,
                            x+w*.66, y+h*.27, fill="#c3cddd")


class Table(tk.Frame):
    def __init__(self, parent, columns, widths, scale=1, selectmode="browse", kind="results"):
        super().__init__(parent, bg=WHITE, highlightbackground=BORDER, highlightcolor=BORDER,
                         highlightthickness=1, bd=0)
        self.scale = scale
        self.tree = ttk.Treeview(self, columns=columns, show="headings",
                                style="Corpus.Treeview", selectmode=selectmode, height=4)
        for index, (column, width) in enumerate(zip(columns, widths)):
            self.tree.heading(column, text=column, anchor="center" if index == 0 else "w")
            self.tree.column(column, width=round(width*scale),
                             minwidth=round(40*scale), stretch=index == len(columns)-1)
        self.vertical = ttk.Scrollbar(self, command=self.tree.yview, style="Corpus.Vertical.TScrollbar")
        self.horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview,
                                        style="Corpus.Horizontal.TScrollbar")
        self.tree.configure(yscrollcommand=lambda a, b: self.scroll(self.vertical, a, b, 0, 1),
                            xscrollcommand=lambda a, b: self.scroll(self.horizontal, a, b, 1, 0))
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.empty = EmptyState(self, kind, scale)
        self.tree.bind("<Configure>", lambda _: self.update_empty(), add="+")

    def scroll(self, bar, first, last, row, column):
        bar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            bar.grid_remove()
        else:
            bar.grid(row=row, column=column, sticky="ns" if column else "ew")

    def update_empty(self, searched=False):
        self.empty.searched = searched
        if self.tree.get_children():
            self.empty.place_forget()
        else:
            heading_height = round(42*self.scale)
            self.empty.place(x=0, y=heading_height, relwidth=1,
                             relheight=1, height=-heading_height)
            tk.Misc.lift(self.empty)
            self.empty.draw()


class Progress(tk.Canvas):
    def __init__(self, parent, scale=1):
        self.scale, self.value, self.phase, self.timer = scale, 0, 0, None
        super().__init__(parent, bg=WHITE, width=round(265*scale),
                         height=round(20*scale), bd=0, highlightthickness=0)
        self.bind("<Configure>", lambda _: self.draw())

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        y1, y2 = h/2-5*self.scale, h/2+5*self.scale
        rounded(self, 0, y1, w, y2, 5*self.scale, fill="#e8edf5", outline="")
        if self.timer is not None:
            length = w*.28
            left = (math.sin(self.phase)+1)/2*(w-length)
            rounded(self, left, y1, left+length, y2, 5*self.scale, fill=BLUE, outline="")
        elif self.value:
            rounded(self, 0, y1, w*self.value/100, y2, 5*self.scale, fill=BLUE, outline="")

    def start(self, interval=12):
        self.stop()
        self.tick()

    def tick(self):
        self.phase += .12
        self.timer = self.after(40, self.tick)
        self.draw()

    def stop(self):
        if self.timer is not None:
            self.after_cancel(self.timer)
        self.timer = None
        self.draw()

    def finish(self, success=True):
        self.stop()
        self.value = 100 if success else 0
        self.draw()
