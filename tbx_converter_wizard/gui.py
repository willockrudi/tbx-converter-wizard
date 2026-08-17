"""TBX Converter Wizard - pick file(s), or rip a DVD, hit Run.

Encodes to TBX's "tbx_broadcast" MP4 profile and drops the result into a
local output folder (config.OUTPUT_DIR). Getting that folder onto the
actual TBX box is entirely up to you (USB drive, network share, whatever)
- this app has no network awareness of TBX at all.
"""

from __future__ import annotations

import queue
import shutil
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import config, discovery, encode, engine

APP_TITLE = "TBX Converter Wizard"


def _dvdbackup_available() -> bool:
    return shutil.which("dvdbackup") is not None and shutil.which("lsdvd") is not None


# Either backend counts - dvdbackup+lsdvd (Linux only) or MakeMKV (any
# platform, including Windows, where it's the only option available).
DVD_TOOLS_AVAILABLE = _dvdbackup_available() or discovery.find_makemkvcon() is not None


def _probe_duration_seconds(path: Path) -> float:
    """Best-effort file duration via ffprobe - only used to preserve the
    existing "longest included title is primary" movie-mode heuristic when
    multiple files are selected. Falls back to 0 (no reordering) if ffprobe
    is missing or the file can't be probed - never blocks the flow."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=15,
            creationflags=config.NO_WINDOW,
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


class ConverterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("820x680")
        self.minsize(700, 580)

        # Shared across both tabs - one worker at a time, one log, one
        # output folder. Background threads must never touch Tk widgets or
        # call self.after() directly - only the main-thread poller below
        # may do that. Worker threads just flip these plain flags (atomic
        # under the GIL) or push to log_queue.
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self._need_recompute = False
        self._need_scan_button_reset = False
        self._need_worker_done = False
        self._need_drive_refresh = False
        self._scanning = False
        # Last drive-scan failure, kept so it can be repeated when the user
        # actually tries to scan a disc. The message is logged once when the
        # scan fails - typically at startup, where it scrolls away long
        # before anyone clicks Scan Disc and wonders why nothing works.
        self._last_drive_error: str | None = None

        self.output_dir = tk.StringVar(value=str(config.OUTPUT_DIR))

        self._build_widgets()
        self._on_convert_mode_change()
        self._on_dvd_mode_change()
        if DVD_TOOLS_AVAILABLE:
            self._refresh_drives()
        self.after(200, self._poll_worker_state)

    # -- top-level layout -----------------------------------------------------

    def _build_widgets(self):
        out_frame = ttk.Frame(self)
        out_frame.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(out_frame, text="Output folder:").pack(side="left")
        ttk.Entry(out_frame, textvariable=self.output_dir, state="readonly").pack(
            side="left", fill="x", expand=True, padx=4)
        ttk.Button(out_frame, text="Change...", command=self._on_change_output_dir).pack(
            side="left")

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.convert_frame = ttk.Frame(notebook)
        self.dvd_frame = ttk.Frame(notebook)
        notebook.add(self.convert_frame, text="Convert File")
        notebook.add(self.dvd_frame, text="Rip DVD" if DVD_TOOLS_AVAILABLE else "Rip DVD (unavailable)")
        if not DVD_TOOLS_AVAILABLE:
            notebook.tab(self.dvd_frame, state="disabled")

        self._build_convert_tab(self.convert_frame)
        self._build_dvd_tab(self.dvd_frame)

        self.log_text = tk.Text(self, height=10, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _on_change_output_dir(self):
        chosen = filedialog.askdirectory(initialdir=self.output_dir.get())
        if chosen:
            config.save_output_dir(Path(chosen))
            self.output_dir.set(chosen)

    # -- Convert File tab -----------------------------------------------------

    def _build_convert_tab(self, parent):
        pad = {"padx": 8, "pady": 4}

        self.convert_files: list[Path] = []
        self.convert_items: list[engine.PlannedTitle] = []
        self.convert_mode = tk.StringVar(value="movie")
        self.convert_title = tk.StringVar()
        self.convert_year = tk.StringVar()
        self.convert_show = tk.StringVar()
        self.convert_season = tk.StringVar()
        self.convert_start_episode = tk.StringVar()

        pick_frame = ttk.Frame(parent)
        pick_frame.pack(fill="x", **pad)
        ttk.Button(pick_frame, text="Choose File(s)...", command=self._on_choose_files).pack(
            side="left")
        self.convert_file_count_label = ttk.Label(pick_frame, text="No files selected.")
        self.convert_file_count_label.pack(side="left", padx=8)

        mode_frame = ttk.LabelFrame(parent, text="Mode")
        mode_frame.pack(fill="x", **pad)
        ttk.Radiobutton(mode_frame, text="Movie", variable=self.convert_mode, value="movie",
                         command=self._on_convert_mode_change).pack(side="left", padx=8)
        ttk.Radiobutton(mode_frame, text="TV Show", variable=self.convert_mode, value="tv",
                         command=self._on_convert_mode_change).pack(side="left", padx=8)

        self.convert_movie_frame = ttk.Frame(parent)
        ttk.Label(self.convert_movie_frame, text="Title:").grid(row=0, column=0, sticky="e")
        ttk.Entry(self.convert_movie_frame, textvariable=self.convert_title, width=32).grid(
            row=0, column=1, padx=4)
        ttk.Label(self.convert_movie_frame, text="Year:").grid(row=0, column=2, sticky="e")
        ttk.Entry(self.convert_movie_frame, textvariable=self.convert_year, width=8).grid(
            row=0, column=3, padx=4)

        self.convert_tv_frame = ttk.Frame(parent)
        ttk.Label(self.convert_tv_frame, text="Show:").grid(row=0, column=0, sticky="e")
        ttk.Entry(self.convert_tv_frame, textvariable=self.convert_show, width=26).grid(
            row=0, column=1, padx=4)
        ttk.Label(self.convert_tv_frame, text="Season:").grid(row=0, column=2, sticky="e")
        ttk.Entry(self.convert_tv_frame, textvariable=self.convert_season, width=5).grid(
            row=0, column=3, padx=4)
        ttk.Label(self.convert_tv_frame, text="Start Ep:").grid(row=0, column=4, sticky="e")
        ttk.Entry(self.convert_tv_frame, textvariable=self.convert_start_episode, width=5).grid(
            row=0, column=5, padx=4)

        cols = ("source", "filename")
        self.convert_tree = ttk.Treeview(parent, columns=cols, show="headings", height=8,
                                          selectmode="none")
        self.convert_tree.heading("source", text="Source file")
        self.convert_tree.heading("filename", text="Output filename")
        self.convert_tree.column("source", width=320, anchor="w")
        self.convert_tree.column("filename", width=380, anchor="w")
        self.convert_tree.pack(fill="both", expand=True, **pad)

        action_frame = ttk.Frame(parent)
        action_frame.pack(fill="x", **pad)
        self.convert_run_button = ttk.Button(action_frame, text="Run", command=self._on_convert_run,
                                              state="disabled")
        self.convert_run_button.pack(side="left")
        self.convert_cancel_button = ttk.Button(action_frame, text="Cancel",
                                                 command=self._on_cancel, state="disabled")
        self.convert_cancel_button.pack(side="left", padx=4)

        # Keep the Output filename column in step with what's typed. Without
        # this, filenames were only ever recomputed on a mode-radio click or
        # when a file-probe finished - so the normal order of operations
        # (choose files, then type the title) left the preview, and the actual
        # output, frozen on the "Untitled (0)" fallback from before anything
        # was typed. Registered last, once every widget above exists, since a
        # trace can fire as soon as it's attached.
        for var in (self.convert_title, self.convert_year, self.convert_show,
                    self.convert_season, self.convert_start_episode):
            var.trace_add("write", lambda *_: self._recompute_convert())

    def _on_convert_mode_change(self):
        if self.convert_mode.get() == "movie":
            self.convert_tv_frame.pack_forget()
            self.convert_movie_frame.pack(fill="x", padx=8, pady=4)
        else:
            self.convert_movie_frame.pack_forget()
            self.convert_tv_frame.pack(fill="x", padx=8, pady=4)
        self._recompute_convert()

    def _on_choose_files(self):
        paths = filedialog.askopenfilenames(title="Choose file(s) to convert")
        if not paths:
            return
        self.convert_files = [Path(p) for p in paths]
        self.convert_file_count_label.configure(
            text=f"{len(self.convert_files)} file(s) selected.")
        self._log(f"Selected {len(self.convert_files)} file(s), probing duration...")

        def work():
            items = []
            for i, path in enumerate(self.convert_files):
                length = _probe_duration_seconds(path)
                items.append(engine.PlannedTitle(title_number=i, length_seconds=length))
            self.convert_items = items
            self._need_recompute = True

        threading.Thread(target=work, daemon=True).start()

    def _convert_current_meta(self) -> dict:
        if self.convert_mode.get() == "movie":
            return {"title": self.convert_title.get().strip() or "Untitled",
                     "year": int(self.convert_year.get() or 0)}
        return {"show": self.convert_show.get().strip() or "Untitled",
                 "season": int(self.convert_season.get() or 0),
                 "start_episode": int(self.convert_start_episode.get() or 1)}

    def _validate_convert_meta(self) -> tuple[bool, str]:
        if self.convert_mode.get() == "movie":
            if not self.convert_title.get().strip():
                return False, "Enter a movie title."
            if not self.convert_year.get().strip().isdigit():
                return False, "Enter a valid year."
        else:
            if not self.convert_show.get().strip():
                return False, "Enter a show name."
            if not self.convert_season.get().strip().isdigit():
                return False, "Enter a valid season number."
            if not self.convert_start_episode.get().strip().isdigit():
                return False, "Enter a valid start episode number."
        return True, ""

    def _recompute_convert(self):
        try:
            engine.recompute_filenames(self.convert_mode.get(), self.convert_items,
                                        **self._convert_current_meta())
        except (ValueError, KeyError):
            pass

        self.convert_tree.delete(*self.convert_tree.get_children())
        for i, it in enumerate(self.convert_items):
            source = self.convert_files[i].name if i < len(self.convert_files) else ""
            self.convert_tree.insert("", "end", iid=str(i), values=(source, it.filename or ""))

        self.convert_run_button.configure(
            state="normal" if self.convert_items else "disabled")

    def _on_convert_run(self):
        ok, msg = self._validate_convert_meta()
        if not ok:
            messagebox.showerror(APP_TITLE, msg)
            return
        if not self.convert_items:
            return

        # Authoritative recompute: the live traces above keep the preview
        # current, but Run must never depend on a trace having fired - paste,
        # IME input and programmatic sets all reach the entries by different
        # routes. Cheap, and it makes "what you see is what gets written" a
        # property of Run itself rather than of the preview machinery.
        self._recompute_convert()

        self.cancel_event.clear()
        self.convert_run_button.configure(state="disabled")
        self.convert_cancel_button.configure(state="normal")

        files = list(self.convert_files)
        items = list(self.convert_items)

        def work():
            try:
                for path, item in zip(files, items):
                    if self.cancel_event.is_set():
                        self._log("Cancelled.")
                        break
                    if not item.filename:
                        continue
                    try:
                        engine.convert_file(path, item.filename, self._log,
                                             item.length_seconds)
                    except encode.EncodeError as exc:
                        self._log(f"FAILED: {exc}")
                self._log("--- conversion finished ---")
            except Exception as exc:  # noqa: BLE001 - last-resort UI safety net
                self._log(f"Conversion failed unexpectedly: {exc!r}")
            finally:
                self._need_worker_done = True

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    # -- Rip DVD tab ------------------------------------------------------------

    def _build_dvd_tab(self, parent):
        pad = {"padx": 8, "pady": 4}

        if not DVD_TOOLS_AVAILABLE:
            ttk.Label(
                parent,
                text="DVD ripping needs MakeMKV (any platform, including Windows) "
                     "or dvdbackup + lsdvd (Linux only), and none were found on "
                     "this system.\nInstall MakeMKV from makemkv.com and restart "
                     "the app, or use the Convert File tab instead.",
                foreground="#a33", wraplength=600, justify="left",
            ).pack(padx=16, pady=16, anchor="w")
            return

        self.items: list[engine.PlannedTitle] = []
        self._drive_options: dict[str, str] = {}  # label -> device string (path or MakeMKV drive index)
        self.device = tk.StringVar()
        self.dvd_mode = tk.StringVar(value="movie")
        self.movie_title = tk.StringVar()
        self.movie_year = tk.StringVar()
        self.tv_show = tk.StringVar()
        self.tv_season = tk.StringVar()
        self.tv_start_episode = tk.StringVar()
        self.min_minutes = tk.StringVar(value=str(config.DEFAULT_MIN_MINUTES["movie"]))
        has_dvdbackup = _dvdbackup_available()
        ripper_values = ["dvdbackup", "makemkv"] if has_dvdbackup else ["makemkv"]
        self.ripper = tk.StringVar(value=ripper_values[0])

        top = ttk.Frame(parent)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Drive:").pack(side="left")
        self.drive_combo = ttk.Combobox(top, textvariable=self.device, width=40, state="readonly")
        self.drive_combo.pack(side="left", padx=4)
        ttk.Button(top, text="Refresh Drives", command=self._refresh_drives).pack(side="left", padx=4)
        self.scan_button = ttk.Button(top, text="Scan Disc", command=self._on_scan)
        self.scan_button.pack(side="left", padx=4)
        ttk.Label(top, text="Ripper:").pack(side="left", padx=(16, 0))
        ripper_combo = ttk.Combobox(top, textvariable=self.ripper, values=ripper_values,
                                     width=10, state="readonly")
        ripper_combo.pack(side="left", padx=4)
        # ttk.Combobox has no live command= for the textvariable itself -
        # the two rippers enumerate disjoint drive sets, so switching
        # ripper must re-scan drives.
        ripper_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_drives())

        mode_frame = ttk.LabelFrame(parent, text="Mode")
        mode_frame.pack(fill="x", **pad)
        ttk.Radiobutton(mode_frame, text="Movie", variable=self.dvd_mode, value="movie",
                         command=self._on_dvd_mode_change).pack(side="left", padx=8)
        ttk.Radiobutton(mode_frame, text="TV Show", variable=self.dvd_mode, value="tv",
                         command=self._on_dvd_mode_change).pack(side="left", padx=8)

        self.movie_frame = ttk.Frame(parent)
        ttk.Label(self.movie_frame, text="Title:").grid(row=0, column=0, sticky="e")
        ttk.Entry(self.movie_frame, textvariable=self.movie_title, width=32).grid(
            row=0, column=1, padx=4)
        ttk.Label(self.movie_frame, text="Year:").grid(row=0, column=2, sticky="e")
        ttk.Entry(self.movie_frame, textvariable=self.movie_year, width=8).grid(
            row=0, column=3, padx=4)

        self.tv_frame = ttk.Frame(parent)
        ttk.Label(self.tv_frame, text="Show:").grid(row=0, column=0, sticky="e")
        ttk.Entry(self.tv_frame, textvariable=self.tv_show, width=26).grid(
            row=0, column=1, padx=4)
        ttk.Label(self.tv_frame, text="Season:").grid(row=0, column=2, sticky="e")
        ttk.Entry(self.tv_frame, textvariable=self.tv_season, width=5).grid(
            row=0, column=3, padx=4)
        ttk.Label(self.tv_frame, text="Start Ep:").grid(row=0, column=4, sticky="e")
        ttk.Entry(self.tv_frame, textvariable=self.tv_start_episode, width=5).grid(
            row=0, column=5, padx=4)

        thresh_frame = ttk.Frame(parent)
        thresh_frame.pack(fill="x", **pad)
        ttk.Label(thresh_frame, text="Min length to include (minutes):").pack(side="left")
        ttk.Entry(thresh_frame, textvariable=self.min_minutes, width=6).pack(side="left", padx=4)
        ttk.Button(thresh_frame, text="Apply", command=self._recompute_dvd).pack(side="left", padx=4)

        self.movie_frame.pack(fill="x", padx=8, pady=4)

        cols = ("include", "title", "length", "filename")
        self.tree = ttk.Treeview(parent, columns=cols, show="headings", height=8,
                                  selectmode="none")
        headers = {"include": "Include", "title": "Title#", "length": "Length (min)",
                   "filename": "Output filename"}
        widths = {"include": 60, "title": 60, "length": 100, "filename": 380}
        for c in cols:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=widths[c], anchor="w")
        self.tree.pack(fill="both", expand=True, **pad)
        self.tree.bind("<Button-1>", self._on_tree_click)
        ttk.Label(parent, text="Click a row's Include column to toggle whether it's ripped.",
                  foreground="#666").pack(anchor="w", padx=8)

        action_frame = ttk.Frame(parent)
        action_frame.pack(fill="x", **pad)
        self.rip_button = ttk.Button(action_frame, text="Run", command=self._on_rip,
                                      state="disabled")
        self.rip_button.pack(side="left")
        self.dvd_cancel_button = ttk.Button(action_frame, text="Cancel", command=self._on_cancel,
                                             state="disabled")
        self.dvd_cancel_button.pack(side="left", padx=4)

        # Same live-preview traces as the Convert File tab. This tab could at
        # least be nudged into recomputing via the Apply button next to the
        # minimum-length box, which is not a thing anyone would guess.
        for var in (self.movie_title, self.movie_year, self.tv_show,
                    self.tv_season, self.tv_start_episode):
            var.trace_add("write", lambda *_: self._recompute_dvd())

    def _refresh_drives(self):
        """Populate the drive dropdown for whichever ripper is currently
        selected. Runs on a background thread since MakeMKV's own drive
        scan shells out to makemkvcon and can take a few seconds."""
        ripper = self.ripper.get()
        self.drive_combo.configure(state="disabled")

        def work():
            options: dict[str, str] = {}
            try:
                if ripper == "dvdbackup":
                    for path in sorted(Path("/dev").glob("sr*")):
                        options[str(path)] = str(path)
                else:
                    for d in discovery.list_makemkv_drives():
                        label = f"{d.device_path or f'Drive {d.index}'} - {d.name}"
                        if d.disc_title:
                            label += f" ({d.disc_title})"
                        options[label] = str(d.index)
            except discovery.DiscoveryError as exc:
                self._last_drive_error = str(exc)
                self._log(f"Drive scan failed: {exc}")
            else:
                self._last_drive_error = None
            self._drive_options = options
            self._need_drive_refresh = True

        threading.Thread(target=work, daemon=True).start()

    def _resolve_device(self) -> str | None:
        """Map the drive dropdown's display label back to the device string the
        selected ripper actually needs: an OS path for dvdbackup, a MakeMKV
        drive index for makemkv.

        Returns None when the dropdown is empty or stale, which is the normal
        state after a failed drive scan (an expired MakeMKV build, say). That
        used to fall through as an empty string and surface from deep inside
        the scan thread as a bare `ValueError: invalid literal for int()` -
        technically accurate, entirely unhelpful."""
        device = self._drive_options.get(self.device.get(), "").strip()
        if not device:
            return None
        if self.ripper.get() == "makemkv" and not device.isdigit():
            return None
        return device

    def _no_drive_message(self) -> str:
        msg = ("No drive selected.\n\nClick Refresh Drives, then pick one from the "
               "Drive dropdown.")
        if self._last_drive_error:
            msg += f"\n\nThe last drive scan failed with:\n{self._last_drive_error}"
        return msg

    def _on_dvd_mode_change(self):
        if not DVD_TOOLS_AVAILABLE:
            return
        if self.dvd_mode.get() == "movie":
            self.tv_frame.pack_forget()
            self.movie_frame.pack(fill="x", padx=8, pady=4)
            self.min_minutes.set(str(config.DEFAULT_MIN_MINUTES["movie"]))
        else:
            self.movie_frame.pack_forget()
            self.tv_frame.pack(fill="x", padx=8, pady=4)
            self.min_minutes.set(str(config.DEFAULT_MIN_MINUTES["tv"]))
        self._recompute_dvd()

    def _min_minutes(self) -> float:
        try:
            return float(self.min_minutes.get())
        except ValueError:
            return config.DEFAULT_MIN_MINUTES[self.dvd_mode.get()]

    def _dvd_current_meta(self) -> dict:
        if self.dvd_mode.get() == "movie":
            return {"title": self.movie_title.get().strip() or "Untitled",
                     "year": int(self.movie_year.get() or 0)}
        return {"show": self.tv_show.get().strip() or "Untitled",
                 "season": int(self.tv_season.get() or 0),
                 "start_episode": int(self.tv_start_episode.get() or 1)}

    def _validate_dvd_meta(self) -> tuple[bool, str]:
        if self.dvd_mode.get() == "movie":
            if not self.movie_title.get().strip():
                return False, "Enter a movie title."
            if not self.movie_year.get().strip().isdigit():
                return False, "Enter a valid year."
        else:
            if not self.tv_show.get().strip():
                return False, "Enter a show name."
            if not self.tv_season.get().strip().isdigit():
                return False, "Enter a valid season number."
            if not self.tv_start_episode.get().strip().isdigit():
                return False, "Enter a valid start episode number."
        return True, ""

    def _on_scan(self):
        if self._scanning:
            return  # ignore repeat clicks/synthetic double-fires while a scan is in flight

        # Checked before the button is disabled, so bailing out here can't
        # leave Scan Disc greyed out with no scan running to re-enable it.
        device = self._resolve_device()
        if device is None:
            messagebox.showerror(APP_TITLE, self._no_drive_message())
            return

        self._scanning = True
        self.scan_button.configure(state="disabled")

        ripper = self.ripper.get()
        threshold = self._min_minutes() * 60  # read Tk vars on the main thread only
        self.tree.delete(*self.tree.get_children())
        self.items = []
        self.rip_button.configure(state="disabled")
        self._log(f"Scanning {self.device.get()} ... (this can take a minute or two)")

        def work():
            # Safety net: any unexpected exception here must still reach the
            # log and reset the button, or the UI looks permanently "stuck"
            # with no clue why (this is exactly how a real bug manifested
            # during testing - an uncaught UnicodeDecodeError silently killed
            # this thread and left Scan Disc disabled forever).
            try:
                if ripper == "makemkv":
                    titles = discovery.discover_titles_makemkv(int(device))
                else:
                    titles = discovery.discover_titles(device)
                self.items = [
                    engine.PlannedTitle(t.number, t.length_seconds,
                                         include=t.length_seconds >= threshold)
                    for t in titles
                ]
                self._log(f"Found {len(self.items)} title(s).")
                # A scan that finds titles but auto-includes none leaves Run
                # greyed out with nothing on screen explaining why - and the
                # movie-mode default of 40 min excludes anything short, which
                # is most TV episodes and plenty of home-burned discs.
                if self.items and not any(it.include for it in self.items):
                    longest = max(it.length_seconds for it in self.items) / 60
                    self._log(
                        f"  ...but none reach the {threshold / 60:.0f} min minimum "
                        f"(longest is {longest:.1f} min), so nothing is selected and Run "
                        "stays disabled. Lower 'Min length to include' and click Apply, "
                        "or click a row's Include cell to select it by hand."
                    )
                self._need_recompute = True
            except discovery.DiscoveryError as exc:
                self._log(f"Scan failed: {exc}")
            except Exception as exc:  # noqa: BLE001 - last-resort UI safety net
                self._log(f"Scan failed unexpectedly: {exc!r}")
            finally:
                self._need_scan_button_reset = True

        threading.Thread(target=work, daemon=True).start()

    def _recompute_dvd(self):
        try:
            engine.recompute_filenames(self.dvd_mode.get(), self.items, **self._dvd_current_meta())
        except (ValueError, KeyError):
            pass

        self.tree.delete(*self.tree.get_children())
        for i, it in enumerate(self.items):
            mark = "[x]" if it.include else "[ ]"
            mins = f"{it.length_seconds / 60:.1f}"
            self.tree.insert("", "end", iid=str(i),
                              values=(mark, it.title_number, mins, it.filename or ""))

        self.rip_button.configure(
            state="normal" if any(it.include for it in self.items) else "disabled")

    def _on_tree_click(self, event):
        row = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not row or col != "#1":
            return
        idx = int(row)
        self.items[idx].include = not self.items[idx].include
        self._recompute_dvd()

    def _on_rip(self):
        ok, msg = self._validate_dvd_meta()
        if not ok:
            messagebox.showerror(APP_TITLE, msg)
            return

        device = self._resolve_device()
        if device is None:
            messagebox.showerror(APP_TITLE, self._no_drive_message())
            return

        # Same reason as the Convert File tab: never rip with filenames left
        # over from before the title/year fields were filled in.
        self._recompute_dvd()

        included = [it for it in self.items if it.include]
        if not included:
            return

        ripper = self.ripper.get()
        self.cancel_event.clear()
        self.rip_button.configure(state="disabled")
        self.dvd_cancel_button.configure(state="normal")

        def work():
            try:
                engine.rip_disc(device, self.items, ripper, self._log,
                                 should_cancel=self.cancel_event.is_set)
                self._log("--- disc finished ---")
            except Exception as exc:  # noqa: BLE001 - last-resort UI safety net
                self._log(f"Rip failed unexpectedly: {exc!r}")
            finally:
                self._need_worker_done = True

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    # -- shared: logging / worker polling / cancel ------------------------------

    def _log(self, msg: str):
        self.log_queue.put(msg)

    def _poll_worker_state(self):
        """Runs on the main thread only. Background threads never call Tk
        methods or self.after() themselves - they just push to log_queue or
        flip the _need_* flags, and this poll picks the results up."""
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass

        if self._need_scan_button_reset:
            self._need_scan_button_reset = False
            self._scanning = False
            self.scan_button.configure(state="normal")

        if self._need_drive_refresh:
            self._need_drive_refresh = False
            self.drive_combo.configure(state="readonly", values=list(self._drive_options))
            if self._drive_options and self.device.get() not in self._drive_options:
                self.device.set(next(iter(self._drive_options)))

        if self._need_recompute:
            self._need_recompute = False
            if hasattr(self, "convert_items"):
                self._recompute_convert()

        if self._need_worker_done:
            self._need_worker_done = False
            self._on_worker_done()

        self.after(200, self._poll_worker_state)

    def _on_worker_done(self):
        self.convert_run_button.configure(state="normal")
        self.convert_cancel_button.configure(state="disabled")
        if DVD_TOOLS_AVAILABLE:
            self.rip_button.configure(state="normal")
            self.dvd_cancel_button.configure(state="disabled")

    def _on_cancel(self):
        self.cancel_event.set()
        self._log("Cancel requested - will stop after the current item.")


def main():
    app = ConverterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
