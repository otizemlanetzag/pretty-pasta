import os
import re
import sys
import time
import tkinter as tk

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import fitz  # PyMuPDF לתצוגת PDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

try:
    from bidi.algorithm import get_display
    import arabic_reshaper
    HAS_BIDI = True
except ImportError:
    HAS_BIDI = False


class _CanvasEngine:
    def __init__(self):
        self.root = None
        self.canvas = None
        self.scrollbar = None
        self.max_y = 600
        self.width = 800
        self.mouse_pos = (-1, -1)
        self.clicked_pos = None
        self.images_ref = []
        self.text_boxes = {}
        self.is_closed = False
        self._last_pump = 0

    def _ensure_init(self):
        if self.is_closed:
            sys.exit(0)
        if self.root is not None:
            return

        self.root = tk.Tk()
        self.root.title("PrettyPasta - Because not only soup is beautiful")
        self.root.geometry(f"{self.width}x600")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        frame = tk.Frame(self.root)
        frame.pack(fill=tk.BOTH, expand=True)

        self.scrollbar = tk.Scrollbar(frame, orient=tk.VERTICAL)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas = tk.Canvas(
            frame,
            bg="white",
            yscrollcommand=self.scrollbar.set,
            highlightthickness=0
        )
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.config(command=self.canvas.yview)
        self.canvas.config(scrollregion=(0, 0, self.width, self.max_y))

        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<Button-1>", self._on_mouse_click)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_close(self):
        self.is_closed = True
        try:
            self.root.destroy()
        except Exception:
            pass
        sys.exit(0)

    def _on_mousewheel(self, event):
        if not self.is_closed:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_mouse_move(self, event):
        real_x = int(self.canvas.canvasx(event.x))
        real_y = int(self.canvas.canvasy(event.y))
        self.mouse_pos = (real_x, real_y)

    def _on_mouse_click(self, event):
        real_x = int(self.canvas.canvasx(event.x))
        real_y = int(self.canvas.canvasy(event.y))
        self.clicked_pos = (real_x, real_y)

    def _expand_height(self, y):
        if y + 50 > self.max_y:
            self.max_y = y + 50
            self.canvas.config(scrollregion=(0, 0, self.width, self.max_y))

    def pump(self):
        self._ensure_init()
        now = time.time()
        if now - self._last_pump < 0.01:
            time.sleep(0.01)
        try:
            self.root.update_idletasks()
            self.root.update()
        except tk.TclError:
            self.is_closed = True
            sys.exit(0)
        self._last_pump = time.time()


_engine = _CanvasEngine()


def _rgb_to_hex(r, g, b):
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def _parse_rgb_str(rgb_str):
    r, g, b = map(int, rgb_str.strip().strip("'\"").split(","))
    return _rgb_to_hex(r, g, b)


def _parse_point(coord_str):
    x, y = map(int, coord_str.strip().split(","))
    return x, y


def _parse_range(range_str):
    p1, p2 = range_str.strip().split("-")
    x1, y1 = _parse_point(p1)
    x2, y2 = _parse_point(p2)
    left, right = min(x1, x2), max(x1, x2)
    top, bottom = min(y1, y2), max(y1, y2)
    return left, top, right, bottom


def _fix_hebrew(txt):
    if HAS_BIDI:
        return get_display(arabic_reshaper.reshape(txt))
    return txt


def _get_windows_thumbnail(path, width, height):
    if sys.platform != "win32" or not HAS_PIL:
        return None
    try:
        from win32com.shell import shell
        import win32ui, win32gui

        pidl, _ = shell.SHILCreateFromPath(os.path.abspath(path), 0)
        desktop = shell.SHGetDesktopFolder()
        parent = desktop.BindToObject(pidl[:-1], None, shell.IID_IShellFolder)
        extractor = parent.GetUIObjectOf(0, [pidl[-1]], shell.IID_IExtractImage)
        extractor.GetLocation(260, 0, (width, height), 32, 0)
        hbitmap = extractor.Extract()

        bmp_info = win32gui.GetObject(hbitmap)
        bmp_str = win32ui.CreateBitmapFromHandle(hbitmap).GetBitmapBits(True)
        img = Image.frombuffer(
            "RGB",
            (bmp_info.bmWidth, bmp_info.bmHeight),
            bmp_str, "raw", "BGRX", 0, 1
        )
        win32gui.DeleteObject(hbitmap)
        return img.resize((width, height), Image.Resampling.LANCZOS)
    except Exception:
        return None


# ================= הפקודות של PrettyPasta =================

