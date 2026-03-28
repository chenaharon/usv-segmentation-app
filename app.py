import queue
import threading
from pathlib import Path
from typing import Dict, List, Optional, Set

import customtkinter as ctk
from tkinter import filedialog, messagebox

from pipeline import discover_year_roots, execute_pipeline

try:
    from CTkMessagebox import CTkMessagebox
except Exception:
    CTkMessagebox = None


class SegmentationApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.title("USV Segmentation Pipeline")
        self.geometry("920x720")
        self.minsize(800, 620)

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.selected_folder: Optional[str] = None
        self.output_dir: Optional[str] = None
        self.worker_thread: Optional[threading.Thread] = None
        self.ui_queue: "queue.Queue[Dict[str, object]]" = queue.Queue()
        self._year_check_vars: Dict[str, ctk.BooleanVar] = {}
        self._years_frame_inner: Optional[ctk.CTkScrollableFrame] = None

        self._build_ui()
        self._start_queue_poller()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.container = ctk.CTkFrame(self, corner_radius=14)
        self.container.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        self.container.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(
            self.container,
            text="USV Segmentation Desktop",
            font=ctk.CTkFont(size=26, weight="bold"),
        )
        self.title_label.grid(row=0, column=0, padx=20, pady=(24, 6), sticky="w")

        self.subtitle_label = ctk.CTkLabel(
            self.container,
            text="Select a data root (one year folder or a parent with 2015/, 2016/, …).",
            text_color=("gray35", "gray70"),
            font=ctk.CTkFont(size=14),
        )
        self.subtitle_label.grid(row=1, column=0, padx=20, pady=(0, 12), sticky="w")

        # Input folder
        self.folder_row = ctk.CTkFrame(self.container, fg_color="transparent")
        self.folder_row.grid(row=2, column=0, padx=20, pady=(0, 6), sticky="ew")
        self.folder_row.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            self.folder_row,
            text="Data folder",
            width=140,
            command=self._on_select_folder,
        ).grid(row=0, column=0, padx=(0, 12), pady=4, sticky="w")

        self.folder_label = ctk.CTkLabel(
            self.folder_row,
            text="No folder selected",
            anchor="w",
            corner_radius=8,
            fg_color=("gray90", "gray20"),
            padx=12,
            pady=8,
        )
        self.folder_label.grid(row=0, column=1, sticky="ew")

        # Output folder
        self.out_row = ctk.CTkFrame(self.container, fg_color="transparent")
        self.out_row.grid(row=3, column=0, padx=20, pady=(0, 6), sticky="ew")
        self.out_row.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            self.out_row,
            text="Output folder",
            width=140,
            command=self._on_select_output,
        ).grid(row=0, column=0, padx=(0, 12), pady=4, sticky="w")

        self.output_label = ctk.CTkLabel(
            self.out_row,
            text="Default: ./outputs (next to working directory)",
            anchor="w",
            corner_radius=8,
            fg_color=("gray90", "gray20"),
            padx=12,
            pady=8,
        )
        self.output_label.grid(row=0, column=1, sticky="ew")

        # Years
        ctk.CTkLabel(
            self.container,
            text="Years to process",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=4, column=0, padx=20, pady=(10, 4), sticky="w")

        self._years_frame_inner = ctk.CTkScrollableFrame(self.container, height=100)
        self._years_frame_inner.grid(row=5, column=0, padx=20, pady=(0, 8), sticky="ew")

        year_btns = ctk.CTkFrame(self.container, fg_color="transparent")
        year_btns.grid(row=6, column=0, padx=20, pady=(0, 8), sticky="w")
        ctk.CTkButton(year_btns, text="Select all years", width=120, command=self._select_all_years).grid(
            row=0, column=0, padx=(0, 8)
        )
        ctk.CTkButton(year_btns, text="Clear years", width=100, command=self._clear_years).grid(
            row=0, column=1
        )

        # Output options
        opt_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        opt_frame.grid(row=7, column=0, padx=20, pady=(4, 8), sticky="w")

        self.var_syllables = ctk.BooleanVar(value=True)
        self.var_metadata = ctk.BooleanVar(value=True)
        self.var_metadata_only = ctk.BooleanVar(value=False)

        ctk.CTkCheckBox(
            opt_frame,
            text="Syllable Excel (segmentation + features + CNN + enrich)",
            variable=self.var_syllables,
            command=self._on_output_mode_change,
        ).grid(row=0, column=0, sticky="w", pady=2)

        ctk.CTkCheckBox(
            opt_frame,
            text="Recording metadata Excel (paths + status [+ syllable counts if syllable run])",
            variable=self.var_metadata,
            command=self._on_output_mode_change,
        ).grid(row=1, column=0, sticky="w", pady=2)

        ctk.CTkCheckBox(
            opt_frame,
            text="Metadata only (no segmentation / no CNN — fast inventory)",
            variable=self.var_metadata_only,
            command=self._on_metadata_only_toggle,
        ).grid(row=2, column=0, sticky="w", pady=2)

        # Controls
        self.controls_row = ctk.CTkFrame(self.container, fg_color="transparent")
        self.controls_row.grid(row=8, column=0, padx=20, pady=(8, 8), sticky="ew")

        self.run_btn = ctk.CTkButton(
            self.controls_row,
            text="Run pipeline",
            state="disabled",
            command=self._on_run_pipeline,
        )
        self.run_btn.grid(row=0, column=0, sticky="w")

        self.mode_switch = ctk.CTkSwitch(
            self.controls_row,
            text="Dark mode",
            command=self._toggle_dark_mode,
        )
        self.mode_switch.grid(row=0, column=1, padx=16, sticky="w")
        if ctk.get_appearance_mode().lower() == "dark":
            self.mode_switch.select()

        self.progress = ctk.CTkProgressBar(self.container)
        self.progress.grid(row=9, column=0, padx=20, pady=(4, 4), sticky="ew")
        self.progress.set(0)

        self.status_label = ctk.CTkLabel(
            self.container,
            text="Idle",
            anchor="w",
            text_color=("gray35", "gray70"),
        )
        self.status_label.grid(row=10, column=0, padx=20, pady=(0, 8), sticky="ew")

        self.log_box = ctk.CTkTextbox(self.container, height=240, wrap="word")
        self.log_box.grid(row=11, column=0, padx=20, pady=(0, 20), sticky="nsew")
        self.log_box.insert("end", "Application ready.\n")
        self.log_box.configure(state="disabled")

        self.container.grid_rowconfigure(11, weight=1)

    def _on_output_mode_change(self) -> None:
        if self.var_metadata_only.get():
            return
        if not self.var_syllables.get() and not self.var_metadata.get():
            self.var_metadata.select()

    def _on_metadata_only_toggle(self) -> None:
        if self.var_metadata_only.get():
            self.var_syllables.deselect()
            self.var_metadata.select()
        else:
            self.var_syllables.select()

    def _refresh_year_checkboxes(self) -> None:
        for w in self._years_frame_inner.winfo_children():
            w.destroy()
        self._year_check_vars.clear()
        if not self.selected_folder:
            return
        pairs = discover_year_roots(Path(self.selected_folder))
        for year_str, _ in pairs:
            var = ctk.BooleanVar(value=True)
            self._year_check_vars[year_str] = var
            ctk.CTkCheckBox(
                self._years_frame_inner,
                text=f"{year_str}",
                variable=var,
            ).pack(anchor="w", padx=4, pady=2)
        if not pairs:
            ctk.CTkLabel(self._years_frame_inner, text="(no year subfolders — single root)").pack(
                anchor="w"
            )

    def _selected_years(self) -> Optional[List[str]]:
        if not self._year_check_vars:
            return None
        sel = [y for y, v in self._year_check_vars.items() if v.get()]
        return sel if sel else None

    def _select_all_years(self) -> None:
        for v in self._year_check_vars.values():
            v.set(True)

    def _clear_years(self) -> None:
        for v in self._year_check_vars.values():
            v.set(False)

    def _toggle_dark_mode(self) -> None:
        if self.mode_switch.get() == 1:
            ctk.set_appearance_mode("Dark")
        else:
            ctk.set_appearance_mode("Light")

    def _on_select_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select data root folder")
        if not folder:
            return
        self.selected_folder = str(Path(folder))
        self.folder_label.configure(text=self.selected_folder)
        self.run_btn.configure(state="normal")
        self._refresh_year_checkboxes()
        self._set_status("Folder selected. Choose years and outputs, then run.")
        self._append_log(f"Data folder: {self.selected_folder}")

    def _on_select_output(self) -> None:
        folder = filedialog.askdirectory(title="Select output folder for Excel files")
        if not folder:
            return
        self.output_dir = str(Path(folder))
        self.output_label.configure(text=self.output_dir)
        self._append_log(f"Output folder: {self.output_dir}")

    def _on_run_pipeline(self) -> None:
        if not self.selected_folder:
            self._show_message("No folder", "Please select a data folder first.", "warning")
            return
        if self.worker_thread and self.worker_thread.is_alive():
            self._show_message("Busy", "A run is already in progress.", "info")
            return

        want_syl = self.var_syllables.get() and not self.var_metadata_only.get()
        want_meta = self.var_metadata.get()
        meta_only = self.var_metadata_only.get()
        if not want_syl and not want_meta and not meta_only:
            self._show_message("Outputs", "Select at least one output type.", "warning")
            return
        years = self._selected_years()
        if years is not None and len(years) == 0:
            self._show_message("Years", "Select at least one year, or use Select all.", "warning")
            return

        self._set_ui_running_state(True)
        self.progress.set(0)
        self._set_status("Starting…")
        self._append_log("Pipeline run started.")

        self.worker_thread = threading.Thread(
            target=self._run_pipeline_worker,
            args=(self.selected_folder, self.output_dir, years, want_syl, want_meta, meta_only),
            daemon=True,
        )
        self.worker_thread.start()

    def _run_pipeline_worker(
        self,
        folder_path: str,
        out_dir: Optional[str],
        years: Optional[List[str]],
        want_syllables: bool,
        want_metadata: bool,
        metadata_only: bool,
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
                want_syllables_xlsx=want_syllables,
                want_metadata_xlsx=want_metadata,
                metadata_only=metadata_only,
            )
            self.ui_queue.put(
                {
                    "type": "done",
                    "message": "Pipeline completed successfully.",
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
            status = str(event.get("status", "Processing…"))
            eta = event.get("eta_seconds")
            eta_f = float(eta) if eta is not None else None
            if progress >= 0:
                self.progress.set(progress)
            extra = self._format_eta(eta_f) if eta_f is not None else ""
            self._set_status(status + extra)
            self._append_log(status + extra)
            return

        if event_type == "done":
            msg = str(event.get("message", "Done"))
            output_path = event.get("output_path")
            summary = event.get("summary")
            if output_path:
                msg = f"{msg}\nPrimary output: {output_path}"
            if summary is not None:
                rep = summary.format_report()
                msg = f"{msg}\n\n{rep}"
                self._append_log(rep)
            self.progress.set(1.0)
            self._set_status("Finished. See log for summary.")
            self._append_log(msg)
            self._set_ui_running_state(False)
            self._show_message("Success", msg, "check")
            return

        if event_type == "error":
            msg = str(event.get("message", "Unknown error"))
            self._set_status(f"Error: {msg}")
            self._append_log(f"Error: {msg}")
            self._set_ui_running_state(False)
            self._show_message("Pipeline error", msg, "cancel")

    def _set_ui_running_state(self, is_running: bool) -> None:
        if is_running:
            self.select_folder_btn_off()
        else:
            self.select_folder_btn_on()

    def select_folder_btn_off(self) -> None:
        for child in self.folder_row.winfo_children():
            if isinstance(child, ctk.CTkButton):
                child.configure(state="disabled")
        for child in self.out_row.winfo_children():
            if isinstance(child, ctk.CTkButton):
                child.configure(state="disabled")
        self.run_btn.configure(state="disabled")
        self.mode_switch.configure(state="disabled")

    def select_folder_btn_on(self) -> None:
        for child in self.folder_row.winfo_children():
            if isinstance(child, ctk.CTkButton):
                child.configure(state="normal")
        for child in self.out_row.winfo_children():
            if isinstance(child, ctk.CTkButton):
                child.configure(state="normal")
        self.run_btn.configure(state="normal" if self.selected_folder else "disabled")
        self.mode_switch.configure(state="normal")

    def _set_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def _append_log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
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
    app = SegmentationApp()
    app.mainloop()
