import ctypes
from ctypes import wintypes
import os
import platform
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Union, Tuple

import customtkinter as ctk
import pandas as pd
import tkinter
from tkinter import filedialog, messagebox

from pipeline import (
    RunSummary,
    discover_year_roots,
    execute_pipeline,
    year_metadata_availability,
)


class PipelineInterrupted(Exception):
    """Raised when the user requests to stop the running pipeline."""

try:
    from CTkMessagebox import CTkMessagebox
except Exception:
    CTkMessagebox = None


@dataclass
class _FolderNode:
    """Folder tree under a year (paths relative to the year directory, POSIX)."""

    name: str
    rel: str
    wav_count: int = 0
    children: List["_FolderNode"] = field(default_factory=list)


_MAIN_BUTTON_WIDTH = 98
_SELECT_BUTTON_WIDTH = 112
_FOLDER_BUTTON_WIDTH = 112
_LOG_BUTTON_WIDTH = 96
_SECONDARY_BTN_FG = ("#6A6A6A", "#3B3B3B")
_SECONDARY_BTN_HOVER = ("#5A5A5A", "#4A4A4A")
_SECONDARY_BTN_TEXT = ("#FFFFFF", "#F2F2F2")
_MENU_FG = ("#D9D9D9", "#2B2B2B")
_MENU_TEXT = ("#111111", "#F0F0F0")
_MENU_BUTTON = ("#BFBFBF", "#3A3A3A")
_MENU_HOVER = ("#AFAFAF", "#4A4A4A")
_MAIN_PROGRESS_BAR_HEIGHT = 18
_LOADING_PROGRESS_BAR_HEIGHT = 16
_PROGRESS_PCT_FONT_SIZE = 10

# First public release; bump when shipping new versions.
APP_VERSION = "1.0.0"


class _SolidChevronOptionMenu(ctk.CTkOptionMenu):
    """
    CTkOptionMenu draws the dropdown chevron as a thick rounded line, which antialiases
    to gray pixels. Use a filled polygon instead so the arrow reads as solid.
    """

    @staticmethod
    def _draw_solid_dropdown_arrow(canvas: Any, x_position: float, y_position: float, size: float) -> bool:
        xi, yi, sz = int(round(x_position)), int(round(y_position)), int(round(size))
        half = max(1, sz // 2)
        y_top = yi - max(1, sz // 5)
        y_bot = yi + max(1, sz // 5)
        x_left = xi - half
        x_right = xi + half
        pts = (x_left, y_top, x_right, y_top, xi, y_bot)
        if not canvas.find_withtag("dropdown_arrow"):
            canvas.create_polygon(*pts, tags="dropdown_arrow", outline="", smooth=False)
            canvas.tag_raise("dropdown_arrow")
            return True
        canvas.coords("dropdown_arrow", *pts)
        return False

    def _draw(self, no_color_updates: bool = False) -> None:
        super(ctk.CTkOptionMenu, self)._draw(no_color_updates)

        left_section_width = self._current_width - self._current_height
        requires_recoloring = self._draw_engine.draw_rounded_rect_with_border_vertical_split(
            self._apply_widget_scaling(self._current_width),
            self._apply_widget_scaling(self._current_height),
            self._apply_widget_scaling(self._corner_radius),
            0,
            self._apply_widget_scaling(left_section_width),
        )

        requires_recoloring_2 = self._draw_solid_dropdown_arrow(
            self._canvas,
            self._apply_widget_scaling(self._current_width - (self._current_height / 2)),
            self._apply_widget_scaling(self._current_height / 2),
            self._apply_widget_scaling(self._current_height / 3),
        )

        if no_color_updates is False or requires_recoloring or requires_recoloring_2:
            self._canvas.configure(bg=self._apply_appearance_mode(self._bg_color))

            self._canvas.itemconfig(
                "inner_parts_left",
                outline=self._apply_appearance_mode(self._fg_color),
                fill=self._apply_appearance_mode(self._fg_color),
            )
            self._canvas.itemconfig(
                "inner_parts_right",
                outline=self._apply_appearance_mode(self._button_color),
                fill=self._apply_appearance_mode(self._button_color),
            )

            self._text_label.configure(fg=self._apply_appearance_mode(self._text_color))

            if self._state == tkinter.DISABLED:
                self._text_label.configure(fg=(self._apply_appearance_mode(self._text_color_disabled)))
                self._canvas.itemconfig(
                    "dropdown_arrow",
                    fill=self._apply_appearance_mode(self._text_color_disabled),
                )
            else:
                self._text_label.configure(fg=self._apply_appearance_mode(self._text_color))
                self._canvas.itemconfig(
                    "dropdown_arrow",
                    fill=self._apply_appearance_mode(self._text_color),
                )

            self._text_label.configure(bg=self._apply_appearance_mode(self._fg_color))

        self._canvas.update_idletasks()


def _path_creation_timestamp(path: Path) -> float:
    """Creation time for sorting Outputs (newest first). Uses st_birthtime when available; else st_ctime (creation on Windows)."""
    try:
        st = path.stat()
        birth = getattr(st, "st_birthtime", None)
        if birth is not None:
            return float(birth)
        return float(st.st_ctime)
    except OSError:
        return 0.0


def _build_wav_folder_tree(
    year_path: Path,
    progress_hook: Optional[Callable[[str, int, int], None]] = None,
) -> Tuple[_FolderNode, int]:
    """Directories under *year_path* that contain supported recording files, plus per-folder counts (currently ``.wav``/``.wave``)."""
    year_path = year_path.resolve()
    root = _FolderNode("", "", 0, [])
    if not year_path.is_dir():
        return root, 0
    wav_dirs: Set[Path] = set()
    wav_files: List[Path] = []
    try:
        wav_files = [
            f for f in year_path.rglob("*")
            if f.is_file() and f.suffix.lower() in (".wav", ".wave")
        ]
    except OSError:
        wav_files = []
    total_files = len(wav_files)
    counts_by_rel: Dict[str, int] = {}
    for idx, f in enumerate(wav_files, start=1):
        if progress_hook and (idx % 50 == 0 or idx == total_files):
            progress_hook(
                f"Scanning {year_path.name}: {idx}/{total_files} audio files",
                idx,
                total_files,
            )
        try:
            rel_file = f.resolve().relative_to(year_path)
            parts = rel_file.parts[:-1]
            for depth in range(1, len(parts) + 1):
                rel_dir = Path(*parts[:depth]).as_posix()
                counts_by_rel[rel_dir] = counts_by_rel.get(rel_dir, 0) + 1
        except (OSError, ValueError):
            pass
        try:
            wav_dirs.add(f.parent.resolve())
        except OSError:
            pass
    needed: Set[Path] = set()
    for d in wav_dirs:
        cur = d
        while True:
            needed.add(cur)
            if cur == year_path:
                break
            parent = cur.parent
            if not str(cur).startswith(str(year_path)):
                break
            cur = parent
    tree: Dict[str, dict] = {}
    for p in needed:
        if p == year_path:
            continue
        try:
            rel = p.relative_to(year_path).as_posix()
        except ValueError:
            continue
        cur_d = tree
        for part in rel.split("/"):
            if not part:
                continue
            cur_d = cur_d.setdefault(part, {})  # type: ignore[assignment]

    def to_nodes(d: dict, parent_rel: str) -> List[_FolderNode]:
        nodes: List[_FolderNode] = []
        for name in sorted(d.keys()):
            rel = f"{parent_rel}/{name}" if parent_rel else name
            sub = d[name]
            ch = to_nodes(sub, rel) if sub else []
            nodes.append(_FolderNode(name=name, rel=rel, wav_count=counts_by_rel.get(rel, 0), children=ch))
        return nodes

    root.children = to_nodes(tree, "")
    root.wav_count = total_files
    return root, total_files


def _folder_filter_leaves(checked: List[str]) -> List[str]:
    """
    Keep paths that have no checked strict descendant.

    Auto-checked ancestors (when the user checks a deep folder) must not widen the
    pipeline filter to the whole branch; only the deepest selected paths apply.
    """
    cset = set(checked)
    leaves: List[str] = []
    for p in sorted(cset, key=len):
        if any(q != p and q.startswith(p + "/") for q in cset):
            continue
        leaves.append(p)
    return sorted(leaves, key=len)


def _wav_files_under_year_with_prefixes(
    year_path: Path,
    prefixes: Optional[List[str]],
) -> List[Path]:
    wavs: List[Path] = []
    norm_prefixes: Optional[List[str]]
    if prefixes is None:
        norm_prefixes = None
    else:
        norm_prefixes = [p.strip("/").lower() for p in prefixes if p.strip("/")]
    for p in year_path.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in (".wav", ".wave"):
            continue
        if norm_prefixes is not None:
            try:
                rel = p.relative_to(year_path).as_posix().lower()
            except ValueError:
                continue
            if not any(rel == pr or rel.startswith(pr + "/") for pr in norm_prefixes):
                continue
        wavs.append(p.resolve())
    return wavs


def _build_recordings_scan_workbook(
    *,
    root_folder: str,
    selected_years: List[str],
    subfolder_filters: Optional[Dict[str, List[str]]],
    output_dir: Optional[str],
) -> Tuple[str, int]:
    root = Path(root_folder).resolve()
    pairs = discover_year_roots(root)
    allow = set(selected_years)
    pairs = [(y, p) for y, p in pairs if y in allow]
    rows: List[Dict[str, Any]] = []
    idx = 1
    for year, ypath in pairs:
        prefixes = None
        if subfolder_filters and year in subfolder_filters:
            prefixes = subfolder_filters[year]
        for wav in _wav_files_under_year_with_prefixes(ypath, prefixes):
            rows.append({"Index": idx, "Year": year, "Record Path": str(wav)})
            idx += 1

    out_root = Path(output_dir).resolve() if output_dir else Path.cwd() / "outputs"
    out_root.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    out_path = out_root / f"recordings_files_scan_{ts}.xlsx"
    pd.DataFrame(rows, columns=["Index", "Year", "Record Path"]).to_excel(
        str(out_path), index=False, engine="openpyxl"
    )
    return str(out_path.resolve()), len(rows)


def _application_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


# Distinct ID so Windows taskbar does not merge this app with generic python.exe.
_WINDOWS_APP_ID = "HIT.USVSegmentation.Desktop.1.0"


def register_windows_application_identity() -> None:
    """Call once before creating the root Tk window (``python app.py`` taskbar icon)."""
    if platform.system() != "Windows":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_WINDOWS_APP_ID)
    except (AttributeError, OSError):
        pass


def _windows_set_taskbar_icons(window: Union[ctk.CTk, ctk.CTkToplevel], ico_path: str) -> None:
    """Force taskbar / Alt-Tab to use our .ico (Tk ``iconbitmap`` alone often leaves python.exe)."""
    if platform.system() != "Windows":
        return
    p = Path(ico_path)
    if not p.is_file():
        return
    path_w = str(p.resolve())

    WM_SETICON = 0x0080
    ICON_SMALL = 0
    ICON_BIG = 1
    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x0010
    GA_ROOT = 2

    user32 = ctypes.windll.user32
    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE,
        wintypes.LPCWSTR,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.SendMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.SendMessageW.restype = wintypes.LPARAM

    try:
        child = int(window.winfo_id())
        hwnd = user32.GetAncestor(child, GA_ROOT) or child
    except (tkinter.TclError, ValueError, TypeError, OSError):
        return

    def _load(cx: int, cy: int) -> int:
        h = user32.LoadImageW(None, path_w, IMAGE_ICON, cx, cy, LR_LOADFROMFILE)
        return h or 0

    h_small = _load(16, 16) or _load(0, 0)
    h_big = _load(32, 32) or _load(48, 48) or _load(256, 256) or h_small
    if h_small:
        user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_small)
    if h_big:
        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_big)


