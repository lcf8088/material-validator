"""
Settings panel for Material Validator GUI.

Embedded in the main window as a swappable frame (avoids CTkToplevel bugs).
"""

import threading
from pathlib import Path

try:
    import customtkinter as ctk
    HAS_CTK = True
except ImportError:
    import tkinter as tk
    from tkinter import ttk
    ctk = None
    HAS_CTK = False

from tkinter import filedialog, messagebox

from .config import Config
from .theme import COLORS, FONTS


class SettingsPanel:
    """Settings panel that embeds in the main window, replacing main content."""

    def __init__(self, parent_frame, config: Config, spec_loader, on_done=None):
        """
        Args:
            parent_frame: The parent frame to pack into (typically root or main container).
            config: Config instance.
            spec_loader: SpecLoader instance.
            on_done: Callback(saved: bool) when settings panel is closed.
        """
        self.config = config
        self.spec_loader = spec_loader
        self.on_done = on_done
        self.saved = False

        if HAS_CTK:
            self.frame = ctk.CTkFrame(parent_frame, fg_color=COLORS['bg_dark'])
        else:
            self.frame = ttk.Frame(parent_frame, padding=10)

        self._build_ui()
        self._load_values()

    def show(self):
        """Show the settings panel."""
        self.frame.pack(fill='both', expand=True, padx=10, pady=10)

    def hide(self):
        """Hide the settings panel."""
        self.frame.pack_forget()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        if HAS_CTK:
            self._build_ctk()
        else:
            self._build_tk()

    # ---------- customtkinter layout ----------
    def _build_ctk(self):
        # Header
        header = ctk.CTkFrame(self.frame, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(10, 5))
        ctk.CTkLabel(
            header, text="Settings", font=FONTS['section_header'],
            text_color=COLORS['text_primary']
        ).pack(side="left")

        # Tabs
        tabs = ctk.CTkTabview(
            self.frame, width=490, height=380,
            fg_color=COLORS['bg_card'],
            segmented_button_selected_color=COLORS['accent'],
            segmented_button_selected_hover_color=COLORS['accent_hover'],
            segmented_button_unselected_color=COLORS['bg_dark'],
            segmented_button_unselected_hover_color=COLORS['surface_hl'],
        )
        tabs.pack(padx=10, pady=(0, 5), fill="both", expand=True)

        tabs.add("Pipeline")
        tabs.add("Archive")
        tabs.add("General")

        self._build_pipeline_tab_ctk(tabs.tab("Pipeline"))
        self._build_archive_tab_ctk(tabs.tab("Archive"))
        self._build_general_tab_ctk(tabs.tab("General"))

        # Bottom buttons
        btn_frame = ctk.CTkFrame(self.frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=(5, 10))

        ctk.CTkButton(
            btn_frame, text="Save", width=100, command=self._on_save,
            fg_color=COLORS['accent'], hover_color=COLORS['accent_hover'],
            text_color=COLORS['bg_darkest'], font=FONTS['badge'],
        ).pack(side="right", padx=5)
        ctk.CTkButton(
            btn_frame, text="Cancel", width=100, command=self._on_cancel,
            fg_color=COLORS['bg_card'], hover_color=COLORS['surface_hl'],
            border_color=COLORS['border'], border_width=1,
            text_color=COLORS['text_primary'], font=FONTS['badge'],
        ).pack(side="right", padx=5)

    def _entry(self, parent, textvariable, width=290, **kw):
        """Create a themed CTkEntry."""
        return ctk.CTkEntry(
            parent, textvariable=textvariable, width=width,
            fg_color=COLORS['bg_input'], border_color=COLORS['border'],
            text_color=COLORS['text_primary'], font=FONTS['body'], **kw
        )

    def _combo(self, parent, values, variable, width=120, **kw):
        """Create a themed CTkComboBox."""
        return ctk.CTkComboBox(
            parent, values=values, variable=variable, width=width,
            fg_color=COLORS['bg_input'], border_color=COLORS['border'],
            button_color=COLORS['accent'], button_hover_color=COLORS['accent_hover'],
            dropdown_fg_color=COLORS['bg_card'], dropdown_hover_color=COLORS['surface_hl'],
            dropdown_text_color=COLORS['text_primary'],
            text_color=COLORS['text_primary'], font=FONTS['body'], **kw
        )

    def _label(self, parent, text, secondary=False):
        """Create a themed CTkLabel."""
        return ctk.CTkLabel(
            parent, text=text, font=FONTS['label'],
            text_color=COLORS['text_secondary'] if secondary else COLORS['text_primary']
        )

    def _browse_button(self, parent, command, text="Browse"):
        """Create a themed secondary browse button."""
        return ctk.CTkButton(
            parent, text=text, width=70, command=command,
            fg_color=COLORS['bg_card'], hover_color=COLORS['surface_hl'],
            border_color=COLORS['border'], border_width=1,
            text_color=COLORS['text_primary'], font=FONTS['label'],
        )

    def _build_pipeline_tab_ctk(self, tab):
        pad = {"padx": 15, "pady": (8, 0)}

        self._label(tab, "Anthropic API Key").pack(anchor="w", **pad)
        key_frame = ctk.CTkFrame(tab, fg_color="transparent")
        key_frame.pack(fill="x", padx=15, pady=2)
        self.key_var = ctk.StringVar()
        self.key_entry = self._entry(key_frame, textvariable=self.key_var, show="*")
        self.key_entry.pack(side="left")
        self.show_key_btn = ctk.CTkButton(
            key_frame, text="Show", width=55, command=self._toggle_key,
            fg_color=COLORS['bg_card'], hover_color=COLORS['surface_hl'],
            border_color=COLORS['border'], border_width=1,
            text_color=COLORS['text_primary'], font=FONTS['label'],
        )
        self.show_key_btn.pack(side="left", padx=5)

        self.test_btn = ctk.CTkButton(
            tab, text="Test Connection", width=140, command=self._test_connection,
            fg_color=COLORS['accent'], hover_color=COLORS['accent_hover'],
            text_color=COLORS['bg_darkest'], font=FONTS['label'],
        )
        self.test_btn.pack(anchor="w", padx=15, pady=(10, 0))
        self.test_label = ctk.CTkLabel(tab, text="", text_color=COLORS['text_secondary'])
        self.test_label.pack(anchor="w", padx=15, pady=2)

        self._label(tab, "Watch Folder (auto-process new files)").pack(anchor="w", **pad)
        wf_frame = ctk.CTkFrame(tab, fg_color="transparent")
        wf_frame.pack(fill="x", padx=15, pady=2)
        self.watch_var = ctk.StringVar()
        self._entry(wf_frame, textvariable=self.watch_var, width=310).pack(side="left")
        self._browse_button(wf_frame, self._browse_watch).pack(side="left", padx=5)

        self.watch_auto_process_var = ctk.BooleanVar()
        ctk.CTkCheckBox(
            tab, text="Auto-process watched files", variable=self.watch_auto_process_var,
            fg_color=COLORS['accent'], hover_color=COLORS['accent_hover'],
            border_color=COLORS['border'], text_color=COLORS['text_primary'],
            font=FONTS['body'],
        ).pack(anchor="w", padx=15, pady=(6, 0))

        self._label(tab, "Preprocessing DPI").pack(anchor="w", **pad)
        self.prep_dpi_var = ctk.StringVar()
        self._combo(tab, ["200", "300", "400"], self.prep_dpi_var, state="readonly").pack(anchor="w", padx=15, pady=2)

        self._label(tab, "PaddleOCR Model Path (optional)").pack(anchor="w", **pad)
        pm_frame = ctk.CTkFrame(tab, fg_color="transparent")
        pm_frame.pack(fill="x", padx=15, pady=2)
        self.paddle_var = ctk.StringVar()
        self._entry(pm_frame, textvariable=self.paddle_var, width=310).pack(side="left")
        self._browse_button(pm_frame, self._browse_paddle).pack(side="left", padx=5)

    def _build_archive_tab_ctk(self, tab):
        pad = {"padx": 15, "pady": (8, 0)}

        self._label(tab, "Archive Folder").pack(anchor="w", **pad)
        af_frame = ctk.CTkFrame(tab, fg_color="transparent")
        af_frame.pack(fill="x", padx=15, pady=2)
        self.archive_var = ctk.StringVar()
        self._entry(af_frame, textvariable=self.archive_var, width=310).pack(side="left")
        self._browse_button(af_frame, self._browse_archive).pack(side="left", padx=5)

        self._label(tab, "Output Folder (overrides Archive Folder)").pack(anchor="w", **pad)
        of_frame = ctk.CTkFrame(tab, fg_color="transparent")
        of_frame.pack(fill="x", padx=15, pady=2)
        self.output_folder_var = ctk.StringVar()
        self._entry(of_frame, textvariable=self.output_folder_var, width=310).pack(side="left")
        self._browse_button(of_frame, self._browse_output_folder).pack(side="left", padx=5)

        self.auto_archive_var = ctk.BooleanVar()
        ctk.CTkCheckBox(
            tab, text="Auto-archive TIFF after validation", variable=self.auto_archive_var,
            fg_color=COLORS['accent'], hover_color=COLORS['accent_hover'],
            border_color=COLORS['border'], text_color=COLORS['text_primary'],
            font=FONTS['body'],
        ).pack(anchor="w", padx=15, pady=(10, 0))

        self.organize_by_po_var = ctk.BooleanVar()
        ctk.CTkCheckBox(
            tab, text="Create PO# subfolders", variable=self.organize_by_po_var,
            fg_color=COLORS['accent'], hover_color=COLORS['accent_hover'],
            border_color=COLORS['border'], text_color=COLORS['text_primary'],
            font=FONTS['body'],
        ).pack(anchor="w", padx=15, pady=(6, 0))

        self._label(tab, "TIFF DPI").pack(anchor="w", **pad)
        self.dpi_var = ctk.StringVar()
        self._combo(tab, ["150", "200", "300"], self.dpi_var, state="readonly").pack(anchor="w", padx=15, pady=2)

        self._label(tab, "TIFF Compression").pack(anchor="w", **pad)
        self.compress_var = ctk.StringVar()
        self._combo(tab, ["lzw", "jpeg", "none", "deflate"], self.compress_var, state="readonly").pack(anchor="w", padx=15, pady=2)

    def _build_general_tab_ctk(self, tab):
        pad = {"padx": 15, "pady": (8, 0)}

        self._label(tab, "Theme").pack(anchor="w", **pad)
        self.theme_var = ctk.StringVar()
        self._combo(tab, ["dark", "light"], self.theme_var, state="readonly").pack(anchor="w", padx=15, pady=2)

        self._label(tab, "Specs Folder").pack(anchor="w", **pad)
        sf_frame = ctk.CTkFrame(tab, fg_color="transparent")
        sf_frame.pack(fill="x", padx=15, pady=2)
        self.specs_var = ctk.StringVar()
        self._entry(sf_frame, textvariable=self.specs_var, width=310).pack(side="left")
        self._browse_button(sf_frame, self._browse_specs).pack(side="left", padx=5)

        self.auto_detect_var = ctk.BooleanVar()
        ctk.CTkCheckBox(
            tab, text="Auto-detect Spec", variable=self.auto_detect_var,
            fg_color=COLORS['accent'], hover_color=COLORS['accent_hover'],
            border_color=COLORS['border'], text_color=COLORS['text_primary'],
            font=FONTS['body'],
        ).pack(anchor="w", padx=15, pady=(10, 0))

        self._label(tab, "Default Spec").pack(anchor="w", **pad)
        spec_ids = self.spec_loader.list_ids()
        self.default_spec_var = ctk.StringVar()
        self.default_spec_combo = self._combo(tab, [""] + spec_ids, self.default_spec_var, width=250)
        self.default_spec_combo.pack(anchor="w", padx=15, pady=2)

    # ---------- standard tkinter fallback ----------
    def _build_tk(self):
        # Header
        ttk.Label(self.frame, text="Settings", font=("", 14, "bold")).pack(anchor="w", padx=10, pady=(10, 5))

        notebook = ttk.Notebook(self.frame)
        notebook.pack(fill="both", expand=True, padx=10, pady=(0, 5))

        pipeline_tab = ttk.Frame(notebook, padding=10)
        archive_tab = ttk.Frame(notebook, padding=10)
        general_tab = ttk.Frame(notebook, padding=10)
        notebook.add(pipeline_tab, text="Pipeline")
        notebook.add(archive_tab, text="Archive")
        notebook.add(general_tab, text="General")

        self._build_pipeline_tab_tk(pipeline_tab)
        self._build_archive_tab_tk(archive_tab)
        self._build_general_tab_tk(general_tab)

        btn_frame = ttk.Frame(self.frame)
        btn_frame.pack(fill="x", padx=10, pady=(5, 10))
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="Save", command=self._on_save).pack(side="right", padx=5)

    def _build_pipeline_tab_tk(self, tab):
        row = 0
        ttk.Label(tab, text="Anthropic API Key").grid(row=row, column=0, sticky="w", pady=4)
        key_frame = ttk.Frame(tab)
        key_frame.grid(row=row, column=1, sticky="w", pady=4)
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(key_frame, textvariable=self.key_var, show="*", width=35)
        self.key_entry.pack(side="left")
        self.show_key_btn = ttk.Button(key_frame, text="Show", width=6, command=self._toggle_key)
        self.show_key_btn.pack(side="left", padx=4)

        row += 1
        self.test_btn = ttk.Button(tab, text="Test Connection", command=self._test_connection)
        self.test_btn.grid(row=row, column=0, sticky="w", pady=8)
        self.test_label = ttk.Label(tab, text="")
        self.test_label.grid(row=row, column=1, sticky="w", pady=8)

        row += 1
        ttk.Label(tab, text="Watch Folder").grid(row=row, column=0, sticky="w", pady=4)
        wf_frame = ttk.Frame(tab)
        wf_frame.grid(row=row, column=1, sticky="w", pady=4)
        self.watch_var = tk.StringVar()
        ttk.Entry(wf_frame, textvariable=self.watch_var, width=35).pack(side="left")
        ttk.Button(wf_frame, text="Browse", command=self._browse_watch).pack(side="left", padx=4)

        row += 1
        self.watch_auto_process_var = tk.BooleanVar()
        ttk.Checkbutton(tab, text="Auto-process watched files", variable=self.watch_auto_process_var).grid(row=row, column=0, columnspan=2, sticky="w", pady=6)

        row += 1
        ttk.Label(tab, text="Preprocessing DPI").grid(row=row, column=0, sticky="w", pady=4)
        self.prep_dpi_var = tk.StringVar()
        ttk.Combobox(tab, values=["200", "300", "400"], textvariable=self.prep_dpi_var, state="readonly", width=10).grid(row=row, column=1, sticky="w", pady=4)

        row += 1
        ttk.Label(tab, text="PaddleOCR Model Path").grid(row=row, column=0, sticky="w", pady=4)
        pm_frame = ttk.Frame(tab)
        pm_frame.grid(row=row, column=1, sticky="w", pady=4)
        self.paddle_var = tk.StringVar()
        ttk.Entry(pm_frame, textvariable=self.paddle_var, width=35).pack(side="left")
        ttk.Button(pm_frame, text="Browse", command=self._browse_paddle).pack(side="left", padx=4)

    def _build_archive_tab_tk(self, tab):
        row = 0
        ttk.Label(tab, text="Archive Folder").grid(row=row, column=0, sticky="w", pady=4)
        af_frame = ttk.Frame(tab)
        af_frame.grid(row=row, column=1, sticky="w", pady=4)
        self.archive_var = tk.StringVar()
        ttk.Entry(af_frame, textvariable=self.archive_var, width=35).pack(side="left")
        ttk.Button(af_frame, text="Browse", command=self._browse_archive).pack(side="left", padx=4)

        row += 1
        ttk.Label(tab, text="Output Folder (overrides Archive)").grid(row=row, column=0, sticky="w", pady=4)
        of_frame = ttk.Frame(tab)
        of_frame.grid(row=row, column=1, sticky="w", pady=4)
        self.output_folder_var = tk.StringVar()
        ttk.Entry(of_frame, textvariable=self.output_folder_var, width=35).pack(side="left")
        ttk.Button(of_frame, text="Browse", command=self._browse_output_folder).pack(side="left", padx=4)

        row += 1
        self.auto_archive_var = tk.BooleanVar()
        ttk.Checkbutton(tab, text="Auto-archive TIFF after validation", variable=self.auto_archive_var).grid(row=row, column=0, columnspan=2, sticky="w", pady=6)

        row += 1
        self.organize_by_po_var = tk.BooleanVar()
        ttk.Checkbutton(tab, text="Create PO# subfolders", variable=self.organize_by_po_var).grid(row=row, column=0, columnspan=2, sticky="w", pady=4)

        row += 1
        ttk.Label(tab, text="TIFF DPI").grid(row=row, column=0, sticky="w", pady=4)
        self.dpi_var = tk.StringVar()
        ttk.Combobox(tab, values=["150", "200", "300"], textvariable=self.dpi_var, state="readonly", width=10).grid(row=row, column=1, sticky="w", pady=4)

        row += 1
        ttk.Label(tab, text="TIFF Compression").grid(row=row, column=0, sticky="w", pady=4)
        self.compress_var = tk.StringVar()
        ttk.Combobox(tab, values=["lzw", "jpeg", "none", "deflate"], textvariable=self.compress_var, state="readonly", width=10).grid(row=row, column=1, sticky="w", pady=4)

    def _build_general_tab_tk(self, tab):
        row = 0
        ttk.Label(tab, text="Theme").grid(row=row, column=0, sticky="w", pady=4)
        self.theme_var = tk.StringVar()
        ttk.Combobox(tab, values=["dark", "light"], textvariable=self.theme_var, state="readonly", width=10).grid(row=row, column=1, sticky="w", pady=4)

        row += 1
        ttk.Label(tab, text="Specs Folder").grid(row=row, column=0, sticky="w", pady=4)
        sf_frame = ttk.Frame(tab)
        sf_frame.grid(row=row, column=1, sticky="w", pady=4)
        self.specs_var = tk.StringVar()
        ttk.Entry(sf_frame, textvariable=self.specs_var, width=35).pack(side="left")
        ttk.Button(sf_frame, text="Browse", command=self._browse_specs).pack(side="left", padx=4)

        row += 1
        self.auto_detect_var = tk.BooleanVar()
        ttk.Checkbutton(tab, text="Auto-detect Spec", variable=self.auto_detect_var).grid(row=row, column=0, columnspan=2, sticky="w", pady=6)

        row += 1
        ttk.Label(tab, text="Default Spec").grid(row=row, column=0, sticky="w", pady=4)
        spec_ids = self.spec_loader.list_ids()
        self.default_spec_var = tk.StringVar()
        self.default_spec_combo = ttk.Combobox(tab, values=[""] + spec_ids, textvariable=self.default_spec_var, width=30)
        self.default_spec_combo.grid(row=row, column=1, sticky="w", pady=4)

    # --------------------------------------------------------- load / save
    def _load_values(self):
        """Populate widgets from config."""
        self.key_var.set(self.config.get("anthropic_api_key", ""))
        self.watch_var.set(self.config.get("watch_folder", ""))
        self.prep_dpi_var.set(str(self.config.get("preprocessing_dpi", 300)))
        self.paddle_var.set(self.config.get("paddle_model_path", ""))

        self.archive_var.set(self.config.get("archive_folder", ""))
        self.output_folder_var.set(self.config.get("output_folder", ""))
        self.auto_archive_var.set(self.config.get("auto_archive", True))
        self.organize_by_po_var.set(self.config.get("organize_by_po", False))
        self.watch_auto_process_var.set(self.config.get("watch_auto_process", True))
        self.dpi_var.set(str(self.config.get("tiff_dpi", 300)))
        self.compress_var.set(self.config.get("tiff_compression", "lzw"))

        self.theme_var.set(self.config.get("theme", "dark"))
        self.specs_var.set(self.config.get("specs_folder", ""))
        self.auto_detect_var.set(self.config.get("auto_detect_spec", True))
        self.default_spec_var.set(self.config.get("default_spec", ""))

    def _on_save(self):
        dpi_str = self.dpi_var.get()
        if not dpi_str.isdigit():
            messagebox.showwarning("Invalid DPI", "TIFF DPI must be a number.")
            return

        prep_dpi_str = self.prep_dpi_var.get()
        if not prep_dpi_str.isdigit():
            messagebox.showwarning("Invalid DPI", "Preprocessing DPI must be a number.")
            return

        old_specs_folder = self.config.get("specs_folder", "")

        self.config.update({
            "anthropic_api_key": self.key_var.get().strip(),
            "watch_folder": self.watch_var.get().strip(),
            "watch_auto_process": self.watch_auto_process_var.get(),
            "preprocessing_dpi": int(prep_dpi_str),
            "paddle_model_path": self.paddle_var.get().strip(),
            "archive_folder": self.archive_var.get().strip(),
            "output_folder": self.output_folder_var.get().strip(),
            "auto_archive": self.auto_archive_var.get(),
            "organize_by_po": self.organize_by_po_var.get(),
            "tiff_dpi": int(dpi_str),
            "tiff_compression": self.compress_var.get(),
            "theme": self.theme_var.get(),
            "specs_folder": self.specs_var.get().strip(),
            "auto_detect_spec": self.auto_detect_var.get(),
            "default_spec": self.default_spec_var.get(),
        })

        # Apply theme immediately
        if HAS_CTK:
            ctk.set_appearance_mode(self.theme_var.get())

        # Reload specs if folder changed
        new_specs_folder = self.specs_var.get().strip()
        if new_specs_folder and new_specs_folder != old_specs_folder:
            self.spec_loader.specs_dir = Path(new_specs_folder)
            self.spec_loader.reload()

        self.saved = True
        if self.on_done:
            self.on_done(True)

    def _on_cancel(self):
        if self.on_done:
            self.on_done(False)

    # --------------------------------------------------------- callbacks
    def _toggle_key(self):
        current = self.key_entry.cget("show")
        if current == "*":
            self.key_entry.configure(show="")
            self.show_key_btn.configure(text="Hide")
        else:
            self.key_entry.configure(show="*")
            self.show_key_btn.configure(text="Show")

    def _test_connection(self):
        api_key = self.key_var.get().strip()
        if not api_key:
            messagebox.showwarning("Missing Key", "Enter an Anthropic API key first.")
            return

        self.test_btn.configure(state="disabled")
        self.test_label.configure(text="Testing...")

        def run():
            from lib.claude_parser import test_connection
            ok, msg = test_connection(api_key)

            def on_done():
                self.test_btn.configure(state="normal")
                self.test_label.configure(text=msg)

            self.frame.after(0, on_done)

        threading.Thread(target=run, daemon=True).start()

    def _browse_archive(self):
        folder = filedialog.askdirectory(title="Select Archive Folder")
        if folder:
            self.archive_var.set(folder)

    def _browse_output_folder(self):
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            self.output_folder_var.set(folder)

    def _browse_watch(self):
        folder = filedialog.askdirectory(title="Select Watch Folder")
        if folder:
            self.watch_var.set(folder)

    def _browse_paddle(self):
        folder = filedialog.askdirectory(title="Select PaddleOCR Model Directory")
        if folder:
            self.paddle_var.set(folder)

    def _browse_specs(self):
        folder = filedialog.askdirectory(title="Select Specs Folder")
        if folder:
            self.specs_var.set(folder)


# Backward-compatible alias
SettingsDialog = SettingsPanel
