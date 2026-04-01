import ctypes
from ctypes import wintypes
import os
import platform
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Union, Tuple

import customtkinter as ctk
import tkinter
from tkinter import filedialog, messagebox

from pipeline import (
    RunSummary,
    discover_year_roots,
    execute_pipeline,
    year_metadata_availability,
)

try:
    from CTkMessagebox import CTkMessagebox
except Exception:
    CTkMessagebox = None


@dataclass
class _FolderNode:
    """Folder tree under a year (paths relative to the year directory, POSIX)."""

    name: str
    rel: str
    children: List["_FolderNode"] = field(default_factory=list)


def _build_wav_folder_tree(
    year_path: Path,
    progress_hook: Optional[Callable[[str, int, int], None]] = None,
) -> Tuple[_FolderNode, int]:
    """Directories on paths to .wav/.WAV files under *year_path*, plus WAV count."""
    year_path = year_path.resolve()
    root = _FolderNode("", "", [])
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
    for idx, f in enumerate(wav_files, start=1):
        if progress_hook and (idx % 50 == 0 or idx == total_files):
            progress_hook(
                f"Scanning {year_path.name}: {idx}/{total_files} audio files",
                idx,
                total_files,
            )
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
            nodes.append(_FolderNode(name=name, rel=rel, children=ch))
        return nodes

    root.children = to_nodes(tree, "")
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

        if platform.system() == "Windows" and ico_path.is_file():
            ico_s = str(ico_path)
            try:
                window.iconbitmap(default=ico_s)
            except Exception:
                try:
                    window.iconbitmap(ico_s)
                except Exception:
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
        self.geometry("920x720")
        self.minsize(800, 620)

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.selected_folder: Optional[str] = None
        self.output_dir: Optional[str] = None
        self.worker_thread: Optional[threading.Thread] = None
        self.ui_queue: "queue.Queue[Dict[str, object]]" = queue.Queue()
        self._year_check_vars: Dict[str, ctk.BooleanVar] = {}
        self._year_folder_paths: Dict[str, Path] = {}
        self._year_folder_check_vars: Dict[str, Dict[str, ctk.BooleanVar]] = {}
        self._cascade_inner: bool = False
        self._years_frame_inner: Optional[ctk.CTkScrollableFrame] = None
        self._log_visible = False
        self._log_grid_info: Dict[str, Any] = {}
        self._run_start_perf: Optional[float] = None
        self._last_run_summary: Optional[RunSummary] = None
        self._last_run_elapsed: Optional[float] = None
        self._results_window: Optional[ctk.CTkToplevel] = None
        self._results_body: Optional[ctk.CTkScrollableFrame] = None
        self._loading_window: Optional[ctk.CTkToplevel] = None
        self._loading_bar: Optional[ctk.CTkProgressBar] = None
        self._loading_note_label: Optional[ctk.CTkLabel] = None
        self._loading_phase: float = 0.0

        set_window_icon(self)
        self._build_ui()
        self._start_queue_poller()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.container = ctk.CTkFrame(self, corner_radius=14)
        self.container.grid(row=0, column=0, padx=16, pady=16, sticky="nsew")
        self.container.grid_columnconfigure(0, weight=1)

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
            text="Dark mode",
            command=self._toggle_dark_mode,
            width=52,
        )
        self.mode_switch.grid(row=0, column=1, sticky="e")
        if ctk.get_appearance_mode().lower() == "dark":
            self.mode_switch.select()

        self.subtitle_label = ctk.CTkLabel(
            self.container,
            text="Pick a data root (one year or a parent with 2015/, 2016/, …).",
            text_color=("gray35", "gray70"),
            font=ctk.CTkFont(size=13),
        )
        self.subtitle_label.grid(row=row, column=0, padx=16, pady=(0, 8), sticky="w")
        row += 1

        self.folder_row = ctk.CTkFrame(self.container, fg_color="transparent")
        self.folder_row.grid(row=row, column=0, padx=16, pady=(0, 6), sticky="ew")
        self.folder_row.grid_columnconfigure(1, weight=1)
        row += 1

        ctk.CTkButton(
            self.folder_row,
            text="Data folder",
            width=130,
            command=self._on_select_folder,
        ).grid(row=0, column=0, padx=(0, 10), pady=4, sticky="w")

        self.folder_label = ctk.CTkLabel(
            self.folder_row,
            text="None",
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
            text="Output folder",
            width=130,
            command=self._on_select_output,
        ).grid(row=0, column=0, padx=(0, 10), pady=4, sticky="w")

        self.output_label = ctk.CTkLabel(
            self.out_row,
            text="Default: ./outputs",
            anchor="w",
            corner_radius=8,
            fg_color=("gray90", "gray20"),
            padx=10,
            pady=8,
        )
        self.output_label.grid(row=0, column=1, sticky="ew")

        ctk.CTkLabel(
            self.container,
            text="Years",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=row, column=0, padx=16, pady=(8, 4), sticky="w")
        row += 1

        ctk.CTkLabel(
            self.container,
            text=(
                "Each year starts collapsed—use ▶ to show folders. "
                "Turn on a year’s checkbox to include it, or simply check any subfolder—parents and the year "
                "turn on automatically. Uncheck the year to exclude that year. "
                "Under a selected year, uncheck folders to narrow processing. "
                "Default: all folders checked. Unchecking a parent unchecks its descendants; "
                "unchecking the year toggles all folders under it. "
                "Metadata Excel for the year is still read when that year runs."
            ),
            text_color=("gray35", "gray70"),
            font=ctk.CTkFont(size=11),
            wraplength=860,
            justify="left",
        ).grid(row=row, column=0, padx=16, pady=(0, 4), sticky="w")
        row += 1

        self.var_segmentation = ctk.BooleanVar(value=True)
        self.var_scan = ctk.BooleanVar(value=True)

        year_controls_row = ctk.CTkFrame(self.container, fg_color="transparent")
        year_controls_row.grid(row=row, column=0, padx=16, pady=(0, 6), sticky="w")
        row += 1

        ctk.CTkButton(
            year_controls_row,
            text="SELECT ALL",
            width=100,
            command=self._select_all_years,
        ).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(
            year_controls_row,
            text="DESELECT ALL",
            width=110,
            command=self._clear_years,
        ).grid(row=0, column=1, padx=(0, 16))
        ctk.CTkCheckBox(
            year_controls_row,
            text="Segmentation workbook",
            variable=self.var_segmentation,
            command=self._on_output_checkbox_change,
        ).grid(row=0, column=2, padx=(0, 16), sticky="w")
        ctk.CTkCheckBox(
            year_controls_row,
            text="Recording scan workbook",
            variable=self.var_scan,
            command=self._on_output_checkbox_change,
        ).grid(row=0, column=3, sticky="w")

        self._years_frame_inner = ctk.CTkScrollableFrame(self.container, height=260)
        self._years_frame_inner.grid(row=row, column=0, padx=16, pady=(0, 6), sticky="ew")
        row += 1

        self.controls_row = ctk.CTkFrame(self.container, fg_color="transparent")
        self.controls_row.grid(row=row, column=0, padx=16, pady=(6, 8), sticky="ew")
        row += 1

        self.run_btn = ctk.CTkButton(
            self.controls_row,
            text="Run",
            state="disabled",
            width=120,
            command=self._on_run_pipeline,
        )
        self.run_btn.grid(row=0, column=0, sticky="w")

        self.results_btn = ctk.CTkButton(
            self.controls_row,
            text="Results",
            width=100,
            state="disabled",
            command=self._on_view_results,
        )
        self.results_btn.grid(row=0, column=1, padx=(12, 0), sticky="w")

        self.progress = ctk.CTkProgressBar(self.container)
        self.progress.grid(row=row, column=0, padx=16, pady=(4, 4), sticky="ew")
        row += 1
        self.progress.set(0)

        self.status_label = ctk.CTkLabel(
            self.container,
            text="Ready",
            anchor="w",
            text_color=("gray35", "gray70"),
        )
        self.status_label.grid(row=row, column=0, padx=16, pady=(0, 6), sticky="ew")
        row += 1

        log_bar = ctk.CTkFrame(self.container, fg_color="transparent")
        log_bar.grid(row=row, column=0, padx=16, pady=(0, 4), sticky="w")
        row += 1

        self._log_toggle_btn = ctk.CTkButton(
            log_bar,
            text="Show log",
            width=110,
            command=self._toggle_log_panel,
        )
        self._log_toggle_btn.pack(side="left")

        self.log_box = ctk.CTkTextbox(self.container, height=180, wrap="word")
        self._log_grid_info = {"row": row, "column": 0, "padx": 16, "pady": (0, 16), "sticky": "nsew"}
        self.log_box.grid(**self._log_grid_info)
        self.log_box.insert("end", "Ready.\n")
        self.log_box.configure(state="disabled")
        self.log_box.grid_remove()
        self.container.grid_rowconfigure(row, weight=1)

    def _on_output_checkbox_change(self) -> None:
        if not self.var_segmentation.get() and not self.var_scan.get():
            self.var_segmentation.set(True)

    def _toggle_log_panel(self) -> None:
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.log_box.grid(**self._log_grid_info)
            self._log_toggle_btn.configure(text="Hide log")
            self.log_box.see("end")
        else:
            self.log_box.grid_remove()
            self._log_toggle_btn.configure(text="Show log")

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

    @staticmethod
    def _format_elapsed_status(seconds: float) -> str:
        """Suffix for status line (same style family as ETA)."""
        if seconds < 0:
            return ""
        total = int(round(seconds))
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        if h:
            return f" — Elapsed ~{h}h {m}m"
        if m:
            return f" — Elapsed ~{m}m {s}s"
        return f" — Elapsed ~{s}s"

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

        win = ctk.CTkToplevel(self)
        win.title("Results")
        win.geometry("540x480")
        win.transient(self)
        set_window_icon(win)

        self._results_window = win
        win.protocol("WM_DELETE_WINDOW", self._close_results_window)

        ctk.CTkLabel(win, text="Results", font=ctk.CTkFont(size=17, weight="bold")).pack(
            anchor="w", padx=16, pady=(14, 6)
        )
        scroll = ctk.CTkScrollableFrame(win, height=360)
        scroll.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._results_body = scroll

        self._populate_results_body(
            scroll,
            self._last_run_summary,
            elapsed_seconds=self._last_run_elapsed,
        )

        ctk.CTkButton(win, text="Close", width=100, command=self._close_results_window).pack(pady=(0, 14))

    def _populate_results_body(
        self,
        scroll: Optional[ctk.CTkScrollableFrame],
        summary: RunSummary,
        *,
        elapsed_seconds: Optional[float] = None,
    ) -> None:
        if scroll is None:
            return
        for w in scroll.winfo_children():
            w.destroy()

        padx = 4
        ctk.CTkLabel(
            scroll,
            text="Outputs",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", padx=padx, pady=(4, 6))

        out_dir = getattr(summary, "output_directory", None) or ""
        files: List[str] = list(getattr(summary, "output_files", []) or [])
        if not out_dir and files:
            out_dir = str(Path(files[0]).parent.resolve())

        for fp in files:
            name = Path(fp).name

            def _open_f(p: str = fp) -> None:
                open_path_with_default_app(p)

            ctk.CTkButton(
                scroll,
                text=name,
                anchor="w",
                command=_open_f,
            ).pack(fill="x", pady=2, padx=padx)

        if out_dir:
            ctk.CTkButton(
                scroll,
                text="Open output folder",
                command=lambda: open_folder_in_explorer(out_dir),
            ).pack(anchor="w", padx=padx, pady=(8, 12))

        ctk.CTkLabel(
            scroll,
            text="Summary",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", padx=padx, pady=(4, 6))

        if elapsed_seconds is not None:
            ctk.CTkLabel(
                scroll,
                text=f"Elapsed: {self._format_elapsed_duration(elapsed_seconds)}",
                anchor="w",
                text_color=("gray25", "gray80"),
            ).pack(anchor="w", padx=padx, pady=(0, 6))

        yrs = ", ".join(getattr(summary, "years_processed", []) or []) or "—"
        lines = [
            f"Years: {yrs}",
            f"Metadata rows scanned: {getattr(summary, 'metadata_rows_scanned', 0)}",
            f"Segmentation OK / failed: {getattr(summary, 'wav_segmentation_succeeded', 0)} / "
            f"{getattr(summary, 'wav_segmentation_failed', 0)}",
            f"Total syllable rows: {getattr(summary, 'total_syllable_rows', 0)}",
        ]
        for line in lines:
            ctk.CTkLabel(scroll, text=line, anchor="w", justify="left").pack(
                anchor="w", padx=padx, pady=2
            )

        errs = list(getattr(summary, "error_messages", []) or [])
        if errs:
            ctk.CTkLabel(
                scroll,
                text="Notes",
                font=ctk.CTkFont(size=13, weight="bold"),
            ).pack(anchor="w", padx=padx, pady=(10, 4))
            for e in errs[:8]:
                ctk.CTkLabel(
                    scroll,
                    text=f"• {e[:220]}",
                    anchor="w",
                    justify="left",
                    wraplength=480,
                ).pack(anchor="w", padx=padx, pady=1)

    def _cascade_tree_check(self, year: str, rel: str, var: ctk.BooleanVar) -> None:
        """Checking a folder turns on all ancestors in the path and the year; also cascades to descendants."""
        if self._cascade_inner:
            return
        self._cascade_inner = True
        try:
            val = var.get()
            d = self._year_folder_check_vars.get(year, {})
            if val:
                parts = [p for p in rel.split("/") if p]
                for i in range(len(parts) - 1):
                    prefix = "/".join(parts[: i + 1])
                    pv = d.get(prefix)
                    if pv is not None:
                        pv.set(True)
                yv = self._year_check_vars.get(year)
                if yv is not None:
                    yv.set(True)
            for k, v in d.items():
                if k == rel or k.startswith(rel + "/"):
                    v.set(val)
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
        """Recursive expand/collapse rows with checkboxes (default: all checked)."""
        tree_font = ctk.CTkFont(size=12)
        arrow_font = ctk.CTkFont(size=11)
        _tw = 18
        for child in node.children:
            block = ctk.CTkFrame(parent, fg_color="transparent")
            block.pack(fill="x", pady=1)
            row = ctk.CTkFrame(block, fg_color="transparent")
            row.pack(fill="x", padx=(depth * 12, 0))

            v = ctk.BooleanVar(value=True)
            self._year_folder_check_vars.setdefault(year, {})[child.rel] = v

            if child.children:
                subtree = ctk.CTkFrame(block, fg_color="transparent")
                self._build_folder_tree_ui(subtree, year, child, depth + 1)
                st_open: Dict[str, bool] = {"v": False}

                def make_toggle(
                    sf: ctk.CTkFrame,
                    btn: ctk.CTkButton,
                    st: Dict[str, bool],
                    dep: int,
                ) -> Any:
                    def toggle() -> None:
                        st["v"] = not st["v"]
                        if st["v"]:
                            btn.configure(text="▼")
                            sf.pack(fill="x", padx=(dep * 12 + 14, 0))
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
                btn.configure(command=make_toggle(subtree, btn, st_open, depth))
                btn.pack(side="left", padx=(0, 1))
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
            self.progress.set(yi / n_years)
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
                self.progress.set(min(0.99, year_base + year_span * frac))
                self._set_status(f"Loading selected folder... {msg}")
                self._pulse_loading(msg)

            root, scanned_in_year = _build_wav_folder_tree(
                ypath,
                progress_hook=_on_year_tree_progress,
            )
            scanned_total += scanned_in_year
            self.progress.set(min(0.99, (yi + 1) / n_years))
            has_tree = bool(root.children)

            row_f = ctk.CTkFrame(year_block, fg_color="transparent")
            row_f.pack(fill="x", anchor="w")

            tree_host = ctk.CTkFrame(year_block, fg_color="transparent")
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
                btn_ref.pack(side="left", padx=(0, 4))
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
            has_meta = year_metadata_availability(ypath)
            badge = "metadata file exist" if has_meta else "metadata file not exist"
            color = ("#2d6a4f", "#95d5b2") if has_meta else ("#9d0208", "#ff758f")
            ctk.CTkLabel(row_f, text=badge, text_color=color, font=ctk.CTkFont(size=12)).pack(
                side="left", padx=(0, 8)
            )

            if has_tree:
                self._build_folder_tree_ui(tree_host, year_str, root, 0)
            else:
                ctk.CTkLabel(
                    year_block,
                    text="(No WAV files found under this year folder.)",
                    text_color=("gray40", "gray65"),
                    font=ctk.CTkFont(size=11),
                ).pack(anchor="w", padx=(38, 0), pady=(0, 2))
        if not pairs:
            ctk.CTkLabel(
                self._years_frame_inner,
                text="Single root (no year subfolders)",
                text_color=("gray35", "gray70"),
            ).pack(anchor="w")
        self.progress.set(1.0)
        self._set_status(
            f"Folder set. Found {len(pairs)} year(s), scanned {scanned_total} audio file(s)."
        )

    def _selected_years(self) -> List[str]:
        """Years whose top-level checkbox is on (may be empty)."""
        if not self._year_check_vars:
            return []
        return [y for y, v in self._year_check_vars.items() if v.get()]

    def _select_all_years(self) -> None:
        """Check every year and every folder row under the year list."""
        self._cascade_inner = True
        try:
            for v in self._year_check_vars.values():
                v.set(True)
            for d in self._year_folder_check_vars.values():
                for fv in d.values():
                    fv.set(True)
        finally:
            self._cascade_inner = False

    def _clear_years(self) -> None:
        """Uncheck every year and every folder row under the year list."""
        self._cascade_inner = True
        try:
            for v in self._year_check_vars.values():
                v.set(False)
            for d in self._year_folder_check_vars.values():
                for fv in d.values():
                    fv.set(False)
        finally:
            self._cascade_inner = False

    def _toggle_dark_mode(self) -> None:
        if self.mode_switch.get() == 1:
            ctk.set_appearance_mode("Dark")
        else:
            ctk.set_appearance_mode("Light")

    def _on_select_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select data root")
        if not folder:
            return
        self._set_status("Loading selected folder...")
        self.progress.set(0.0)
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
        if self.worker_thread and self.worker_thread.is_alive():
            self._show_message("Busy", "A run is already in progress.", "info")
            return

        want_seg = self.var_segmentation.get()
        want_scan = self.var_scan.get()
        metadata_only = not want_seg and want_scan
        if not want_seg and not want_scan:
            self._show_message("Outputs", "Select at least one workbook type.", "warning")
            return
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
        self._set_ui_running_state(True)
        self.progress.set(0)
        self._set_status("Starting…")
        self._append_log("Run started.")

        sf = self._compute_subfolder_filters_for_run()

        self.worker_thread = threading.Thread(
            target=self._run_pipeline_worker,
            args=(
                self.selected_folder,
                self.output_dir,
                years,
                want_seg,
                want_scan,
                metadata_only,
                sf,
            ),
            daemon=True,
        )
        self.worker_thread.start()

    def _run_pipeline_worker(
        self,
        folder_path: str,
        out_dir: Optional[str],
        years: Optional[List[str]],
        want_segmentation: bool,
        want_scan_workbook: bool,
        metadata_only: bool,
        subfolder_filters: Optional[Dict[str, List[str]]],
    ) -> None:
        def progress_callback(progress: float, status_text: str, eta_seconds: Optional[float] = None) -> None:
            self.ui_queue.put(
                {
                    "type": "progress",
                    "progress": max(0.0, min(1.0, float(progress))),
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
                want_syllables_xlsx=want_segmentation,
                want_metadata_xlsx=want_scan_workbook,
                metadata_only=metadata_only,
                subfolder_filters=subfolder_filters,
            )
            self.ui_queue.put(
                {
                    "type": "done",
                    "output_path": primary,
                    "summary": summary,
                }
            )
        except Exception as exc:
            self.ui_queue.put({"type": "error", "message": str(exc)})

    def _start_queue_poller(self) -> None:
        self.after(100, self._poll_queue)

    def _poll_queue(self) -> None:
        try:
            while True:
                event = self.ui_queue.get_nowait()
                self._handle_ui_event(event)
        except queue.Empty:
            pass
        finally:
            self.after(100, self._poll_queue)

    def _format_eta(self, eta: Optional[float]) -> str:
        if eta is None or eta < 0 or eta > 864000:
            return ""
        m, s = divmod(int(eta), 60)
        h, m = divmod(m, 60)
        if h:
            return f" — ETA ~{h}h {m}m"
        if m:
            return f" — ETA ~{m}m {s}s"
        return f" — ETA ~{s}s"

    def _handle_ui_event(self, event: Dict[str, object]) -> None:
        event_type = event.get("type")

        if event_type == "progress":
            progress = float(event.get("progress", 0.0))
            status = str(event.get("status", "Working…"))
            eta = event.get("eta_seconds")
            eta_f = float(eta) if eta is not None else None
            if progress >= 0:
                self.progress.set(progress)
            extra = self._format_eta(eta_f) if eta_f is not None else ""
            elapsed_extra = ""
            if self._run_start_perf is not None:
                elapsed_extra = self._format_elapsed_status(
                    time.perf_counter() - self._run_start_perf
                )
            line = status + extra + elapsed_extra
            self._set_status(line)
            self._append_log(line)
            return

        if event_type == "done":
            summary = event.get("summary")
            elapsed: Optional[float] = None
            if self._run_start_perf is not None:
                elapsed = time.perf_counter() - self._run_start_perf
            self._run_start_perf = None
            self.progress.set(1.0)
            done_elapsed = self._format_elapsed_status(elapsed) if elapsed is not None else ""
            self._set_status(f"Done.{done_elapsed}")
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
            self._show_message("Done", "Processing finished successfully.", "check")
            return

        if event_type == "error":
            self._run_start_perf = None
            msg = str(event.get("message", "Unknown error"))
            self._set_status(f"Error: {msg}")
            self._append_log(f"Error: {msg}")
            self._set_ui_running_state(False)
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
        self.run_btn.configure(state="disabled")
        self.results_btn.configure(state="disabled")
        self.mode_switch.configure(state="disabled")

    def _enable_inputs_after_run(self) -> None:
        for child in self.folder_row.winfo_children():
            if isinstance(child, ctk.CTkButton):
                child.configure(state="normal")
        for child in self.out_row.winfo_children():
            if isinstance(child, ctk.CTkButton):
                child.configure(state="normal")
        self.run_btn.configure(state="normal" if self.selected_folder else "disabled")
        self.results_btn.configure(
            state="normal" if self._last_run_summary is not None else "disabled"
        )
        self.mode_switch.configure(state="normal")

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
            text="Scanning years and WAV folders...",
            text_color=("gray35", "gray70"),
        )
        self._loading_note_label.pack(anchor="w", padx=12, pady=(0, 8))

        bar = ctk.CTkProgressBar(body, mode="determinate")
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

    def _append_log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        try:
            _, y1 = self.log_box.yview()
            at_bottom = y1 >= 0.999
        except tkinter.TclError:
            at_bottom = True
        self.log_box.insert("end", text + "\n")
        if at_bottom:
            self.log_box.see("end")
        self.log_box.configure(state="disabled")

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