def set_window_icon(window: Union[ctk.CTk, ctk.CTkToplevel]) -> None:
    """Title-bar + Windows taskbar icon. Windows: ``.ico`` + WM_SETICON. Else: PNG + ``iconphoto``."""

    def _apply() -> None:
        base = _application_dir()
        ico_path = (base / "assets" / "app_icon.ico").resolve()
        png_path = base / "assets" / "app_icon.png"

        try:
            window.update_idletasks()
        except (tkinter.TclError, AttributeError):
            pass

        if platform.system() == "Windows" and ico_path.is_file():
            ico_s = str(ico_path)
            try:
                window.iconbitmap(default=ico_s)
            except Exception:
                try:
                    window.iconbitmap(ico_s)
                except Exception:
                    pass
            try:
                window.wm_iconbitmap(ico_s)
            except (tkinter.TclError, AttributeError):
                pass
            _windows_set_taskbar_icons(window, ico_s)
            return

        if not png_path.is_file():
            return
        try:
            from PIL import Image, ImageTk

            photo = ImageTk.PhotoImage(Image.open(png_path))
            window.iconphoto(True, photo)
            window._app_icon_photo = photo  # noqa: SLF001
        except Exception:
            pass

    window.after_idle(_apply)
    # CTkToplevel / Windows: title-bar HWND is ready only after the window starts mapping.
    window.after(150, _apply)
    window.after(450, _apply)


def open_path_with_default_app(path: str) -> None:
    p = Path(path)
    if not p.exists():
        messagebox.showerror("Not found", f"The path does not exist:\n{p}")
        return
    try:
        if platform.system() == "Windows":
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.run(["open", str(p)], check=False)
        else:
            subprocess.run(["xdg-open", str(p)], check=False)
    except OSError as exc:
        messagebox.showerror("Open failed", str(exc))


def open_folder_in_explorer(folder: str) -> None:
    p = Path(folder)
    if not p.is_dir():
        messagebox.showerror("Not found", f"Not a folder:\n{p}")
        return
    try:
        if platform.system() == "Windows":
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.run(["open", str(p)], check=False)
        else:
            subprocess.run(["xdg-open", str(p)], check=False)
    except OSError as exc:
        messagebox.showerror("Open failed", str(exc))


class SegmentationApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.title("USV Segmentation")
        self._default_window_width: int = 790
        self._log_panel_width: int = 650
        self.geometry(f"{self._default_window_width}x720")
        self.minsize(790, 620)

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.selected_folder: Optional[str] = None
        self.output_dir: Optional[str] = None
        self.worker_thread: Optional[threading.Thread] = None
        self.ui_queue: "queue.Queue[Dict[str, object]]" = queue.Queue()
        self._year_check_vars: Dict[str, ctk.BooleanVar] = {}
        self._year_folder_paths: Dict[str, Path] = {}
        self._year_folder_check_vars: Dict[str, Dict[str, ctk.BooleanVar]] = {}
        self._manual_metadata_files_by_year: Dict[str, str] = {}
        self._pause_requested = threading.Event()
        self._stop_requested = threading.Event()
        self._is_running = False
        self._cascade_inner: bool = False
        self._years_frame_inner: Optional[ctk.CTkScrollableFrame] = None
        self._year_controls_row: Optional[ctk.CTkFrame] = None
        self._log_visible = False
        self._run_start_perf: Optional[float] = None
        self._last_run_summary: Optional[RunSummary] = None
        self._last_run_elapsed: Optional[float] = None
        self._results_window: Optional[ctk.CTkToplevel] = None
        self._results_body: Optional[ctk.CTkScrollableFrame] = None
        self._outputs_window: Optional[ctk.CTkToplevel] = None
        self._outputs_body: Optional[ctk.CTkScrollableFrame] = None
        self._loading_window: Optional[ctk.CTkToplevel] = None
        self._loading_bar: Optional[ctk.CTkProgressBar] = None
        self._loading_note_label: Optional[ctk.CTkLabel] = None
        self._loading_phase: float = 0.0
        self._run_total_files: int = 0
        self._run_processed_files: int = 0
        self._selected_wav_count_by_year: Dict[str, int] = {}
        self._wav_count_by_year_rel: Dict[str, Dict[str, int]] = {}
        self._queue_poll_after_id: Optional[str] = None
        self._last_log_body: str = ""
        self._elapsed_tick_id: Optional[str] = None
        self._last_pipeline_status_text: str = "Ready"
        self._ui_progress_value: float = 0.0
        self._progress_pct_text_id: Optional[int] = None
        self._folder_tree_expandable: Dict[str, List[Dict[str, Any]]] = {}
        self._folder_tree_panel_host: Dict[str, Any] = {}
        self._folder_tree_year_block: Dict[str, Any] = {}
        self._year_tree_header_toggle: Dict[str, Dict[str, Any]] = {}
        self._results_open_folder_btn: Optional[ctk.CTkButton] = None
        self._outputs_open_folder_btn: Optional[ctk.CTkButton] = None

        set_window_icon(self)
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close_requested)
        self._start_queue_poller()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.container = ctk.CTkFrame(self, corner_radius=14)
        self.container.grid(row=0, column=0, padx=16, pady=16, sticky="nsew")
        self.container.grid_columnconfigure(0, weight=1)
        self.container.grid_columnconfigure(1, weight=0)

        row = 0

        # Top bar: title (left), dark mode (right)
        header = ctk.CTkFrame(self.container, fg_color="transparent")
        header.grid(row=row, column=0, padx=16, pady=(16, 8), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        row += 1

        self.title_label = ctk.CTkLabel(
            header,
            text="USV Segmentation",
            font=ctk.CTkFont(size=22, weight="bold"),
        )
        self.title_label.grid(row=0, column=0, padx=(0, 12), sticky="w")

        self.mode_switch = ctk.CTkSwitch(
            header,
            text="Dark Mode",
            command=self._toggle_dark_mode,
            width=52,
        )
        self.mode_switch.grid(row=0, column=1, sticky="e")
        if ctk.get_appearance_mode().lower() == "dark":
            self.mode_switch.select()

        self.subtitle_label = ctk.CTkLabel(
            self.container,
            text=(
                "Select the folder that holds your recordings:\n"
                "A single year folder, or a parent folder with one subfolder per year "
                "(for example 2015, 2016)."
            ),
            text_color=("gray35", "gray70"),
            font=ctk.CTkFont(size=13),
            justify="left",
        )
        self.subtitle_label.grid(row=row, column=0, padx=16, pady=(0, 8), sticky="w")
        row += 1

        self.folder_row = ctk.CTkFrame(self.container, fg_color="transparent")
        self.folder_row.grid(row=row, column=0, padx=16, pady=(0, 6), sticky="ew")
        self.folder_row.grid_columnconfigure(1, weight=1)
        row += 1

        ctk.CTkButton(
            self.folder_row,
            text="Data Folder",
            width=_FOLDER_BUTTON_WIDTH,
            command=self._on_select_folder,
        ).grid(row=0, column=0, padx=(0, 10), pady=4, sticky="w")

        self.folder_label = ctk.CTkLabel(
            self.folder_row,
            text="",
            anchor="w",
            corner_radius=8,
            fg_color=("gray90", "gray20"),
            padx=10,
            pady=8,
        )
        self.folder_label.grid(row=0, column=1, sticky="ew")

        self.out_row = ctk.CTkFrame(self.container, fg_color="transparent")
        self.out_row.grid(row=row, column=0, padx=16, pady=(0, 6), sticky="ew")
        self.out_row.grid_columnconfigure(1, weight=1)
        row += 1

        ctk.CTkButton(
            self.out_row,
            text="Output Folder",
            width=_FOLDER_BUTTON_WIDTH,
            command=self._on_select_output,
        ).grid(row=0, column=0, padx=(0, 10), pady=4, sticky="w")

        self.output_label = ctk.CTkLabel(
            self.out_row,
            text="",
            anchor="w",
            corner_radius=8,
            fg_color=("gray90", "gray20"),
            padx=10,
            pady=8,
        )
        self.output_label.grid(row=0, column=1, sticky="ew")

        year_controls_row = ctk.CTkFrame(self.container, fg_color="transparent")
        self._year_controls_row = year_controls_row
        year_controls_row.grid(row=row, column=0, padx=16, pady=(0, 6), sticky="w")
        row += 1

        self.select_all_btn = ctk.CTkButton(
            year_controls_row,
            text="Select All",
            width=_SELECT_BUTTON_WIDTH,
            command=self._select_all_years,
        )
        self.select_all_btn.grid(row=0, column=0, padx=(0, 8))
        self.select_all_btn.configure(
            fg_color=_SECONDARY_BTN_FG,
            hover_color=_SECONDARY_BTN_HOVER,
            text_color=_SECONDARY_BTN_TEXT,
        )
        self.deselect_all_btn = ctk.CTkButton(
            year_controls_row,
            text="Deselect All",
            width=_SELECT_BUTTON_WIDTH,
            command=self._clear_years,
        )
        self.deselect_all_btn.grid(row=0, column=1, padx=(0, 16))
        self.deselect_all_btn.configure(
            fg_color=_SECONDARY_BTN_FG,
            hover_color=_SECONDARY_BTN_HOVER,
            text_color=_SECONDARY_BTN_TEXT,
        )
        self.segmentation_mode_var = ctk.StringVar(value="Segmentation + Classification")
        self.segmentation_mode_menu = _SolidChevronOptionMenu(
            year_controls_row,
            values=["Segmentation + Classification", "Segmentation"],
            variable=self.segmentation_mode_var,
            width=220,
        )
        self.segmentation_mode_menu.grid(row=0, column=2, padx=(0, 14), sticky="w")
        self.segmentation_mode_menu.configure(
            fg_color=_MENU_FG,
            text_color=_MENU_TEXT,
            button_color=_MENU_BUTTON,
            button_hover_color=_MENU_HOVER,
        )
        self.recordings_scan_mode_var = ctk.StringVar(value="Without Recordings Files Scan")
        self.recordings_scan_mode_menu = _SolidChevronOptionMenu(
            year_controls_row,
            values=[
                "Without Recordings Files Scan",
                "With Recordings Files Scan",
                "Only Recordings Files Scan",
            ],
            variable=self.recordings_scan_mode_var,
            width=240,
            command=self._on_recordings_scan_mode_change,
        )
        self.recordings_scan_mode_menu.grid(row=0, column=3, sticky="w")
        self.recordings_scan_mode_menu.configure(
            fg_color=_MENU_FG,
            text_color=_MENU_TEXT,
            button_color=_MENU_BUTTON,
            button_hover_color=_MENU_HOVER,
        )

        self._years_frame_inner = ctk.CTkScrollableFrame(self.container, height=260)
        years_row = row
        self._years_frame_inner.grid(row=years_row, column=0, padx=16, pady=(0, 6), sticky="nsew")
        row += 1
        self.container.grid_rowconfigure(years_row, weight=1)
        y_canvas = getattr(self._years_frame_inner, "_parent_canvas", None)
        if y_canvas is not None:
            y_canvas.bind("<Button-3>", self._on_years_panel_dead_space_context_menu, add="+")
            if platform.system() == "Darwin":
                y_canvas.bind("<Control-Button-1>", self._on_years_panel_dead_space_context_menu, add="+")
        self._years_frame_inner.bind("<Button-3>", self._on_years_panel_dead_space_context_menu, add="+")
        if platform.system() == "Darwin":
            self._years_frame_inner.bind(
                "<Control-Button-1>", self._on_years_panel_dead_space_context_menu, add="+"
            )

        self.controls_row = ctk.CTkFrame(self.container, fg_color="transparent")
        self.controls_row.grid(row=row, column=0, padx=16, pady=(6, 8), sticky="ew")
        self.controls_row.grid_columnconfigure(4, weight=1)
        row += 1

        self.run_btn = ctk.CTkButton(
            self.controls_row,
            text="Run",
            state="disabled",
            width=_MAIN_BUTTON_WIDTH,
            command=self._on_run_pipeline,
        )
        self.run_btn.grid(row=0, column=0, sticky="w")

        self.stop_btn = ctk.CTkButton(
            self.controls_row,
            text="Stop",
            width=_MAIN_BUTTON_WIDTH,
            state="disabled",
            command=self._on_stop_pipeline,
        )
        self.stop_btn.grid(row=0, column=1, padx=(12, 0), sticky="w")

        self.results_btn = ctk.CTkButton(
            self.controls_row,
            text="Results",
            width=_MAIN_BUTTON_WIDTH,
            state="disabled",
            command=self._on_view_results,
        )
        self.results_btn.grid(row=0, column=2, padx=(12, 0), sticky="w")

        self.outputs_browser_btn = ctk.CTkButton(
            self.controls_row,
            text="Outputs",
            width=_MAIN_BUTTON_WIDTH,
            command=self._on_view_outputs_folder,
        )
        self.outputs_browser_btn.grid(row=0, column=3, padx=(12, 0), sticky="w")
        self.outputs_browser_btn.configure(
            fg_color=_SECONDARY_BTN_FG,
            hover_color=_SECONDARY_BTN_HOVER,
            text_color=_SECONDARY_BTN_TEXT,
        )

        self._log_toggle_btn = ctk.CTkButton(
            self.controls_row,
            text="Show Logs",
            width=_LOG_BUTTON_WIDTH,
            command=self._toggle_log_panel,
        )
        self._log_toggle_btn.grid(row=0, column=5, sticky="e")
        self._log_toggle_btn.configure(
            fg_color=_SECONDARY_BTN_FG,
            hover_color=_SECONDARY_BTN_HOVER,
            text_color=_SECONDARY_BTN_TEXT,
        )

        self._progress_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self._progress_frame.grid(row=row, column=0, padx=16, pady=(4, 4), sticky="ew")
        self._progress_frame.grid_columnconfigure(0, weight=1)
        self.progress = ctk.CTkProgressBar(
            self._progress_frame,
            height=_MAIN_PROGRESS_BAR_HEIGHT,
        )
        self.progress.grid(row=0, column=0, sticky="ew")
        canvas = getattr(self.progress, "_canvas", None)
        if canvas is not None:
            self._progress_pct_text_id = canvas.create_text(
                0,
                0,
                text="0%",
                fill="white",
                font=("Segoe UI", _PROGRESS_PCT_FONT_SIZE),
            )
            canvas.bind("<Configure>", lambda _e: self._position_progress_pct_text())
            self.after_idle(self._position_progress_pct_text)
        row += 1
        self._update_progress_bar_ui(0.0)

        self.status_label = ctk.CTkLabel(
            self.container,
            text="Ready",
            anchor="w",
            text_color=("gray35", "gray70"),
        )
        self.status_label.grid(row=row, column=0, padx=16, pady=(0, 6), sticky="ew")
        row += 1

        self.log_panel = ctk.CTkFrame(self.container, corner_radius=12)
        self.log_panel.grid(row=0, column=1, rowspan=row + 1, padx=(0, 16), pady=16, sticky="nsew")
        self.log_panel.grid_columnconfigure(0, weight=1)
        self.log_panel.grid_rowconfigure(0, weight=1)
        self.log_box = ctk.CTkTextbox(self.log_panel, height=180, wrap="word")
        self.log_box.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.log_box.insert("end", "Ready.\n")
        self._wire_log_text_widget()
        self.log_panel.grid_remove()

        # Credits sit in the bottom window margin only (same grid layout as before this line
        # existed). ``place`` avoids an extra grid row so the window height is unchanged.
        # Match the CTk window surround (light gray outside the rounded card), not the card itself.
        self._footer_bar = ctk.CTkFrame(
            self,
            corner_radius=0,
            width=self._default_window_width,
            height=16,
            fg_color=self.cget("fg_color"),
        )
        self._footer_label = ctk.CTkLabel(
            self._footer_bar,
            text=(
                f"Version {APP_VERSION}  ·  "
                "Developed by Chen Aharon & Aviel Bitton"
            ),
            anchor="center",
            font=ctk.CTkFont(size=9),
            text_color=("gray45", "gray65"),
        )
        self._footer_label.place(relx=0.5, rely=0.5, anchor="center")
        # Match bottom grid ``pady`` (16) so the strip sits only in the margin, not over the card.
        # Keep footer aligned to the main pane width even when the logs panel expands the window.
        self._footer_bar.place(x=0, rely=1.0, anchor="sw")
        self._footer_bar.lift()

    def _on_recordings_scan_mode_change(self, _choice: str) -> None:
        mode = self.recordings_scan_mode_var.get()
        if mode == "Only Recordings Files Scan":
            self.segmentation_mode_menu.configure(state="disabled")
        else:
            self.segmentation_mode_menu.configure(state="normal")

    def _toggle_log_panel(self) -> None:
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.log_panel.grid()
            self._log_toggle_btn.configure(text="Hide Logs")
            self.log_box.see("end")
            self.container.grid_columnconfigure(0, weight=0, minsize=self._default_window_width - 32)
            self.container.grid_columnconfigure(1, weight=1)
            self.geometry(f"{self._default_window_width + self._log_panel_width}x720")
        else:
            self.log_panel.grid_remove()
            self._log_toggle_btn.configure(text="Show Logs")
            self.container.grid_columnconfigure(0, weight=1, minsize=0)
            self.container.grid_columnconfigure(1, weight=0)
            self.geometry(f"{self._default_window_width}x720")

    def _wire_log_text_widget(self) -> None:
        inner = getattr(self.log_box, "_textbox", None)
        if inner is None:
            self.log_box.bind("<Control-c>", self._on_copy_log_shortcut)
            self.log_box.bind("<Control-C>", self._on_copy_log_shortcut)
            self.log_box.bind("<Control-KeyPress-c>", self._on_copy_log_shortcut)
            self.log_box.bind("<Control-KeyPress-C>", self._on_copy_log_shortcut)
            return
        try:
            inner.configure(exportselection=True)
        except tkinter.TclError:
            pass
        inner.bind("<Control-c>", self._on_copy_log_shortcut)
        inner.bind("<Control-C>", self._on_copy_log_shortcut)
        inner.bind("<Control-KeyPress-c>", self._on_copy_log_shortcut)
        inner.bind("<Control-KeyPress-C>", self._on_copy_log_shortcut)
        inner.bind("<Button-3>", self._on_log_right_click)
        self.log_box.bind("<Control-c>", self._on_copy_log_shortcut)
        self.log_box.bind("<Control-C>", self._on_copy_log_shortcut)
        self.log_box.bind("<Control-KeyPress-c>", self._on_copy_log_shortcut)
        self.log_box.bind("<Control-KeyPress-C>", self._on_copy_log_shortcut)

    def _copy_log_selection(self) -> None:
        try:
            sel = self.log_box.get("sel.first", "sel.last")
        except tkinter.TclError:
            sel = ""
        self.clipboard_clear()
        self.clipboard_append(sel if sel else self.log_box.get("1.0", "end-1c"))

    def _on_copy_log_shortcut(self, _event: Any = None) -> str:
        self._copy_log_selection()
        return "break"

    def _on_log_right_click(self, event: Any) -> None:
        menu = tkinter.Menu(self, tearoff=0)
        menu.add_command(label="Copy", command=self._copy_log_selection)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    @staticmethod
    def _format_elapsed_duration(seconds: float) -> str:
        total = max(0, int(round(seconds)))
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h {m}m {s}s"
        if m:
            return f"{m}m {s}s"
        return f"{s}s"

    def _position_progress_pct_text(self) -> None:
        canvas = getattr(self.progress, "_canvas", None)
        if canvas is None or self._progress_pct_text_id is None:
            return
        w = max(0, int(canvas.winfo_width()))
        h = max(0, int(canvas.winfo_height()))
        # Optical centering: canvas text baseline appears slightly low at this height.
        canvas.coords(self._progress_pct_text_id, w / 2, (h / 2) - 1)
        canvas.tag_raise(self._progress_pct_text_id)

    def _sync_progress_pct_label(self) -> None:
        p = max(0.0, min(1.0, float(self._ui_progress_value)))
        canvas = getattr(self.progress, "_canvas", None)
        if canvas is None:
            return
        if self._progress_pct_text_id is None:
            self._progress_pct_text_id = canvas.create_text(
                0,
                0,
                text="",
                fill="white",
                font=("Segoe UI", _PROGRESS_PCT_FONT_SIZE),
            )
        self._position_progress_pct_text()
        canvas.itemconfigure(
            self._progress_pct_text_id,
            text=f"{int(round(p * 100))}%",
            fill="white",
        )
        canvas.tag_raise(self._progress_pct_text_id)

    def _update_progress_bar_ui(self, p: float) -> None:
        self._ui_progress_value = max(0.0, min(1.0, float(p)))
        self.progress.set(self._ui_progress_value)
        self._sync_progress_pct_label()

    def _refresh_running_status_bar(self) -> None:
        if not self._is_running or self._run_start_perf is None:
            return
        elapsed = max(0.0, time.perf_counter() - self._run_start_perf)
        self._set_status(f"Elapsed Time: {self._format_elapsed_duration(elapsed)}")

    @staticmethod
    def _display_progress_from_pipeline(raw_progress: float) -> float:
        """
        Convert pipeline float progress to 1%-step UI progress.

        While running, keep the bar in whole-percent steps for smoother UX.
        """
        p = max(0.0, min(1.0, float(raw_progress)))
        return round(p * 100.0) / 100.0

    def _start_elapsed_tick(self) -> None:
        self._stop_elapsed_tick()
        self._refresh_running_status_bar()

        def _tick() -> None:
            self._elapsed_tick_id = None
            if not self._is_running:
                return
            self._refresh_running_status_bar()
            self._elapsed_tick_id = self.after(250, _tick)

        self._elapsed_tick_id = self.after(250, _tick)

    def _stop_elapsed_tick(self) -> None:
        if self._elapsed_tick_id is not None:
            try:
                self.after_cancel(self._elapsed_tick_id)
            except tkinter.TclError:
                pass
        self._elapsed_tick_id = None

    def _on_view_results(self) -> None:
        if self._last_run_summary is None:
            self._show_message("Results", "Run the pipeline successfully first.", "info")
            return
        self._open_or_focus_results_window()

    def _close_results_window(self) -> None:
        if self._results_window is not None:
            try:
                self._results_window.destroy()
            except tkinter.TclError:
                pass
        self._results_window = None
        self._results_body = None
        self._results_open_folder_btn = None

    def _open_or_focus_results_window(self) -> None:
        if self._last_run_summary is None:
            return
        if self._results_window is not None:
            try:
                if self._results_window.winfo_exists():
                    self._populate_results_body(
                        self._results_body,
                        self._last_run_summary,
                        elapsed_seconds=self._last_run_elapsed,
                    )
                    self._results_window.lift()
                    return
            except tkinter.TclError:
                pass
            self._results_window = None
            self._results_body = None
            self._results_open_folder_btn = None

        win = ctk.CTkToplevel(self)
        win.title("Results")
        win.geometry("540x480")
        win.minsize(400, 320)
        win.transient(self)
        set_window_icon(win)

        self._results_window = win
        win.protocol("WM_DELETE_WINDOW", self._close_results_window)

        scroll = ctk.CTkScrollableFrame(win, height=320)
        scroll.pack(fill="both", expand=True, padx=12, pady=(14, 8))
        self._results_body = scroll

        bottom = ctk.CTkFrame(win, fg_color="transparent")
        bottom.pack(fill="x", padx=16, pady=(0, 14))
        self._results_open_folder_btn = ctk.CTkButton(
            bottom,
            text="Open Output Folder",
            anchor="center",
            command=lambda: None,
        )
        self._results_open_folder_btn.pack(fill="x", pady=(0, 10))

        close_btn = ctk.CTkButton(
            bottom, text="Close", width=120, command=self._close_results_window
        )
        close_btn.pack()
        close_btn.configure(
            fg_color=_SECONDARY_BTN_FG,
            hover_color=_SECONDARY_BTN_HOVER,
            text_color=_SECONDARY_BTN_TEXT,
        )

        self._populate_results_body(
            scroll,
            self._last_run_summary,
            elapsed_seconds=self._last_run_elapsed,
        )

    def _resolve_outputs_dir(self) -> Path:
        if self.output_dir and str(self.output_dir).strip():
            return Path(self.output_dir).resolve()
        return (Path.cwd() / "outputs").resolve()

    @staticmethod
    def _add_output_file_link_row(
        scroll: ctk.CTkScrollableFrame,
        file_path: str,
        *,
        padx: int,
        text_color: Optional[Union[str, Tuple[str, str]]] = None,
    ) -> None:
        row_f = ctk.CTkFrame(scroll, fg_color="transparent")
        row_f.pack(fill="x", pady=3, padx=padx)
        name = Path(file_path).name
        lbl = ctk.CTkLabel(
            row_f,
            text=name,
            anchor="w",
            cursor="hand2",
            font=ctk.CTkFont(size=13, underline=True),
            text_color=text_color or ("#1a5fb4", "#62a0ea"),
        )
        lbl.pack(side="left", fill="x", expand=True)

        def _open(_event: Any = None) -> None:
            open_path_with_default_app(file_path)

        lbl.bind("<Button-1>", _open)

    def _populate_results_body(
        self,
        scroll: Optional[ctk.CTkScrollableFrame],
        summary: RunSummary,
        *,
        elapsed_seconds: Optional[float] = None,
    ) -> None:
        del elapsed_seconds  # kept for call-site compatibility; no longer shown in UI
        if scroll is None:
            return
        for w in scroll.winfo_children():
            w.destroy()

        padx = 4
        out_dir = getattr(summary, "output_directory", None) or ""
        files: List[str] = list(getattr(summary, "output_files", []) or [])
        if not out_dir and files:
            out_dir = str(Path(files[0]).parent.resolve())

        if self._results_open_folder_btn is not None:
            if out_dir:
                self._results_open_folder_btn.configure(
                    state="normal",
                    command=lambda d=out_dir: open_folder_in_explorer(d),
                )
            else:
                self._results_open_folder_btn.configure(state="disabled", command=lambda: None)

        for fp in files:
            self._add_output_file_link_row(scroll, fp, padx=padx)

    def _close_outputs_browser_window(self) -> None:
        if self._outputs_window is not None:
            try:
                self._outputs_window.destroy()
            except tkinter.TclError:
                pass
        self._outputs_window = None
        self._outputs_body = None
        self._outputs_open_folder_btn = None

    def _populate_outputs_browser_body(self, scroll: Optional[ctk.CTkScrollableFrame]) -> None:
        if scroll is None:
            return
        for w in scroll.winfo_children():
            w.destroy()
        padx = 4
        out = self._resolve_outputs_dir()
        if self._outputs_open_folder_btn is not None:
            self._outputs_open_folder_btn.configure(
                state="normal",
                command=lambda p=str(out): open_folder_in_explorer(p),
            )
        if not out.is_dir():
            ctk.CTkLabel(scroll, text="Folder does not exist yet.", anchor="w").pack(
                anchor="w", padx=padx, pady=4
            )
            return
        entries: List[Path] = []
        try:
            for ch in out.iterdir():
                if ch.name.startswith("."):
                    continue
                entries.append(ch)
        except OSError as exc:
            ctk.CTkLabel(scroll, text=f"Could not read folder: {exc}", anchor="w").pack(
                anchor="w", padx=padx, pady=4
            )
            return
        entries.sort(key=lambda p: (-_path_creation_timestamp(p), p.name.lower()))
        if not entries:
            ctk.CTkLabel(scroll, text="(empty folder)", anchor="w").pack(
                anchor="w", padx=padx, pady=4
            )
            return
        for p in entries:
            if p.is_file():
                self._add_output_file_link_row(scroll, str(p.resolve()), padx=padx)
            else:
                row_f = ctk.CTkFrame(scroll, fg_color="transparent")
                row_f.pack(fill="x", pady=2, padx=padx)
                ctk.CTkLabel(
                    row_f,
                    text=f"{p.name}/",
                    anchor="w",
                    font=ctk.CTkFont(size=13),
                    text_color=("gray30", "gray70"),
                ).pack(side="left", fill="x", expand=True)

    def _open_or_focus_outputs_browser_window(self) -> None:
        if self._outputs_window is not None:
            try:
                if self._outputs_window.winfo_exists():
                    self._populate_outputs_browser_body(self._outputs_body)
                    self._outputs_window.lift()
                    return
            except tkinter.TclError:
                pass
            self._outputs_window = None
            self._outputs_body = None
            self._outputs_open_folder_btn = None

        win = ctk.CTkToplevel(self)
        win.title("Outputs")
        win.geometry("520x440")
        win.minsize(400, 320)
        win.transient(self)
        set_window_icon(win)
        self._outputs_window = win
        win.protocol("WM_DELETE_WINDOW", self._close_outputs_browser_window)

        scroll = ctk.CTkScrollableFrame(win, height=320)
        scroll.pack(fill="both", expand=True, padx=12, pady=(14, 8))
        self._outputs_body = scroll

        bottom = ctk.CTkFrame(win, fg_color="transparent")
        bottom.pack(fill="x", padx=16, pady=(0, 14))
        self._outputs_open_folder_btn = ctk.CTkButton(
            bottom,
            text="Open Output Folder",
            anchor="center",
            command=lambda: open_folder_in_explorer(str(self._resolve_outputs_dir())),
        )
        self._outputs_open_folder_btn.pack(fill="x", pady=(0, 10))

        close_btn = ctk.CTkButton(
            bottom, text="Close", width=120, command=self._close_outputs_browser_window
        )
        close_btn.pack()
        close_btn.configure(
            fg_color=_SECONDARY_BTN_FG,
            hover_color=_SECONDARY_BTN_HOVER,
            text_color=_SECONDARY_BTN_TEXT,
        )

        self._populate_outputs_browser_body(scroll)

    def _on_view_outputs_folder(self) -> None:
        self._open_or_focus_outputs_browser_window()

    def _cascade_tree_check(self, year: str, rel: str, var: ctk.BooleanVar) -> None:
        """Keep descendants synced and recompute parent/year selection from children."""
        if self._cascade_inner:
            return
        self._cascade_inner = True
        try:
            val = var.get()
            d = self._year_folder_check_vars.get(year, {})
            for k, v in d.items():
                if k.startswith(rel + "/"):
                    v.set(val)
            parts = [p for p in rel.split("/") if p]
            for i in range(len(parts), 0, -1):
                parent = "/".join(parts[:i])
                parent_var = d.get(parent)
                if parent_var is None:
                    continue
                direct_children = [
                    k
                    for k in d.keys()
                    if k.startswith(parent + "/") and "/" not in k[len(parent) + 1 :]
                ]
                if direct_children:
                    parent_var.set(any(d[ch].get() for ch in direct_children))
            yv = self._year_check_vars.get(year)
            if yv is not None:
                yv.set(any(vv.get() for vv in d.values()) if d else yv.get())
        finally:
            self._cascade_inner = False

    def _on_year_folder_cascade(self, year_str: str) -> None:
        """Toggling the year checkbox checks or unchecks all folder rows under that year."""
        if self._cascade_inner:
            return
        var = self._year_check_vars.get(year_str)
        if var is None:
            return
        val = var.get()
        self._cascade_inner = True
        try:
            for fv in self._year_folder_check_vars.get(year_str, {}).values():
                fv.set(val)
        finally:
            self._cascade_inner = False

    @staticmethod
    def _tk_widget_same(a: Any, b: Any) -> bool:
        if a is None or b is None:
            return False
        try:
            return int(a.winfo_id()) == int(b.winfo_id())
        except (tkinter.TclError, AttributeError, TypeError):
            return a is b

    def _widget_is_descendant_of(self, leaf: Any, ancestor: Any) -> bool:
        if leaf is None or ancestor is None:
            return False
        try:
            aid = int(ancestor.winfo_id())
        except (tkinter.TclError, AttributeError, TypeError):
            return False
        w: Any = leaf
        for _ in range(120):
            if w is None:
                return False
            try:
                if int(w.winfo_id()) == aid:
                    return True
            except (tkinter.TclError, AttributeError, TypeError):
                pass
            w = getattr(w, "master", None)
        return False

    def _year_block_at_global_xy(self, x_root: int, y_root: int) -> Optional[Tuple[str, Any, Any]]:
        """Pick which year row block contains the screen point (for scroll-area background clicks)."""
        for y, yb in self._folder_tree_year_block.items():
            try:
                ex = int(yb.winfo_rootx())
                ey = int(yb.winfo_rooty())
                ew = int(yb.winfo_width())
                eh = int(yb.winfo_height())
            except (tkinter.TclError, ValueError, TypeError):
                continue
            if ex <= x_root < ex + max(1, ew) and ey <= y_root < ey + max(1, eh):
                th = self._folder_tree_panel_host.get(y)
                if th is not None:
                    return y, yb, th
        return None

    def _on_years_panel_dead_space_context_menu(self, event: Any) -> None:
        hit = self._year_block_at_global_xy(int(event.x_root), int(event.y_root))
        if hit is None:
            return
        y, yb, th = hit
        w: Any = event.widget
        if w is not None and self._widget_is_descendant_of(w, yb):
            return
        self._show_folder_tree_context_menu(event, y, tree_host=th, year_block=yb)

    def _bind_folder_tree_context_menu_recursive(self, root_widget: Any, year: str) -> None:
        """
        CustomTkinter often only delivers mouse events to inner tk widgets. Walk the whole
        subtree and bind right-click on each descendant so the context menu works on labels,
        checkboxes, and frames.
        """
        panel = self._folder_tree_panel_host.get(year, root_widget)
        yb = self._folder_tree_year_block.get(year, root_widget)

        def handler(event: Any, _y: str = year, _panel: Any = panel, _yb: Any = yb) -> None:
            self._show_folder_tree_context_menu(event, _y, tree_host=_panel, year_block=_yb)

        seen: Set[int] = set()

        def visit(w: Any) -> None:
            if w is None:
                return
            wid = id(w)
            if wid in seen:
                return
            seen.add(wid)
            try:
                w.bind("<Button-3>", handler)
            except (tkinter.TclError, AttributeError):
                pass
            if platform.system() == "Darwin":
                try:
                    w.bind("<Control-Button-1>", handler)
                except (tkinter.TclError, AttributeError):
                    pass
            try:
                for ch in w.winfo_children():
                    visit(ch)
            except tkinter.TclError:
                pass

        visit(root_widget)

    @staticmethod
    def _folder_tree_rel_under_prefix(rel: str, prefix: Optional[str]) -> bool:
        """True if *rel* is *prefix* or a descendant path under *prefix* (POSIX rel segments)."""
        if prefix is None:
            return True
        if rel == prefix:
            return True
        return rel.startswith(prefix + "/")

    def _folder_tree_row_rel_from_event(
        self, event: Any, year: str, tree_host: Any, year_block: Any
    ) -> Optional[str]:
        """
        Walk from the event widget toward the root. If we hit a folder row marked with
        _seg_tree_row_rel before the tree panel / year block boundary, return that rel.
        If we reach *tree_host* first → whole-year tree scope (empty tree padding).
        If we reach *year_block* first (e.g. year header row) → whole-year scope.
        """
        w: Any = event.widget
        for _ in range(80):
            if w is None:
                return None
            if self._tk_widget_same(w, year_block):
                return None
            rel = getattr(w, "_seg_tree_row_rel", None)
            row_yr = getattr(w, "_seg_tree_row_year", None)
            if rel is not None and (row_yr is None or row_yr == year):
                return str(rel)
            if self._tk_widget_same(w, tree_host):
                return None
            w = getattr(w, "master", None)
        return None

    def _show_folder_tree_context_menu(
        self, event: Any, year: str, tree_host: Any, year_block: Any
    ) -> None:
        if self._is_running:
            return
        if not self._widget_is_descendant_of(event.widget, year_block):
            return
        row_rel = self._folder_tree_row_rel_from_event(event, year, tree_host, year_block)

        top = self.winfo_toplevel()
        menu = tkinter.Menu(top, tearoff=0)
        scope = row_rel
        menu.add_command(
            label="Expand all",
            command=lambda y=year, s=scope: self.after_idle(
                lambda yy=y, ss=s: self._folder_tree_expand_all(yy, under_rel=ss)
            ),
        )
        menu.add_command(
            label="Collapse all",
            command=lambda y=year, s=scope: self.after_idle(
                lambda yy=y, ss=s: self._folder_tree_collapse_all(yy, under_rel=ss)
            ),
        )
        try:
            menu.tk_popup(int(event.x_root), int(event.y_root))
        except tkinter.TclError:
            pass

    def _ensure_year_tree_host_visible(self, year: str) -> None:
        """Show the per-year folder list (▼) so nested expand/collapse is visible."""
        info = self._year_tree_header_toggle.get(year)
        if info is None:
            return
        st: Dict[str, bool] = info["st_open"]
        if st.get("v"):
            return
        st["v"] = True
        try:
            info["btn"].configure(text="▼")
            info["tree_host"].pack(fill="x", padx=(10, 0), pady=(4, 0))
        except (tkinter.TclError, AttributeError, KeyError):
            pass

    def _collapse_year_tree_host_header(self, year: str) -> None:
        """Hide the per-year folder list (▶), same as the year-row triangle."""
        info = self._year_tree_header_toggle.get(year)
        if info is None:
            return
        st: Dict[str, bool] = info["st_open"]
        if not st.get("v"):
            return
        st["v"] = False
        try:
            info["btn"].configure(text="▶")
            info["tree_host"].pack_forget()
        except (tkinter.TclError, AttributeError, KeyError):
            pass

    def _folder_tree_expand_all(self, year: str, under_rel: Optional[str] = None) -> None:
        """Open every expandable row in scope; re-scan until lazy-built rows are included."""
        self._ensure_year_tree_host_visible(year)

        def in_scope(rel: str) -> bool:
            return self._folder_tree_rel_under_prefix(rel, under_rel)

        for _ in range(256):
            entries = [
                e
                for e in self._folder_tree_expandable.get(year, [])
                if in_scope(e["child_node"].rel)
            ]
            if not entries:
                break
            entries.sort(key=lambda e: e["child_node"].rel.count("/"))
            progressed = False
            for e in entries:
                # Map subtree before filling it (matches arrow toggle; helps CTk lay out children).
                if not e["st_open"]["v"]:
                    e["st_open"]["v"] = True
                    e["btn"].configure(text="▼")
                    e["subtree"].pack(fill="x", padx=(e["pack_depth"] * 12 + 14, 0))
                    progressed = True
                if not e["st_built"]["v"]:
                    self._build_folder_tree_ui(
                        e["subtree"], year, e["child_node"], e["pack_depth"] + 1
                    )
                    e["st_built"]["v"] = True
                    self._bind_folder_tree_context_menu_recursive(e["subtree"], year)
                    progressed = True
            if not progressed:
                break
        try:
            self.update_idletasks()
        except tkinter.TclError:
            pass

    def _folder_tree_collapse_all(self, year: str, under_rel: Optional[str] = None) -> None:
        def in_scope(rel: str) -> bool:
            return self._folder_tree_rel_under_prefix(rel, under_rel)

        entries = [
            e
            for e in self._folder_tree_expandable.get(year, [])
            if in_scope(e["child_node"].rel)
        ]
        entries.sort(key=lambda e: e["child_node"].rel.count("/"), reverse=True)
        for e in entries:
            e["st_open"]["v"] = False
            e["btn"].configure(text="▶")
            e["subtree"].pack_forget()
        if under_rel is None:
            self._collapse_year_tree_host_header(year)
        try:
            self.update_idletasks()
        except tkinter.TclError:
            pass

    @staticmethod
    def _year_expand_toggle_command(
        tree_host: Any,
        btn: Any,
        st_open: Dict[str, bool],
    ) -> Any:
        """Bind one expand/collapse handler per year (avoids Python loop late-binding bugs)."""

        def _toggle() -> None:
            st_open["v"] = not st_open["v"]
            if st_open["v"]:
                btn.configure(text="▼")
                tree_host.pack(fill="x", padx=(10, 0), pady=(4, 0))
            else:
                btn.configure(text="▶")
                tree_host.pack_forget()

        return _toggle

    def _build_folder_tree_ui(self, parent: Any, year: str, node: _FolderNode, depth: int) -> None:
        """Lazy expand/collapse rows with checkboxes (default: all checked)."""
        tree_font = ctk.CTkFont(size=12)
        arrow_font = ctk.CTkFont(size=11)
        count_font = ctk.CTkFont(size=11)
        _tw = 18
        for child in node.children:
            block = ctk.CTkFrame(parent, fg_color="transparent")
            setattr(block, "_seg_tree_row_rel", child.rel)
            setattr(block, "_seg_tree_row_year", year)
            block.pack(fill="x", pady=1)
            row = ctk.CTkFrame(block, fg_color="transparent")
            row.pack(fill="x", padx=(depth * 12, 0))

            d_chk = self._year_folder_check_vars.setdefault(year, {})
            v = d_chk.get(child.rel)
            if v is None:
                v = ctk.BooleanVar(value=True)
                d_chk[child.rel] = v

            if child.children:
                subtree = ctk.CTkFrame(block, fg_color="transparent")
                st_open: Dict[str, bool] = {"v": False}
                st_built: Dict[str, bool] = {"v": False}

                def make_toggle(
                    sf: ctk.CTkFrame,
                    btn: ctk.CTkButton,
                    st: Dict[str, bool],
                    built: Dict[str, bool],
                    child_node: _FolderNode,
                    dep: int,
                ) -> Any:
                    def toggle() -> None:
                        st["v"] = not st["v"]
                        if st["v"]:
                            btn.configure(text="▼")
                            sf.pack(fill="x", padx=(dep * 12 + 14, 0))
                            if not built["v"]:
                                self._build_folder_tree_ui(sf, year, child_node, dep + 1)
                                built["v"] = True
                                self._bind_folder_tree_context_menu_recursive(sf, year)
                        else:
                            btn.configure(text="▶")
                            sf.pack_forget()

                    return toggle

                btn = ctk.CTkButton(
                    row,
                    text="▶",
                    width=20,
                    height=20,
                    font=arrow_font,
                    corner_radius=0,
                    fg_color="transparent",
                    hover_color=("gray85", "gray35"),
                    text_color=("gray40", "gray65"),
                )
                btn.configure(command=make_toggle(subtree, btn, st_open, st_built, child, depth))
                setattr(btn, "_seg_folder_tree_expand_btn", True)
                btn.pack(side="left", padx=(0, 1))
                self._folder_tree_expandable.setdefault(year, []).append(
                    {
                        "subtree": subtree,
                        "btn": btn,
                        "st_open": st_open,
                        "st_built": st_built,
                        "child_node": child,
                        "pack_depth": depth,
                    }
                )
            else:
                ctk.CTkLabel(row, text="", width=_tw).pack(side="left", padx=(0, 1))

            ctk.CTkCheckBox(
                row,
                text=child.name,
                variable=v,
                command=lambda yr=year, r=child.rel, bv=v: self._cascade_tree_check(yr, r, bv),
                checkbox_width=16,
                checkbox_height=16,
                font=tree_font,
            ).pack(side="left", padx=(1, 0))
            ctk.CTkLabel(
                row,
                text=f"Recording files: {child.wav_count:,}",
                text_color=("gray30", "gray75"),
                font=count_font,
            ).pack(side="left", padx=(8, 0))

    def _compute_subfolder_filters_for_run(self) -> Optional[Dict[str, List[str]]]:
        """Maps checked tree nodes to pipeline prefix lists; None = no restriction."""
        out: Dict[str, List[str]] = {}
        for year, d in self._year_folder_check_vars.items():
            if not d:
                continue
            all_k = list(d.keys())
            checked = [k for k, v in d.items() if v.get()]
            if len(checked) == len(all_k):
                continue
            if not checked:
                out[year] = []
            else:
                out[year] = _folder_filter_leaves(checked)
        return out if out else None

    def _refresh_year_checkboxes(self) -> None:
        saved = {y: v.get() for y, v in self._year_check_vars.items()}
        for w in self._years_frame_inner.winfo_children():
            w.destroy()
        self._year_check_vars.clear()
        self._year_folder_paths.clear()
        self._year_folder_check_vars.clear()
        self._folder_tree_expandable.clear()
        self._folder_tree_panel_host.clear()
        self._folder_tree_year_block.clear()
        self._year_tree_header_toggle.clear()
        self._selected_wav_count_by_year.clear()
        self._wav_count_by_year_rel.clear()
        self._manual_metadata_files_by_year = {
            y: p for y, p in self._manual_metadata_files_by_year.items() if Path(p).exists()
        }
        if not self.selected_folder:
            return
        self._pulse_loading("Discovering year folders...")
        pairs = discover_year_roots(Path(self.selected_folder))
        self._pulse_loading(f"Found {len(pairs)} year folder(s). Building folder tree...")
        n_years = max(1, len(pairs))
        scanned_total = 0
        for year_str, ypath in pairs:
            yi = len(self._year_folder_paths)
            self._pulse_loading(f"Scanning year {year_str}...")
            self._update_progress_bar_ui(yi / n_years)
            self._year_folder_paths[year_str] = ypath
            var = ctk.BooleanVar(value=saved.get(year_str, True))
            self._year_check_vars[year_str] = var

            year_block = ctk.CTkFrame(self._years_frame_inner, fg_color="transparent")
            year_block.pack(fill="x", pady=(2, 8))

            self._year_folder_check_vars[year_str] = {}
            year_base = yi / n_years
            year_span = 1.0 / n_years

            def _on_year_tree_progress(msg: str, done: int, total: int) -> None:
                frac = (done / total) if total > 0 else 1.0
                self._update_progress_bar_ui(min(0.99, year_base + year_span * frac))
                self._set_status(f"Loading selected folder... {msg}")
                self._pulse_loading(msg)

            root, scanned_in_year = _build_wav_folder_tree(
                ypath,
                progress_hook=_on_year_tree_progress,
            )
            self._selected_wav_count_by_year[year_str] = int(scanned_in_year)
            rel_counts: Dict[str, int] = {}

            def _collect_counts(n: _FolderNode) -> None:
                if n.rel:
                    rel_counts[n.rel] = int(n.wav_count)
                for ch in n.children:
                    _collect_counts(ch)

            _collect_counts(root)
            self._wav_count_by_year_rel[year_str] = rel_counts
            for rel in rel_counts:
                self._year_folder_check_vars[year_str][rel] = ctk.BooleanVar(value=True)
            scanned_total += scanned_in_year
            self._update_progress_bar_ui(min(0.99, (yi + 1) / n_years))
            has_tree = bool(root.children)

            row_f = ctk.CTkFrame(year_block, fg_color="transparent")
            row_f.pack(fill="x", anchor="w")

            tree_host = ctk.CTkFrame(year_block, fg_color="transparent")
            setattr(tree_host, "_seg_folder_tree_host", True)
            arrow_font = ctk.CTkFont(size=11)

            if has_tree:
                st_open: Dict[str, bool] = {"v": False}
                btn_ref = ctk.CTkButton(
                    row_f,
                    text="▶",
                    width=20,
                    height=20,
                    font=arrow_font,
                    corner_radius=0,
                    fg_color="transparent",
                    hover_color=("gray85", "gray35"),
                    text_color=("gray40", "gray65"),
                )

                btn_ref.configure(
                    command=self._year_expand_toggle_command(tree_host, btn_ref, st_open)
                )
                setattr(btn_ref, "_seg_folder_tree_expand_btn", True)
                btn_ref.pack(side="left", padx=(0, 4))
                self._year_tree_header_toggle[year_str] = {
                    "st_open": st_open,
                    "btn": btn_ref,
                    "tree_host": tree_host,
                }
            else:
                ctk.CTkLabel(row_f, text="", width=24).pack(side="left", padx=(0, 4))

            ctk.CTkCheckBox(
                row_f,
                text=year_str,
                variable=var,
                command=lambda y=year_str: self._on_year_folder_cascade(y),
                checkbox_width=16,
                checkbox_height=16,
                font=ctk.CTkFont(size=13),
            ).pack(side="left", padx=(0, 8))
            ctk.CTkLabel(
                row_f,
                text=f"Record Files: {scanned_in_year:,}",
                text_color=("gray30", "gray75"),
                font=ctk.CTkFont(size=12, weight="bold"),
            ).pack(side="left", padx=(0, 8))
            has_auto_meta = year_metadata_availability(ypath)
            manual_meta = self._manual_metadata_files_by_year.get(year_str, "")
            has_manual_meta = bool(manual_meta and Path(manual_meta).is_file())
            if has_auto_meta or has_manual_meta:
                source = "Auto-Detected" if has_auto_meta else "Selected Manually"
                badge = f"✓ Metadata File Exists ({source}, Ready to Process)"
                ctk.CTkLabel(
                    row_f,
                    text=badge,
                    text_color=("#2d6a4f", "#95d5b2"),
                    font=ctk.CTkFont(size=12),
                ).pack(side="left", padx=(0, 8))
            else:
                ctk.CTkButton(
                    row_f,
                    text="✗ Metadata File Missing (Not Ready to Process) — Click to Select",
                    fg_color="transparent",
                    hover_color=("gray85", "gray35"),
                    text_color=("#9d0208", "#ff758f"),
                    font=ctk.CTkFont(size=12),
                    command=lambda y=year_str: self._pick_metadata_for_year(y),
                ).pack(side="left", padx=(0, 8))

            setattr(year_block, "_seg_year_block_year", year_str)
            setattr(year_block, "_seg_year_block_tree_host", tree_host)
            self._folder_tree_year_block[year_str] = year_block
            self._folder_tree_panel_host[year_str] = tree_host
            if has_tree:
                self._build_folder_tree_ui(tree_host, year_str, root, 0)
            else:
                ctk.CTkLabel(
                    year_block,
                    text="(No audio recordings found under this year folder.)",
                    text_color=("gray40", "gray65"),
                    font=ctk.CTkFont(size=11),
                ).pack(anchor="w", padx=(38, 0), pady=(0, 2))
            self._bind_folder_tree_context_menu_recursive(year_block, year_str)
        if not pairs:
            ctk.CTkLabel(
                self._years_frame_inner,
                text="Single root (no year subfolders)",
                text_color=("gray35", "gray70"),
            ).pack(anchor="w")
        self._update_progress_bar_ui(1.0)
        self._set_status(
            f"Folder set. Found {len(pairs)} year(s), scanned {scanned_total} audio file(s)."
        )

    def _selected_years(self) -> List[str]:
        """Years whose top-level checkbox is on (may be empty)."""
        if not self._year_check_vars:
            return []
        return [y for y, v in self._year_check_vars.items() if v.get()]

    def _count_selected_wav_files(
        self,
        years: List[str],
        subfolder_filters: Optional[Dict[str, List[str]]],
    ) -> int:
        total = 0
        for y in years:
            year_total = int(self._selected_wav_count_by_year.get(y, 0))
            if not subfolder_filters or y not in subfolder_filters:
                total += year_total
                continue
            prefixes = subfolder_filters[y]
            if not prefixes:
                continue
            rel_counts = self._wav_count_by_year_rel.get(y, {})
            total += sum(int(rel_counts.get(p, 0)) for p in prefixes)
        return total

    def _select_all_years(self) -> None:
        """Check every year and every folder row under the year list."""
        self._cascade_inner = True
        try:
            for v in self._year_check_vars.values():
                if not v.get():
                    v.set(True)
            for d in self._year_folder_check_vars.values():
                for fv in d.values():
                    if not fv.get():
                        fv.set(True)
        finally:
            self._cascade_inner = False
        self.update_idletasks()

    def _clear_years(self) -> None:
        """Uncheck every year and every folder row under the year list."""
        self._cascade_inner = True
        try:
            for v in self._year_check_vars.values():
                if v.get():
                    v.set(False)
            for d in self._year_folder_check_vars.values():
                for fv in d.values():
                    if fv.get():
                        fv.set(False)
        finally:
            self._cascade_inner = False
        self.update_idletasks()

    def _toggle_dark_mode(self) -> None:
        if self.mode_switch.get() == 1:
            ctk.set_appearance_mode("Dark")
        else:
            ctk.set_appearance_mode("Light")
        if getattr(self, "_footer_bar", None) is not None:
            self._footer_bar.configure(fg_color=self.cget("fg_color"))
        self._sync_progress_pct_label()

    def _on_select_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select recording dataset folder")
        if not folder:
            return
        self._set_status("Loading selected folder...")
        self._update_progress_bar_ui(0.0)
        self.update_idletasks()
        self._apply_selected_folder(folder)

    def _on_select_output(self) -> None:
        folder = filedialog.askdirectory(title="Select output folder")
        if not folder:
            return
        self.output_dir = str(Path(folder))
        self.output_label.configure(text=self.output_dir)
        self._append_log(f"Output: {self.output_dir}")

    def _on_run_pipeline(self) -> None:
        if not self.selected_folder:
            self._show_message("Folder", "Select a data folder first.", "warning")
            return
        if self._is_running and self.worker_thread and self.worker_thread.is_alive():
            self._toggle_pause_resume()
            return

        seg_mode = self.segmentation_mode_var.get()
        scan_mode = self.recordings_scan_mode_var.get()

        run_segmentation = scan_mode != "Only Recordings Files Scan"
        run_classification = seg_mode == "Segmentation + Classification"
        run_recordings_scan = scan_mode in ("With Recordings Files Scan", "Only Recordings Files Scan")
        metadata_only = False
        years = self._selected_years()
        if len(years) == 0:
            self._show_message(
                "Years",
                "Select at least one year (checkbox next to 2015, 2018, …). "
                "Unchecking the year excludes that year from the run.",
                "warning",
            )
            return

        self._run_start_perf = time.perf_counter()
        self._run_processed_files = 0
        self._pause_requested.clear()
        self._stop_requested.clear()
        self._is_running = True
        self._set_ui_running_state(True)
        self._update_progress_bar_ui(0.01)
        self._last_pipeline_status_text = "Starting…"
        self._set_status("Elapsed Time: 0s")
        self._append_log("Run started.")
        self.run_btn.configure(text="Pause", state="normal")
        self.stop_btn.configure(state="normal")

        sf = self._compute_subfolder_filters_for_run()
        self._run_total_files = self._count_selected_wav_files(years, sf)

        self._start_elapsed_tick()

        self.worker_thread = threading.Thread(
            target=self._run_pipeline_worker,
            args=(
                self.selected_folder,
                self.output_dir,
                years,
                run_segmentation,
                run_classification,
                run_recordings_scan,
                metadata_only,
                sf,
                dict(self._manual_metadata_files_by_year),
            ),
            daemon=True,
        )
        self.worker_thread.start()

    def _run_pipeline_worker(
        self,
        folder_path: str,
        out_dir: Optional[str],
        years: Optional[List[str]],
        run_segmentation: bool,
        run_classification: bool,
        run_recordings_scan: bool,
        metadata_only: bool,
        subfolder_filters: Optional[Dict[str, List[str]]],
        metadata_file_overrides: Optional[Dict[str, str]],
    ) -> None:
        last_emit_t = 0.0
        last_emit_p = -1.0
        last_emit_status = ""

        def progress_callback(progress: float, status_text: str, eta_seconds: Optional[float] = None) -> None:
            nonlocal last_emit_t, last_emit_p, last_emit_status
            while self._pause_requested.is_set():
                if self._stop_requested.is_set():
                    raise PipelineInterrupted("Stopped by user.")
                time.sleep(0.1)
            if self._stop_requested.is_set():
                raise PipelineInterrupted("Stopped by user.")
            p = max(0.0, min(1.0, float(progress)))
            now = time.perf_counter()
            status_changed = status_text != last_emit_status
            should_emit = (
                p >= 1.0
                or (now - last_emit_t) >= 0.20
                or abs(p - last_emit_p) >= 0.005
                or status_changed
            )
            if not should_emit:
                return
            last_emit_t = now
            last_emit_p = p
            last_emit_status = status_text
            self.ui_queue.put(
                {
                    "type": "progress",
                    "progress": p,
                    "status": status_text,
                    "eta_seconds": eta_seconds,
                }
            )

        try:
            primary, summary = execute_pipeline(
                folder_path,
                progress_callback,
                output_dir=out_dir,
                years=years,
                want_syllables_xlsx=run_segmentation,
                want_metadata_xlsx=False,
                metadata_only=metadata_only,
                run_classification=run_classification,
                subfolder_filters=subfolder_filters,
                metadata_file_overrides=metadata_file_overrides,
            ) if run_segmentation else ("", RunSummary())

            if run_recordings_scan:
                scan_path, scan_count = _build_recordings_scan_workbook(
                    root_folder=folder_path,
                    selected_years=years or [],
                    subfolder_filters=subfolder_filters,
                    output_dir=out_dir,
                )
                summary.output_files.append(scan_path)
                if not primary:
                    primary = scan_path
                self.ui_queue.put(
                    {
                        "type": "progress",
                        "progress": 1.0 if not run_segmentation else max(0.0, min(1.0, float(0.99))),
                        "status": f"Recordings Files Scan done: {scan_count} files",
                        "eta_seconds": 0.0,
                    }
                )
            self.ui_queue.put(
                {
                    "type": "done",
                    "output_path": primary,
                    "summary": summary,
                }
            )
        except PipelineInterrupted as exc:
            self.ui_queue.put({"type": "stopped", "message": str(exc)})
        except Exception as exc:
            self.ui_queue.put({"type": "error", "message": str(exc)})

    def _start_queue_poller(self) -> None:
        self._queue_poll_after_id = self.after(100, self._poll_queue)

    def _poll_queue(self) -> None:
        try:
            while True:
                event = self.ui_queue.get_nowait()
                self._handle_ui_event(event)
        except queue.Empty:
            pass
        finally:
            self._queue_poll_after_id = self.after(100, self._poll_queue)

    def _update_processed_files_from_status(self, status: str) -> None:
        m = re.search(
            r"Segmenting recording\s+(\d+)\s*/\s*(\d+)", status, flags=re.I
        )
        if not m:
            m = re.search(r"Segmenting WAV\s+(\d+)\s*/\s*(\d+)", status, flags=re.I)
        if not m:
            m = re.search(r"Segment\s+(\d+)\s*/\s*(\d+)", status, flags=re.I)
        if m:
            done = int(m.group(1))
            self._run_processed_files = max(self._run_processed_files, done)
            return
        for pat in (
            r"\bClassify\s+(\d+)\s*/\s*(\d+)\b",
            r"Classify syllables\s+(\d+)\s*/\s*(\d+)",
            r"Classify: resolving paths\s+(\d+)\s*/\s*(\d+)",
            r"Build spectrograms\s+(\d+)\s*/\s*(\d+)",
            r"Build spectrograms \(per syllable\)\s+(\d+)\s*/\s*(\d+)",
            r"CNN predictions \(per recording\)\s+(\d+)\s*/\s*(\d+)",
            r"CNN batch inference \(syllables\)\s+(\d+)\s*/\s*(\d+)",
        ):
            m_cls = re.search(pat, status, flags=re.I)
            if m_cls:
                done = int(m_cls.group(1))
                self._run_processed_files = max(self._run_processed_files, done)
                return
        m2 = re.search(r"Recordings Files Scan done:\s*(\d+)", status, flags=re.I)
        if m2:
            self._run_processed_files = max(self._run_processed_files, int(m2.group(1)))

    def _handle_ui_event(self, event: Dict[str, object]) -> None:
        event_type = event.get("type")

        if event_type == "progress":
            progress = float(event.get("progress", 0.0))
            status = str(event.get("status", "Working…"))
            self._update_processed_files_from_status(status)
            self._last_pipeline_status_text = status
            if progress >= 0:
                target = self._display_progress_from_pipeline(progress)
                target_pct = max(1, min(99, int(round(target * 100))))
                current_pct = int(round(self._ui_progress_value * 100))
                next_pct = max(current_pct, min(target_pct, current_pct + 1))
                self._update_progress_bar_ui(next_pct / 100.0)
            self._refresh_running_status_bar()
            self._append_log(status)
            return

        if event_type == "done":
            summary = event.get("summary")
            elapsed: Optional[float] = None
            if self._run_start_perf is not None:
                elapsed = time.perf_counter() - self._run_start_perf
            self._run_start_perf = None
            self._run_processed_files = self._run_total_files
            self._stop_elapsed_tick()
            self._update_progress_bar_ui(1.0)
            if elapsed is not None:
                self._set_status(
                    f"Done | Elapsed Time: {self._format_elapsed_duration(elapsed)}"
                )
            else:
                self._set_status("Done.")
            if summary is not None:
                self._append_log(summary.format_report())
                if elapsed is not None:
                    self._append_log(f"Elapsed: {self._format_elapsed_duration(elapsed)}")
                self._last_run_summary = summary
                self._last_run_elapsed = elapsed
                self.results_btn.configure(state="normal")
                if self._results_window is not None and self._results_body is not None:
                    try:
                        if self._results_window.winfo_exists():
                            self._populate_results_body(
                                self._results_body,
                                summary,
                                elapsed_seconds=elapsed,
                            )
                    except tkinter.TclError:
                        pass
            else:
                self._last_run_summary = None
                self._last_run_elapsed = None
            self._set_ui_running_state(False)
            self._is_running = False
            self.run_btn.configure(text="Run")
            self.stop_btn.configure(state="disabled")
            messagebox.showinfo("Done", "Processing finished successfully.")
            if self._last_run_summary is not None:
                self._open_or_focus_results_window()
            return

        if event_type == "stopped":
            elapsed = time.perf_counter() - self._run_start_perf if self._run_start_perf is not None else 0.0
            self._run_start_perf = None
            self._stop_elapsed_tick()
            msg = str(event.get("message", "Stopped by user."))
            self._set_status(
                f"Stopped | Elapsed Time: {self._format_elapsed_duration(elapsed)}"
            )
            self._append_log(msg)
            self._set_ui_running_state(False)
            self._is_running = False
            self.run_btn.configure(text="Run")
            self.stop_btn.configure(state="disabled")
            return

        if event_type == "error":
            elapsed = time.perf_counter() - self._run_start_perf if self._run_start_perf is not None else 0.0
            self._run_start_perf = None
            self._stop_elapsed_tick()
            msg = str(event.get("message", "Unknown error"))
            self._set_status(
                f"Error | Elapsed Time: {self._format_elapsed_duration(elapsed)}"
            )
            self._append_log(f"Error: {msg}")
            self._set_ui_running_state(False)
            self._is_running = False
            self.run_btn.configure(text="Run")
            self.stop_btn.configure(state="disabled")
            self._show_message("Error", msg, "cancel")

    def _set_ui_running_state(self, is_running: bool) -> None:
        if is_running:
            self._disable_inputs_during_run()
        else:
            self._enable_inputs_after_run()

    def _disable_inputs_during_run(self) -> None:
        for child in self.folder_row.winfo_children():
            if isinstance(child, ctk.CTkButton):
                child.configure(state="disabled")
        for child in self.out_row.winfo_children():
            if isinstance(child, ctk.CTkButton):
                child.configure(state="disabled")
        self._set_year_selection_widgets_state("disabled")
        self.run_btn.configure(state="normal")
        self.results_btn.configure(state="disabled")
        self.outputs_browser_btn.configure(state="normal")
        self.stop_btn.configure(state="normal")
        self.mode_switch.configure(state="normal")

    def _enable_inputs_after_run(self) -> None:
        for child in self.folder_row.winfo_children():
            if isinstance(child, ctk.CTkButton):
                child.configure(state="normal")
        for child in self.out_row.winfo_children():
            if isinstance(child, ctk.CTkButton):
                child.configure(state="normal")
        self._set_year_selection_widgets_state("normal")
        self.run_btn.configure(state="normal" if self.selected_folder else "disabled")
        self.results_btn.configure(
            state="normal" if self._last_run_summary is not None else "disabled"
        )
        self.outputs_browser_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.mode_switch.configure(state="normal")

    def _set_year_selection_widgets_state(self, state: str) -> None:
        def _apply_recursive(widget: Any) -> None:
            if isinstance(widget, ctk.CTkCheckBox):
                try:
                    widget.configure(state=state)
                except Exception:
                    pass
            elif isinstance(widget, ctk.CTkButton):
                try:
                    widget.configure(state=state)
                except Exception:
                    pass
            elif isinstance(widget, ctk.CTkOptionMenu):
                try:
                    widget.configure(state=state)
                except Exception:
                    pass
            for ch in widget.winfo_children():
                _apply_recursive(ch)

        if self._year_controls_row is not None:
            _apply_recursive(self._year_controls_row)
        if self._years_frame_inner is not None:
            _apply_recursive(self._years_frame_inner)

    def _toggle_pause_resume(self) -> None:
        if not self._is_running:
            return
        if not self._pause_requested.is_set():
            self._pause_requested.set()
            self.run_btn.configure(text="Resume")
            self._set_status("Paused.")
            self._append_log("Paused by user.")
        else:
            self._pause_requested.clear()
            self.run_btn.configure(text="Pause")
            self._set_status("Resuming…")
            self._append_log("Resumed by user.")

    def _on_stop_pipeline(self) -> None:
        if not self._is_running:
            return
        self._stop_requested.set()
        self._pause_requested.clear()
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="disabled")
        self._set_status("Stopping…")
        self._append_log("Stop requested by user.")

    def _set_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def _show_loading_overlay(self, message: str = "Loading...") -> None:
        if self._loading_window is not None:
            try:
                if self._loading_window.winfo_exists():
                    return
            except tkinter.TclError:
                pass
            self._loading_window = None
            self._loading_bar = None

        win = ctk.CTkToplevel(self)
        win.title("Loading")
        win.geometry("360x130")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()
        set_window_icon(win)
        self._loading_window = win

        body = ctk.CTkFrame(win, corner_radius=12)
        body.pack(fill="both", expand=True, padx=12, pady=12)
        ctk.CTkLabel(
            body,
            text=message,
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(12, 8))

        self._loading_note_label = ctk.CTkLabel(
            body,
            text="Scanning years and recording folders...",
            text_color=("gray35", "gray70"),
        )
        self._loading_note_label.pack(anchor="w", padx=12, pady=(0, 8))

        bar = ctk.CTkProgressBar(
            body,
            mode="determinate",
            height=_LOADING_PROGRESS_BAR_HEIGHT,
        )
        bar.pack(fill="x", padx=12, pady=(0, 12))
        self._loading_phase = 0.0
        bar.set(0.0)
        self._loading_bar = bar
        self.update()

    def _pulse_loading(self, message: Optional[str] = None) -> None:
        if message and self._loading_note_label is not None:
            try:
                self._loading_note_label.configure(text=message)
            except tkinter.TclError:
                pass
        if self._loading_bar is not None:
            self._loading_phase = (self._loading_phase + 0.04) % 1.0
            try:
                self._loading_bar.set(self._loading_phase)
            except tkinter.TclError:
                pass
        self.update_idletasks()

    def _hide_loading_overlay(self) -> None:
        self._loading_phase = 0.0
        self._loading_bar = None
        self._loading_note_label = None
        if self._loading_window is not None:
            try:
                if self._loading_window.winfo_exists():
                    self._loading_window.grab_release()
                    self._loading_window.destroy()
            except tkinter.TclError:
                pass
        self._loading_window = None

    def _apply_selected_folder(self, folder: str) -> None:
        self.selected_folder = str(Path(folder))
        self.folder_label.configure(text=self.selected_folder)
        self.run_btn.configure(state="normal")
        self._year_folder_check_vars.clear()
        self._refresh_year_checkboxes()
        self._set_status("Folder set.")
        self._append_log(f"Data: {self.selected_folder}")

    def _pick_metadata_for_year(self, year: str) -> None:
        initial_dir = str(self._year_folder_paths.get(year, Path.cwd()))
        picked = filedialog.askopenfilename(
            title=f"Select metadata workbook for {year}",
            initialdir=initial_dir,
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")],
        )
        if not picked:
            return
        self._manual_metadata_files_by_year[year] = picked
        self._refresh_year_checkboxes()

    def _append_log(self, body: str) -> None:
        if body == self._last_log_body:
            return
        self._last_log_body = body
        try:
            _, y1 = self.log_box.yview()
            at_bottom = y1 >= 0.999
        except tkinter.TclError:
            at_bottom = True
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self._run_start_perf is not None:
            el_txt = self._format_elapsed_duration(
                max(0.0, time.perf_counter() - self._run_start_perf)
            )
        else:
            el_txt = "—"
        header = f"{ts} | Elapsed Time: {el_txt}"
        self.log_box.insert("end", header + "\n" + body + "\n")
        if at_bottom:
            self.log_box.see("end")

    def _on_close_requested(self) -> None:
        self._stop_requested.set()
        self._pause_requested.clear()
        self._stop_elapsed_tick()
        if self._queue_poll_after_id is not None:
            try:
                self.after_cancel(self._queue_poll_after_id)
            except tkinter.TclError:
                pass
            self._queue_poll_after_id = None
        self._hide_loading_overlay()
        self._close_results_window()
        self._close_outputs_browser_window()
        try:
            self.destroy()
        except tkinter.TclError:
            pass

    def _show_message(self, title: str, message: str, icon: str = "info") -> None:
        if CTkMessagebox is not None:
            CTkMessagebox(title=title, message=message, icon=icon)
        else:
            if icon in {"cancel", "warning"}:
                messagebox.showerror(title, message)
            elif icon == "check":
                messagebox.showinfo(title, message)
            else:
                messagebox.showinfo(title, message)


if __name__ == "__main__":
    register_windows_application_identity()
    app = SegmentationApp()
    app.mainloop()