def clr(coord: str, r: int, g: int, b: int):
    """1. צביעת פיקסל בודד"""
    _engine._ensure_init()
    x, y = _parse_point(coord)
    _engine._expand_height(y)
    color = _rgb_to_hex(r, g, b)
    _engine.canvas.create_rectangle(x, y, x + 1, y + 1, outline=color, fill=color)
    _engine.pump()


def square(coord_range: str, r: int, g: int, b: int):
    """2. צביעת מלבן לפי טווח x1,y1-x2,y2"""
    _engine._ensure_init()
    left, top, right, bottom = _parse_range(coord_range)
    _engine._expand_height(bottom)
    color = _rgb_to_hex(r, g, b)
    _engine.canvas.create_rectangle(left, top, right, bottom, outline=color, fill=color)
    _engine.pump()


def file(path: str, coord_range: str):
    """3. הצגת קובץ בתוך מלבן (תמונה, PDF, OS Thumbnail, טקסט או אימוג'י מתוסכל)"""
    _engine._ensure_init()
    left, top, right, bottom = _parse_range(coord_range)
    w, h = max(1, right - left), max(1, bottom - top)
    _engine._expand_height(bottom)

    if not os.path.exists(path):
        _engine.canvas.create_text(left + w // 2, top + h // 2, text="😫 (File not found)", font=("Arial", 16))
        _engine.pump()
        return

    ext = os.path.splitext(path)[1].lower()
    rendered = False

    if HAS_PIL and ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico"}:
        try:
            img = Image.open(path)
            img = img.resize((w, h), Image.Resampling.LANCZOS)
            tk_img = ImageTk.PhotoImage(img)
            _engine.images_ref.append(tk_img)
            _engine.canvas.create_image(left, top, anchor=tk.NW, image=tk_img)
            rendered = True
        except Exception:
            pass

    if not rendered and HAS_FITZ and ext == ".pdf" and HAS_PIL:
        try:
            doc = fitz.open(path)
            page = doc.load_page(0)
            pix = page.get_pixmap()
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            img = img.resize((w, h), Image.Resampling.LANCZOS)
            tk_img = ImageTk.PhotoImage(img)
            _engine.images_ref.append(tk_img)
            _engine.canvas.create_image(left, top, anchor=tk.NW, image=tk_img)
            rendered = True
        except Exception:
            pass

    if not rendered:
        thumb = _get_windows_thumbnail(path, w, h)
        if thumb is not None:
            tk_img = ImageTk.PhotoImage(thumb)
            _engine.images_ref.append(tk_img)
            _engine.canvas.create_image(left, top, anchor=tk.NW, image=tk_img)
            rendered = True

    if not rendered:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read(2000)
            _engine.canvas.create_rectangle(left, top, right, bottom, outline="#cccccc", fill="#f9f9f9")
            _engine.canvas.create_text(
                left + 5, top + 5,
                anchor=tk.NW,
                text=_fix_hebrew(content),
                width=max(10, w - 10),
                font=("Consolas", 10)
            )
            rendered = True
        except UnicodeDecodeError:
            _engine.canvas.create_rectangle(left, top, right, bottom, outline="#999999", fill="#eeeeee")
            _engine.canvas.create_text(
                left + w // 2, top + h // 2,
                text="😫",
                font=("Segoe UI Emoji", min(w, h) // 2 or 24)
            )

    _engine.pump()


def text(content: str, font_name: str, size: int, rgb: str, top_edge: str):
    """4. הצגת טקסט סטטי בין שתי פינות עליונות x1,y1_x2,y2 עם ירידת שורה אוטומטית"""
    _engine._ensure_init()
    p1, p2 = top_edge.strip().split("_")
    x1, y1 = _parse_point(p1)
    x2, y2 = _parse_point(p2)

    left = min(x1, x2)
    top = min(y1, y2)
    max_width = max(10, abs(x2 - x1))
    color = _parse_rgb_str(rgb)

    if os.path.isfile(font_name):
        actual_font = (os.path.splitext(os.path.basename(font_name))[0], size)
    else:
        actual_font = (font_name, size)

    item_id = _engine.canvas.create_text(
        left, top,
        anchor=tk.NW,
        text=_fix_hebrew(content),
        font=actual_font,
        fill=color,
        width=max_width
    )

    bbox = _engine.canvas.bbox(item_id)
    if bbox:
        _engine._expand_height(bbox[3])

    _engine.pump()


def _apply_rich_styles(widget: tk.Text, styles: list):
    if not styles:
        return
    if isinstance(styles, str):
        styles = [styles]

    pattern = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*\(([^)]+)\)\s*$")
    for idx, rule in enumerate(styles):
        match = pattern.match(rule)
        if not match:
            continue
        start_c, end_c, params_str = match.groups()
        parts = [p.strip() for p in params_str.split(",")]

        s_size = int(parts[0])
        s_font = parts[1].strip("'\"")
        tag_kwargs = {"font": (s_font, s_size)}

        if len(parts) >= 5:
            r, g, b = parts[2].strip("'\""), parts[3].strip("'\""), parts[4].strip("'\"")
            tag_kwargs["foreground"] = _rgb_to_hex(r, g, b)

        tag_name = f"style_{idx}"
        widget.tag_configure(tag_name, **tag_kwargs)
        widget.tag_add(tag_name, f"1.0 + {start_c} chars", f"1.0 + {end_c} chars")


def Text(top_edge: str, nr_of_rows: int = None, font: str = "Arial", size: int = 14, rgb: str = "0,0,0", styles=None) -> str:
    """5. תיבת קלט טקסט עם תמיכה בהגבלת שורות, גובה דינמי ועיצוב מקטעים char-char(size, font, 'r,g,b')"""
    _engine._ensure_init()

    if isinstance(nr_of_rows, (list, str)):
        styles = nr_of_rows
        nr_of_rows = None

    p1, p2 = top_edge.strip().split("_")
    x1, y1 = _parse_point(p1)
    x2, y2 = _parse_point(p2)

    left = min(x1, x2)
    top = min(y1, y2)
    width_px = max(40, abs(x2 - x1))
    default_color = _parse_rgb_str(rgb)

    max_font_size = size
    if styles:
        style_list = [styles] if isinstance(styles, str) else styles
        for rule in style_list:
            m = re.match(r"^\s*\d+\s*-\s*\d+\s*\(\s*(\d+)", rule)
            if m:
                max_font_size = max(max_font_size, int(m.group(1)))

    if top_edge not in _engine.text_boxes:
        initial_height = nr_of_rows if nr_of_rows is not None else 1
        txt_widget = tk.Text(
            _engine.canvas,
            font=(font, max_font_size),
            fg=default_color,
            wrap=tk.WORD,
            height=initial_height,
            bd=1,
            relief=tk.SOLID,
            pady=4
        )
        txt_widget.tag_configure("default_style", font=(font, size), foreground=default_color)
        win_id = _engine.canvas.create_window(left, top, anchor=tk.NW, window=txt_widget, width=width_px)

        def _on_key(event=None):
            if _engine.is_closed:
                return
            txt_widget.tag_add("default_style", "1.0", "end")
            if nr_of_rows is None:
                lines = int(txt_widget.index("end-1c").split(".")[0])
                txt_widget.config(height=max(1, lines))
            if styles:
                _apply_rich_styles(txt_widget, styles)
                for idx in range(len(styles) if isinstance(styles, list) else 1):
                    txt_widget.tag_raise(f"style_{idx}")
            bbox = _engine.canvas.bbox(win_id)
            if bbox:
                _engine._expand_height(bbox[3])

        txt_widget.bind("<KeyRelease>", _on_key)
        _engine.text_boxes[top_edge] = (txt_widget, win_id)
    else:
        txt_widget, win_id = _engine.text_boxes[top_edge]

    if not txt_widget.winfo_exists():
        sys.exit(0)

    txt_widget.tag_add("default_style", "1.0", "end")
    if styles:
        _apply_rich_styles(txt_widget, styles)
        for idx in range(len(styles) if isinstance(styles, list) else 1):
            txt_widget.tag_raise(f"style_{idx}")

    bbox = _engine.canvas.bbox(win_id)
    if bbox:
        _engine._expand_height(bbox[3])

    _engine.pump()
    if _engine.is_closed or not txt_widget.winfo_exists():
        sys.exit(0)
    return txt_widget.get("1.0", "end-1c")


def _check_hit(target: str, point: tuple) -> bool:
    px, py = point
    if px < 0 or py < 0:
        return False
    if "-" in target:
        left, top, right, bottom = _parse_range(target)
        return left <= px <= right and top <= py <= bottom
    else:
        tx, ty = _parse_point(target)
        return px == tx and py == ty


def ontouch(target: str) -> bool:
    """6א. מחזיר True אם סמן העכבר נוגע בפיקסל או במלבן"""
    _engine.pump()
    return _check_hit(target, _engine.mouse_pos)


def onclick(target: str) -> bool:
    """6ב. מחזיר True אם בוצעה לחיצה על הפיקסל או בתוך המלבן"""
    _engine.pump()
    if _engine.clicked_pos is None:
        return False
    hit = _check_hit(target, _engine.clicked_pos)
    if hit:
        _engine.clicked_pos = None
    return hit
