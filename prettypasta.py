#prettypasta is licensed under agpl v3
import os
import subprocess
import sys
import time
import tkinter as tk

# ספריות אופציונליות לשיפור תצוגת תמונות, PDF ועברית
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
        self.images_ref = {}  # מיפוי בין item_id לתמונה כדי לפנות זיכרון כשנמחק
        self.file_items = {}  # מיפוי בין item_id לנתיב קובץ לפתיחה בלחיצה כפולה
        self._last_pump = 0

    def _ensure_init(self):
        if self.root is not None:
            return

        self.root = tk.Tk()
        self.root.title("PrettyPasta")
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
        self.canvas.bind("<Double-Button-1>", self._on_double_click)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_close(self):
        self.root.destroy()
        sys.exit(0)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_mouse_move(self, event):
        real_x = int(self.canvas.canvasx(event.x))
        real_y = int(self.canvas.canvasy(event.y))
        self.mouse_pos = (real_x, real_y)

    def _on_mouse_click(self, event):
        real_x = int(self.canvas.canvasx(event.x))
        real_y = int(self.canvas.canvasy(event.y))
        self.clicked_pos = (real_x, real_y)

    def _on_double_click(self, event):
        real_x = int(self.canvas.canvasx(event.x))
        real_y = int(self.canvas.canvasy(event.y))
        # בודק מהאלמנט העליון ביותר לתחתון אם נלחץ אימוג'י מתוסכל של קובץ
        for item_id in reversed(self.canvas.find_all()):
            if item_id in self.file_items:
                bbox = self.canvas.bbox(item_id)
                if bbox and bbox[0] <= real_x <= bbox[2] and bbox[1] <= real_y <= bbox[3]:
                    _open_external_file(self.file_items[item_id])
                    break

    def _expand_height(self, y):
        if y + 50 > self.max_y:
            self.max_y = y + 50
            self.canvas.config(scrollregion=(0, 0, self.width, self.max_y))

    def _prune_covered(self, left, top, right, bottom, keep_id):
        """מוחק מהזיכרון אלמנטים ישנים שכוסו לחלוטין על ידי האלמנט החדש"""
        for item_id in self.canvas.find_all():
            if item_id == keep_id:
                continue
            bbox = self.canvas.bbox(item_id)
            if bbox:
                ix1, iy1, ix2, iy2 = bbox
                if left <= ix1 and top <= iy1 and right >= ix2 and bottom >= iy2:
                    self.canvas.delete(item_id)
                    self.images_ref.pop(item_id, None)
                    self.file_items.pop(item_id, None)

    def pump(self):
        self._ensure_init()
        now = time.time()
        if now - self._last_pump < 0.01:
            time.sleep(0.01)
        self.root.update_idletasks()
        self.root.update()
        self._last_pump = time.time()


_engine = _CanvasEngine()


def _open_external_file(path: str):
    """פתיחת הקובץ בתוכנת ברירת המחדל של מערכת ההפעלה"""
    if not os.path.exists(path):
        return
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass
def _rgb_to_hex(r, g, b):
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


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


# ================= 5 הפקודות של PrettyPasta =================

def clr(coord: str, r: int, g: int, b: int):
    """1. צביעת פיקסל בודד"""
    _engine._ensure_init()
    x, y = _parse_point(coord)
    _engine._expand_height(y)
    color = _rgb_to_hex(r, g, b)
    item_id = _engine.canvas.create_rectangle(x, y, x + 1, y + 1, outline=color, fill=color)
    _engine._prune_covered(x, y, x + 1, y + 1, item_id)
    _engine.pump()


def square(coord_range: str, r: int, g: int, b: int):
    """2. צביעת מלבן לפי טווח x1,y1-x2,y2"""
    _engine._ensure_init()
    left, top, right, bottom = _parse_range(coord_range)
    _engine._expand_height(bottom)
    color = _rgb_to_hex(r, g, b)
    item_id = _engine.canvas.create_rectangle(left, top, right, bottom, outline=color, fill=color)
    _engine._prune_covered(left, top, right, bottom, item_id)
    _engine.pump()


def file(path: str, coord_range: str):
    """3. הצגת קובץ בתוך מלבן (תמונה, PDF, טקסט או אימוג'י מתוסכל)"""
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
    top_item_id = None

    if HAS_PIL and ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico"}:
        try:
            img = Image.open(path)
            img = img.resize((w, h), Image.Resampling.LANCZOS)
            tk_img = ImageTk.PhotoImage(img)
            top_item_id = _engine.canvas.create_image(left, top, anchor=tk.NW, image=tk_img)
            _engine.images_ref[top_item_id] = tk_img
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
            top_item_id = _engine.canvas.create_image(left, top, anchor=tk.NW, image=tk_img)
            _engine.images_ref[top_item_id] = tk_img
            rendered = True
        except Exception:
            pass

    if not rendered:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read(2000)
            bg_id = _engine.canvas.create_rectangle(left, top, right, bottom, outline="#cccccc", fill="#f9f9f9")
            _engine._prune_covered(left, top, right, bottom, bg_id)
            _engine.canvas.create_text(
                left + 5, top + 5,
                anchor=tk.NW,
                text=_fix_hebrew(content),
                width=max(10, w - 10),
                font=("Consolas", 10)
            )
            rendered = True
        except UnicodeDecodeError:
            bg_id = _engine.canvas.create_rectangle(left, top, right, bottom, outline="#999999", fill="#eeeeee")
            _engine._prune_covered(left, top, right, bottom, bg_id)
            emoji_id = _engine.canvas.create_text(
                left + w // 2, top + h // 2,
                text="😫",
                font=("Segoe UI Emoji", min(w, h) // 2 or 24)
            )
            _engine.file_items[emoji_id] = os.path.abspath(path)

    if top_item_id is not None:
        _engine._prune_covered(left, top, right, bottom, top_item_id)

    _engine.pump()


def text(content: str, font_name: str, size: int, rgb: str, top_edge: str):
    """4. הצגת טקסט בין שתי פינות עליונות x1,y1_x2,y2 עם ירידת שורה אוטומטית"""
    _engine._ensure_init()
    p1, p2 = top_edge.strip().split("_")
    x1, y1 = _parse_point(p1)
    x2, y2 = _parse_point(p2)

    left = min(x1, x2)
    top = min(y1, y2)
    max_width = max(10, abs(x2 - x1))

    r, g, b = map(int, rgb.strip().split(","))
    color = _rgb_to_hex(r, g, b)

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
    """5א. מחזיר True אם סמן העכבר נוגע בפיקסל או במלבן"""
    _engine.pump()
    return _check_hit(target, _engine.mouse_pos)


def onclick(target: str) -> bool:
    """5ב. מחזיר True אם בוצעה לחיצה על הפיקסל או בתוך המלבן"""
    _engine.pump()
    if _engine.clicked_pos is None:
        return False
    hit = _check_hit(target, _engine.clicked_pos)
    if hit:
        _engine.clicked_pos = None
    return hit
