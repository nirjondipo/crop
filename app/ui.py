"""CustomTkinter main window — lean layout, throttled progress updates."""

from __future__ import annotations

import queue
import threading
import time
from tkinter import messagebox

import customtkinter as ctk
from customtkinter import BooleanVar, IntVar, StringVar

from app.folders import is_wsl, normalize_to_linux, pick_files, pick_folder
from app.processor import (
    BatchRunner,
    CropAnchor,
    IMAGE_EXTENSIONS,
    JobSettings,
    ProgressEvent,
    ResizeMode,
    SizeSpec,
    scan_images,
)
from app.updater import UpdateInfo, check_async, download_and_install
from app.version import APP_NAME, COMPANY, DEVELOPER, __version__

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")
ctk.set_widget_scaling(1.0)
ctk.set_window_scaling(1.0)

BG = "#0e1116"
PANEL = "#161b22"
FIELD = "#1c2330"
LINE = "#2a3341"
TEXT = "#f0f3f7"
MUTED = "#8a93a3"
ACCENT = "#2f9e78"
ACCENT_H = "#268566"
OK = "#3dba7e"
WARN = "#d4a017"
ERR = "#e06c6c"

WARN_IMAGE_COUNT = 500
UI_POLL_MS = 50
PROGRESS_MIN_INTERVAL = 0.08  # seconds between progress bar redraws


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME}")
        self.geometry("980x640")
        self.minsize(880, 560)
        self.configure(fg_color=BG)

        self._runner: BatchRunner | None = None
        self._worker: threading.Thread | None = None
        self._running = False
        self._events: queue.Queue[ProgressEvent] = queue.Queue()
        self._last_progress_ui = 0.0
        self._pending_status: ProgressEvent | None = None
        self._log_buffer: list[str] = []

        self.input_var = StringVar()
        self.output_var = StringVar()
        self.sizes_var = StringVar(value="1920, 1280, 800")
        self.quality_var = IntVar(value=80)
        self.skip_upscale_var = BooleanVar(value=True)
        self.strip_exif_var = BooleanVar(value=True)
        self.include_sub_var = BooleanVar(value=False)
        # Explicit file list when source mode is Files (linux Paths)
        self._input_files: list = []
        self._input_file_labels: list[str] = []

        self._build()
        self.after(UI_POLL_MS, self._poll_events)

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_columnconfigure(0, weight=1)

        right = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(3, weight=1)

        self._build_left(left)
        self._build_right(right)

    def _label(self, parent, text: str, row: int) -> None:
        ctk.CTkLabel(
            parent,
            text=text,
            text_color=MUTED,
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        ).grid(row=row, column=0, sticky="w", padx=24, pady=(18, 6))

    def _build_left(self, parent: ctk.CTkFrame) -> None:
        title = ctk.CTkFrame(parent, fg_color="transparent")
        title.grid(row=0, column=0, sticky="ew", padx=24, pady=(22, 4))
        ctk.CTkLabel(
            title,
            text=COMPANY,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=ACCENT,
        ).pack(anchor="w")
        ctk.CTkLabel(
            title,
            text=APP_NAME,
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color=TEXT,
        ).pack(anchor="w", pady=(2, 0))
        ctk.CTkLabel(
            title,
            text=f"Batch resize → one folder per size  ·  v{__version__}",
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
        ).pack(anchor="w", pady=(2, 0))
        ctk.CTkLabel(
            title,
            text=f"Developed by {DEVELOPER}",
            font=ctk.CTkFont(size=11),
            text_color=MUTED,
        ).pack(anchor="w", pady=(4, 0))

        # Input source: folder or files
        self._label(parent, "SOURCE", 1)
        self.source_seg = ctk.CTkSegmentedButton(
            parent,
            values=["Folder", "Files"],
            command=self._on_source_change,
            height=34,
            selected_color=ACCENT,
            selected_hover_color=ACCENT_H,
            unselected_color=FIELD,
            unselected_hover_color=LINE,
        )
        self.source_seg.set("Folder")
        self.source_seg.grid(row=2, column=0, sticky="ew", padx=24)

        self.input_label = ctk.CTkLabel(
            parent,
            text="INPUT FOLDER",
            text_color=MUTED,
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        )
        self.input_label.grid(row=3, column=0, sticky="w", padx=24, pady=(14, 6))

        in_row = ctk.CTkFrame(parent, fg_color="transparent")
        in_row.grid(row=4, column=0, sticky="ew", padx=24)
        in_row.grid_columnconfigure(0, weight=1)
        self.input_entry = ctk.CTkEntry(
            in_row,
            textvariable=self.input_var,
            placeholder_text=(
                r"e.g. C:\Users\...\Pictures" if is_wsl() else "Select source images folder"
            ),
            height=38,
            fg_color=FIELD,
            border_color=LINE,
            border_width=1,
        )
        self.input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(
            in_row,
            text="Browse",
            width=88,
            height=38,
            fg_color=FIELD,
            hover_color=LINE,
            border_width=1,
            border_color=LINE,
            command=self._browse_input,
        ).grid(row=0, column=1)

        self.include_sub_cb = ctk.CTkCheckBox(
            parent,
            text="Include subfolders",
            variable=self.include_sub_var,
            text_color=MUTED,
            fg_color=ACCENT,
            hover_color=ACCENT_H,
            checkbox_height=18,
            checkbox_width=18,
        )
        self.include_sub_cb.grid(row=5, column=0, sticky="w", padx=24, pady=(10, 0))

        # Output
        self._label(parent, "OUTPUT FOLDER", 6)
        out_row = ctk.CTkFrame(parent, fg_color="transparent")
        out_row.grid(row=7, column=0, sticky="ew", padx=24)
        out_row.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(
            out_row,
            textvariable=self.output_var,
            placeholder_text=(
                r"e.g. C:\Users\...\Desktop\out" if is_wsl() else "Where size folders will be created"
            ),
            height=38,
            fg_color=FIELD,
            border_color=LINE,
            border_width=1,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(
            out_row,
            text="Browse",
            width=88,
            height=38,
            fg_color=FIELD,
            hover_color=LINE,
            border_width=1,
            border_color=LINE,
            command=self._browse_output,
        ).grid(row=0, column=1)

        # Mode
        self._label(parent, "MODE", 8)
        self.mode_seg = ctk.CTkSegmentedButton(
            parent,
            values=["Fit to width", "Exact crop"],
            command=self._on_mode_change,
            height=34,
            selected_color=ACCENT,
            selected_hover_color=ACCENT_H,
            unselected_color=FIELD,
            unselected_hover_color=LINE,
        )
        self.mode_seg.set("Fit to width")
        self.mode_seg.grid(row=9, column=0, sticky="ew", padx=24)

        self.anchor_row = ctk.CTkFrame(parent, fg_color="transparent")
        self.anchor_row.grid(row=10, column=0, sticky="ew", padx=24, pady=(10, 0))
        ctk.CTkLabel(self.anchor_row, text="Anchor", text_color=MUTED).pack(
            side="left", padx=(0, 10)
        )
        self.anchor_menu = ctk.CTkOptionMenu(
            self.anchor_row,
            values=["Center", "Top", "Bottom", "Left", "Right"],
            width=120,
            height=30,
            fg_color=FIELD,
            button_color=LINE,
            button_hover_color=ACCENT,
        )
        self.anchor_menu.set("Center")
        self.anchor_menu.pack(side="left")
        self.anchor_row.grid_remove()

        # Sizes
        self._label(parent, "SIZES", 11)
        self.sizes_hint = ctk.CTkLabel(
            parent,
            text="Widths separated by commas, e.g. 1920, 1280, 800",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
            anchor="w",
        )
        self.sizes_hint.grid(row=12, column=0, sticky="ew", padx=24)
        ctk.CTkEntry(
            parent,
            textvariable=self.sizes_var,
            height=38,
            fg_color=FIELD,
            border_color=LINE,
            border_width=1,
        ).grid(row=13, column=0, sticky="ew", padx=24, pady=(6, 0))

        # Format
        self._label(parent, "FORMAT", 14)
        fmt_row = ctk.CTkFrame(parent, fg_color="transparent")
        fmt_row.grid(row=15, column=0, sticky="ew", padx=24)
        fmt_row.grid_columnconfigure(1, weight=1)

        self.format_seg = ctk.CTkSegmentedButton(
            fmt_row,
            values=["Original", "JPG", "WebP"],
            command=self._on_format_change,
            height=34,
            dynamic_resizing=False,
            selected_color=ACCENT,
            selected_hover_color=ACCENT_H,
            unselected_color=FIELD,
            unselected_hover_color=LINE,
        )
        self.format_seg.set("WebP")
        self.format_seg.grid(row=0, column=0, columnspan=2, sticky="ew")
        try:
            self.format_seg.configure(width=320)
        except Exception:  # noqa: BLE001
            pass

        self.quality_label = ctk.CTkLabel(
            fmt_row, text="Quality 80", text_color=MUTED, width=90, anchor="w"
        )
        self.quality_label.grid(row=1, column=0, sticky="w", pady=(12, 0))
        self.quality_slider = ctk.CTkSlider(
            fmt_row,
            from_=60,
            to=95,
            number_of_steps=35,
            variable=self.quality_var,
            command=self._on_quality,
            height=16,
            progress_color=ACCENT,
            button_color=ACCENT,
            button_hover_color=ACCENT_H,
            button_length=18,
        )
        self.quality_slider.grid(row=1, column=1, sticky="ew", pady=(12, 0), padx=(8, 0))

        opts = ctk.CTkFrame(parent, fg_color="transparent")
        opts.grid(row=16, column=0, sticky="w", padx=24, pady=(14, 24))
        ctk.CTkCheckBox(
            opts,
            text="Skip upscale",
            variable=self.skip_upscale_var,
            text_color=MUTED,
            fg_color=ACCENT,
            hover_color=ACCENT_H,
            checkbox_height=18,
            checkbox_width=18,
        ).pack(side="left", padx=(0, 16))
        ctk.CTkCheckBox(
            opts,
            text="Strip EXIF",
            variable=self.strip_exif_var,
            text_color=MUTED,
            fg_color=ACCENT,
            hover_color=ACCENT_H,
            checkbox_height=18,
            checkbox_width=18,
        ).pack(side="left")

    def _build_right(self, parent: ctk.CTkFrame) -> None:
        ctk.CTkLabel(
            parent,
            text="Run",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=TEXT,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=20, pady=(28, 12))

        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=20)
        actions.grid_columnconfigure(0, weight=1)

        self.start_btn = ctk.CTkButton(
            actions,
            text="Start batch",
            height=44,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_H,
            command=self._start,
        )
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.cancel_btn = ctk.CTkButton(
            actions,
            text="Cancel",
            height=44,
            width=96,
            fg_color=FIELD,
            hover_color=LINE,
            border_width=1,
            border_color=LINE,
            text_color=MUTED,
            state="disabled",
            command=self._cancel,
        )
        self.cancel_btn.grid(row=0, column=1)

        update_row = ctk.CTkFrame(parent, fg_color="transparent")
        update_row.grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 0))
        update_row.grid_columnconfigure(0, weight=1)
        self.update_btn = ctk.CTkButton(
            update_row,
            text="Check for updates",
            height=34,
            fg_color=FIELD,
            hover_color=LINE,
            border_width=1,
            border_color=LINE,
            text_color=TEXT,
            command=self._check_updates,
        )
        self.update_btn.grid(row=0, column=0, sticky="ew")
        self.update_label = ctk.CTkLabel(
            update_row,
            text="",
            text_color=MUTED,
            anchor="w",
            font=ctk.CTkFont(size=12),
        )
        self.update_label.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        self.status_label = ctk.CTkLabel(
            parent,
            text="Ready",
            text_color=MUTED,
            anchor="w",
            font=ctk.CTkFont(size=13),
        )
        self.status_label.grid(row=3, column=0, sticky="ew", padx=20, pady=(14, 6))

        self.progress = ctk.CTkProgressBar(
            parent,
            height=8,
            progress_color=ACCENT,
            fg_color=FIELD,
            corner_radius=4,
        )
        self.progress.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 12))
        self.progress.set(0)

        self.log_box = ctk.CTkTextbox(
            parent,
            fg_color=PANEL,
            text_color=MUTED,
            font=ctk.CTkFont(family="monospace", size=12),
            border_width=1,
            border_color=LINE,
            activate_scrollbars=True,
        )
        self.log_box.grid(row=5, column=0, sticky="nsew", padx=20, pady=(0, 20))
        parent.grid_rowconfigure(5, weight=1)
        self.log_box.insert("end", "Errors and summaries appear here.\n")
        self.log_box.configure(state="disabled")

    # --- mode / format ---

    def _current_mode(self) -> ResizeMode:
        return "exact_crop" if self.mode_seg.get() == "Exact crop" else "fit_width"

    def _current_format(self) -> str:
        return {"Original": "original", "JPG": "jpg", "WebP": "webp"}.get(
            self.format_seg.get(), "webp"
        )

    def _current_anchor(self) -> CropAnchor:
        return self.anchor_menu.get().lower()  # type: ignore[return-value]

    def _source_is_files(self) -> bool:
        return self.source_seg.get() == "Files"

    def _on_source_change(self, value: str) -> None:
        if value == "Files":
            self.input_label.configure(text="INPUT FILES")
            self.include_sub_cb.grid_remove()
            self.input_entry.configure(
                placeholder_text="Browse to pick one or more images…"
            )
            if self._input_files:
                self._set_files_display()
            else:
                self.input_var.set("")
        else:
            self.input_label.configure(text="INPUT FOLDER")
            self.include_sub_cb.grid()
            self.input_entry.configure(
                placeholder_text=(
                    r"e.g. C:\Users\...\Pictures" if is_wsl() else "Select source images folder"
                )
            )
            # Keep folder path if user typed one; clear file-selection summary
            if self._input_files and "file" in self.input_var.get().lower():
                self.input_var.set("")
            self._input_files = []
            self._input_file_labels = []

    def _set_files_display(self) -> None:
        n = len(self._input_files)
        if n == 0:
            self.input_var.set("")
            return
        first = self._input_file_labels[0]
        if n == 1:
            self.input_var.set(first)
        else:
            self.input_var.set(f"{n} files selected · {first}")

    def _on_mode_change(self, value: str) -> None:
        if value == "Exact crop":
            self.anchor_row.grid()
            self.sizes_hint.configure(
                text="Width×height pairs, e.g. 1920x1080, 800x600"
            )
            if "," not in self.sizes_var.get() or "x" not in self.sizes_var.get().lower():
                self.sizes_var.set("1920x1080, 1280x720, 800x600")
        else:
            self.anchor_row.grid_remove()
            self.sizes_hint.configure(
                text="Widths separated by commas, e.g. 1920, 1280, 800"
            )
            if "x" in self.sizes_var.get().lower():
                self.sizes_var.set("1920, 1280, 800")

    def _on_format_change(self, value: str) -> None:
        state = "disabled" if value == "Original" else "normal"
        self.quality_slider.configure(state=state)

    def _on_quality(self, value: float) -> None:
        self.quality_label.configure(text=f"Quality {int(value)}")

    def _with_window_aside(self, fn):
        """On WSL, hide Crop so the Windows dialog is not covered by the WSLg window."""
        if not is_wsl():
            return fn()
        try:
            self.update_idletasks()
            self.withdraw()
            self.update()
        except Exception:  # noqa: BLE001
            pass
        try:
            return fn()
        finally:
            try:
                self.deiconify()
                self.lift()
                self.focus_force()
                self.attributes("-topmost", True)
                self.after(200, lambda: self.attributes("-topmost", False))
            except Exception:  # noqa: BLE001
                pass

    def _browse_input(self) -> None:
        if self._source_is_files():
            initial = None
            if self._input_files:
                initial = str(self._input_files[0].parent)
            elif self.input_var.get().strip() and "files selected" not in self.input_var.get().lower():
                try:
                    p = normalize_to_linux(self.input_var.get())
                    initial = str(p.parent if p.suffix else p)
                except Exception:  # noqa: BLE001
                    initial = None

            def _pick():
                return pick_files(title="Select image files", initial_linux=initial)

            picked = self._with_window_aside(_pick)
            if not picked:
                return
            files = []
            labels = []
            for display, linux in picked:
                if linux.suffix.lower() in IMAGE_EXTENSIONS:
                    files.append(linux)
                    labels.append(display)
            if not files:
                messagebox.showerror("Input", "No supported image files in that selection.")
                return
            self._input_files = files
            self._input_file_labels = labels
            self._set_files_display()
            return

        current = self.input_var.get().strip()
        initial = str(normalize_to_linux(current)) if current else None

        def _pick_folder():
            return pick_folder(title="Select input folder", initial_linux=initial)

        picked = self._with_window_aside(_pick_folder)
        if picked:
            display, _linux = picked
            self.input_var.set(display)
            self._input_files = []
            self._input_file_labels = []

    def _browse_output(self) -> None:
        current = self.output_var.get().strip()
        initial = str(normalize_to_linux(current)) if current else None

        def _pick_folder():
            return pick_folder(title="Select output folder", initial_linux=initial)

        picked = self._with_window_aside(_pick_folder)
        if picked:
            display, _linux = picked
            self.output_var.set(display)

    def _parse_sizes(self) -> list[SizeSpec] | None:
        raw = self.sizes_var.get().strip()
        if not raw:
            messagebox.showerror("Sizes", "Enter at least one size.")
            return None

        mode = self._current_mode()
        specs: list[SizeSpec] = []
        seen: set[str] = set()

        for part in raw.replace(";", ",").split(","):
            token = part.strip().lower().replace("×", "x")
            if not token:
                continue
            try:
                if mode == "fit_width":
                    if "x" in token:
                        messagebox.showerror(
                            "Sizes",
                            f"Fit to width needs widths only (got “{part.strip()}”).\n"
                            "Example: 1920, 1280, 800",
                        )
                        return None
                    w = int(token)
                    if w <= 0:
                        raise ValueError
                    spec = SizeSpec(width=w)
                else:
                    if "x" not in token:
                        messagebox.showerror(
                            "Sizes",
                            f"Exact crop needs width×height (got “{part.strip()}”).\n"
                            "Example: 1920x1080, 800x600",
                        )
                        return None
                    w_s, h_s = token.split("x", 1)
                    w, h = int(w_s.strip()), int(h_s.strip())
                    if w <= 0 or h <= 0:
                        raise ValueError
                    spec = SizeSpec(width=w, height=h)
            except ValueError:
                messagebox.showerror("Sizes", f"Invalid size: “{part.strip()}”")
                return None

            name = spec.folder_name(mode)
            if name not in seen:
                seen.add(name)
                specs.append(spec)

        if not specs:
            messagebox.showerror("Sizes", "Enter at least one size.")
            return None
        return specs

    def _start(self) -> None:
        if self._running:
            return

        if not self.output_var.get().strip():
            messagebox.showerror("Output", "Choose an output folder.")
            return

        output_path = normalize_to_linux(self.output_var.get())
        input_folder = None
        input_files = None

        if self._source_is_files():
            if not self._input_files:
                messagebox.showerror("Input", "Browse and select one or more image files.")
                return
            input_files = list(self._input_files)
            images = [p for p in input_files if p.is_file()]
            if not images:
                messagebox.showerror("Input", "Selected files are missing or unsupported.")
                return
        else:
            if not self.input_var.get().strip():
                messagebox.showerror("Input", "Choose a valid input folder.")
                return
            input_folder = normalize_to_linux(self.input_var.get())
            if not input_folder.is_dir():
                messagebox.showerror(
                    "Input",
                    f"Choose a valid input folder.\n(Resolved to: {input_folder})",
                )
                return
            try:
                if input_folder.resolve() == output_path.resolve():
                    messagebox.showerror("Folders", "Input and output must be different.")
                    return
            except OSError:
                pass
            images = scan_images(input_folder, self.include_sub_var.get())
            if not images:
                messagebox.showerror("Input", "No supported images found in that folder.")
                return

        sizes = self._parse_sizes()
        if not sizes:
            return

        if len(images) > WARN_IMAGE_COUNT:
            if not messagebox.askyesno(
                "Large batch",
                f"Found {len(images)} images (over {WARN_IMAGE_COUNT}). Continue?",
            ):
                return

        try:
            output_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Output", f"Cannot create output folder:\n{exc}")
            return

        settings = JobSettings(
            output_folder=output_path,
            mode=self._current_mode(),
            sizes=sizes,
            format=self._current_format(),  # type: ignore[arg-type]
            input_folder=input_folder,
            input_files=input_files,
            quality=int(self.quality_var.get()),
            crop_anchor=self._current_anchor(),
            skip_upscale=self.skip_upscale_var.get(),
            strip_exif=self.strip_exif_var.get(),
            include_subfolders=self.include_sub_var.get(),
        )

        self._running = True
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress.set(0)
        self._clear_log()
        self._log(f"Starting · {len(images)} images · {len(sizes)} sizes")
        self.status_label.configure(text="Working…", text_color=MUTED)

        self._runner = BatchRunner(settings=settings, on_progress=self._enqueue_event)
        self._worker = threading.Thread(target=self._runner.run, daemon=True)
        self._worker.start()

    def _cancel(self) -> None:
        if self._runner:
            self._runner.cancel()
            self.status_label.configure(text="Cancelling…", text_color=WARN)

    def _check_updates(self) -> None:
        self.update_btn.configure(state="disabled", text="Checking…")
        self.update_label.configure(text="Looking for updates on GitHub…", text_color=MUTED)

        def _done(info: UpdateInfo | None, err: Exception | None) -> None:
            self.after(0, lambda: self._on_update_result(info, err))

        check_async(_done)

    def _on_update_result(self, info: UpdateInfo | None, err: Exception | None) -> None:
        self.update_btn.configure(state="normal", text="Check for updates")
        if err is not None:
            self.update_label.configure(text=f"Update check failed: {err}", text_color=WARN)
            return
        if info is None or info.channel == "none":
            self.update_label.configure(
                text="No GitHub release found (publish a release with CropSetup.exe).",
                text_color=MUTED,
            )
            return
        if not info.available:
            self.update_label.configure(text=f"Up to date (v{info.current})", text_color=OK)
            return

        msg = (
            f"Update available: v{info.current} → v{info.latest}\n\n"
            f"{info.notes or 'New version ready.'}\n\n"
            "Download the installer now?\n"
            "This app will close so Setup can replace files, then the installer opens."
        )
        if not messagebox.askyesno(f"Update {APP_NAME}", msg):
            self.update_label.configure(
                text=f"Update available: v{info.latest} — click again to install",
                text_color=WARN,
            )
            return

        self.update_btn.configure(state="disabled", text="Downloading…")
        self.update_label.configure(text="Downloading installer…", text_color=MUTED)

        def _install():
            try:
                path = download_and_install(
                    info,
                    on_status=lambda s: self.after(
                        0, lambda: self.update_label.configure(text=s, text_color=MUTED)
                    ),
                    quit_first=True,
                )
                self.after(0, lambda: self._on_update_downloaded(path, None))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._on_update_downloaded(None, exc))

        threading.Thread(target=_install, daemon=True).start()

    def _on_update_downloaded(self, path, err: Exception | None) -> None:
        if err is not None:
            self.update_btn.configure(state="normal", text="Check for updates")
            self.update_label.configure(text=f"Download failed: {err}", text_color=WARN)
            messagebox.showerror("Update", f"Could not download update:\n{err}")
            return
        self.update_label.configure(
            text="Closing so Setup can install…",
            text_color=OK,
        )
        messagebox.showinfo(
            f"Update {APP_NAME}",
            "Download complete.\n\n"
            "This window will close now.\n"
            "The installer opens automatically afterward — finish Setup, then reopen the app.",
        )
        # Quit so Crop.exe unlocks; helper starts Setup after exit
        self.after(200, self.destroy)

    def _enqueue_event(self, event: ProgressEvent) -> None:
        self._events.put(event)

    def _poll_events(self) -> None:
        """Drain queue on UI thread; throttle redraws so the window stays responsive."""
        latest: ProgressEvent | None = None
        log_lines: list[str] = []

        try:
            while True:
                event = self._events.get_nowait()
                latest = event
                # Only log meaningful lines — not every successful file
                if event.level in ("error", "info", "skip") and event.message:
                    if event.level == "info" and event.current > 0 and not event.done:
                        # skip noisy mid-run info except start/done
                        if "Found" in event.message or event.done:
                            log_lines.append(event.message)
                    elif event.level != "info" or event.done or "Found" in event.message:
                        prefix = {"error": "✗", "skip": "–", "info": "·"}.get(
                            event.level, "·"
                        )
                        log_lines.append(f"{prefix} {event.message}")
                if event.done and event.message and event.level == "info":
                    # ensure final summary is logged
                    if event.message not in "".join(log_lines):
                        log_lines.append(f"· {event.message}")
        except queue.Empty:
            pass

        if log_lines:
            # dedupe consecutive duplicates
            unique: list[str] = []
            for line in log_lines:
                if not unique or unique[-1] != line:
                    unique.append(line)
            self._log("\n".join(unique))

        if latest is not None:
            now = time.monotonic()
            should_draw = (
                latest.done
                or latest.level == "error"
                or (now - self._last_progress_ui) >= PROGRESS_MIN_INTERVAL
            )
            if should_draw:
                self._last_progress_ui = now
                if latest.total > 0:
                    self.progress.set(latest.current / latest.total)
                    self.status_label.configure(
                        text=(
                            f"{latest.current}/{latest.total}"
                            + (f"  ·  {latest.filename}" if latest.filename else "")
                            + f"  ·  errors {latest.errors}"
                        ),
                        text_color=TEXT,
                    )
                if latest.done:
                    self._running = False
                    self.start_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
                    color = OK if latest.errors == 0 else WARN
                    self.status_label.configure(
                        text=latest.message or "Done.",
                        text_color=color,
                    )
                    if latest.total > 0:
                        self.progress.set(1.0)

        self.after(UI_POLL_MS, self._poll_events)

    def _clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _log(self, message: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")


def run_app() -> None:
    app = App()

    def _on_close() -> None:
        # Stop any batch worker, tell control API we exited, then quit cleanly.
        try:
            if app._runner is not None:
                app._runner.cancel()
        except Exception:  # noqa: BLE001
            pass
        try:
            import json
            import os
            import urllib.request

            payload = json.dumps({"pid": os.getpid()}).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:18765/exited",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=1.5)
        except Exception:  # noqa: BLE001
            pass
        try:
            app.destroy()
        except Exception:  # noqa: BLE001
            pass

    app.protocol("WM_DELETE_WINDOW", _on_close)
    app.mainloop()
    # If mainloop ended without WM_DELETE (rare), still notify
    try:
        import json
        import os
        import urllib.request

        payload = json.dumps({"pid": os.getpid()}).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:18765/exited",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=1.0)
    except Exception:  # noqa: BLE001
        pass
