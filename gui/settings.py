"""
Settings dialog for Material Validator GUI.
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

from .config import Config, VISION_PROVIDERS
from .vision_api import create_vision_provider


class SettingsDialog:
    """Modal settings dialog with tabbed sections."""

    def __init__(self, parent, config: Config, spec_loader):
        self.config = config
        self.spec_loader = spec_loader
        self.parent = parent
        self.saved = False

        # Create modal toplevel
        if HAS_CTK:
            self.window = ctk.CTkToplevel(parent)
        else:
            self.window = tk.Toplevel(parent)

        self.window.title("Settings")
        self.window.geometry("520x480")
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self._build_ui()
        self._load_values()

        self.window.wait_window()

        # Workaround: CTkToplevel.destroy() can hide the parent window
        self.parent.deiconify()
        self.parent.lift()
        self.parent.focus_force()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        if HAS_CTK:
            self._build_ctk()
        else:
            self._build_tk()

    # ---------- customtkinter layout ----------
    def _build_ctk(self):
        tabs = ctk.CTkTabview(self.window, width=490, height=390)
        tabs.pack(padx=10, pady=(10, 0))

        tabs.add("Vision")
        tabs.add("Archive")
        tabs.add("General")

        self._build_vision_tab_ctk(tabs.tab("Vision"))
        self._build_archive_tab_ctk(tabs.tab("Archive"))
        self._build_general_tab_ctk(tabs.tab("General"))

        # Bottom buttons
        btn_frame = ctk.CTkFrame(self.window, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkButton(btn_frame, text="Save", width=100, command=self._on_save).pack(side="right", padx=5)
        ctk.CTkButton(btn_frame, text="Cancel", width=100, fg_color="gray40", command=self._on_cancel).pack(side="right", padx=5)

    def _build_vision_tab_ctk(self, tab):
        pad = {"padx": 15, "pady": (8, 0)}

        ctk.CTkLabel(tab, text="Vision Provider").pack(anchor="w", **pad)
        provider_names = [VISION_PROVIDERS[k]["name"] for k in VISION_PROVIDERS]
        self.provider_var = ctk.StringVar()
        self.provider_combo = ctk.CTkComboBox(
            tab, values=provider_names, variable=self.provider_var,
            command=self._on_provider_change, state="readonly", width=350
        )
        self.provider_combo.pack(anchor="w", padx=15, pady=2)

        ctk.CTkLabel(tab, text="API Key").pack(anchor="w", **pad)
        key_frame = ctk.CTkFrame(tab, fg_color="transparent")
        key_frame.pack(fill="x", padx=15, pady=2)
        self.key_var = ctk.StringVar()
        self.key_entry = ctk.CTkEntry(key_frame, textvariable=self.key_var, show="*", width=290)
        self.key_entry.pack(side="left")
        self.show_key_btn = ctk.CTkButton(key_frame, text="Show", width=55, command=self._toggle_key)
        self.show_key_btn.pack(side="left", padx=5)

        ctk.CTkLabel(tab, text="Model").pack(anchor="w", **pad)
        self.model_var = ctk.StringVar()
        self.model_combo = ctk.CTkComboBox(tab, values=[], variable=self.model_var, width=350)
        self.model_combo.pack(anchor="w", padx=15, pady=2)

        self.test_btn = ctk.CTkButton(tab, text="Test Connection", width=140, command=self._test_connection)
        self.test_btn.pack(anchor="w", padx=15, pady=(12, 0))
        self.test_label = ctk.CTkLabel(tab, text="")
        self.test_label.pack(anchor="w", padx=15, pady=2)

    def _build_archive_tab_ctk(self, tab):
        pad = {"padx": 15, "pady": (8, 0)}

        ctk.CTkLabel(tab, text="Archive Folder").pack(anchor="w", **pad)
        af_frame = ctk.CTkFrame(tab, fg_color="transparent")
        af_frame.pack(fill="x", padx=15, pady=2)
        self.archive_var = ctk.StringVar()
        ctk.CTkEntry(af_frame, textvariable=self.archive_var, width=310).pack(side="left")
        ctk.CTkButton(af_frame, text="Browse", width=70, command=self._browse_archive).pack(side="left", padx=5)

        ctk.CTkLabel(tab, text="TIFF DPI").pack(anchor="w", **pad)
        self.dpi_var = ctk.StringVar()
        ctk.CTkComboBox(tab, values=["150", "200", "300"], variable=self.dpi_var, width=120, state="readonly").pack(anchor="w", padx=15, pady=2)

        ctk.CTkLabel(tab, text="TIFF Compression").pack(anchor="w", **pad)
        self.compress_var = ctk.StringVar()
        ctk.CTkComboBox(tab, values=["lzw", "jpeg", "none", "deflate"], variable=self.compress_var, width=120, state="readonly").pack(anchor="w", padx=15, pady=2)

    def _build_general_tab_ctk(self, tab):
        pad = {"padx": 15, "pady": (8, 0)}

        ctk.CTkLabel(tab, text="Theme").pack(anchor="w", **pad)
        self.theme_var = ctk.StringVar()
        ctk.CTkComboBox(tab, values=["dark", "light"], variable=self.theme_var, width=120, state="readonly").pack(anchor="w", padx=15, pady=2)

        ctk.CTkLabel(tab, text="Specs Folder").pack(anchor="w", **pad)
        sf_frame = ctk.CTkFrame(tab, fg_color="transparent")
        sf_frame.pack(fill="x", padx=15, pady=2)
        self.specs_var = ctk.StringVar()
        ctk.CTkEntry(sf_frame, textvariable=self.specs_var, width=310).pack(side="left")
        ctk.CTkButton(sf_frame, text="Browse", width=70, command=self._browse_specs).pack(side="left", padx=5)

        self.auto_detect_var = ctk.BooleanVar()
        ctk.CTkCheckBox(tab, text="Auto-detect Spec", variable=self.auto_detect_var).pack(anchor="w", padx=15, pady=(10, 0))

        ctk.CTkLabel(tab, text="Default Spec").pack(anchor="w", **pad)
        spec_ids = self.spec_loader.list_ids()
        self.default_spec_var = ctk.StringVar()
        self.default_spec_combo = ctk.CTkComboBox(tab, values=[""] + spec_ids, variable=self.default_spec_var, width=250)
        self.default_spec_combo.pack(anchor="w", padx=15, pady=2)

    # ---------- standard tkinter fallback ----------
    def _build_tk(self):
        notebook = ttk.Notebook(self.window)
        notebook.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        vision_tab = ttk.Frame(notebook, padding=10)
        archive_tab = ttk.Frame(notebook, padding=10)
        general_tab = ttk.Frame(notebook, padding=10)
        notebook.add(vision_tab, text="Vision")
        notebook.add(archive_tab, text="Archive")
        notebook.add(general_tab, text="General")

        self._build_vision_tab_tk(vision_tab)
        self._build_archive_tab_tk(archive_tab)
        self._build_general_tab_tk(general_tab)

        btn_frame = ttk.Frame(self.window)
        btn_frame.pack(fill="x", padx=10, pady=10)
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="Save", command=self._on_save).pack(side="right", padx=5)

    def _build_vision_tab_tk(self, tab):
        row = 0
        ttk.Label(tab, text="Vision Provider").grid(row=row, column=0, sticky="w", pady=4)
        provider_names = [VISION_PROVIDERS[k]["name"] for k in VISION_PROVIDERS]
        self.provider_var = tk.StringVar()
        self.provider_combo = ttk.Combobox(tab, values=provider_names, textvariable=self.provider_var, state="readonly", width=40)
        self.provider_combo.grid(row=row, column=1, sticky="w", pady=4)
        self.provider_combo.bind("<<ComboboxSelected>>", lambda e: self._on_provider_change(self.provider_var.get()))

        row += 1
        ttk.Label(tab, text="API Key").grid(row=row, column=0, sticky="w", pady=4)
        key_frame = ttk.Frame(tab)
        key_frame.grid(row=row, column=1, sticky="w", pady=4)
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(key_frame, textvariable=self.key_var, show="*", width=35)
        self.key_entry.pack(side="left")
        self.show_key_btn = ttk.Button(key_frame, text="Show", width=6, command=self._toggle_key)
        self.show_key_btn.pack(side="left", padx=4)

        row += 1
        ttk.Label(tab, text="Model").grid(row=row, column=0, sticky="w", pady=4)
        self.model_var = tk.StringVar()
        self.model_combo = ttk.Combobox(tab, values=[], textvariable=self.model_var, width=40)
        self.model_combo.grid(row=row, column=1, sticky="w", pady=4)

        row += 1
        self.test_btn = ttk.Button(tab, text="Test Connection", command=self._test_connection)
        self.test_btn.grid(row=row, column=0, sticky="w", pady=8)
        self.test_label = ttk.Label(tab, text="")
        self.test_label.grid(row=row, column=1, sticky="w", pady=8)

    def _build_archive_tab_tk(self, tab):
        row = 0
        ttk.Label(tab, text="Archive Folder").grid(row=row, column=0, sticky="w", pady=4)
        af_frame = ttk.Frame(tab)
        af_frame.grid(row=row, column=1, sticky="w", pady=4)
        self.archive_var = tk.StringVar()
        ttk.Entry(af_frame, textvariable=self.archive_var, width=35).pack(side="left")
        ttk.Button(af_frame, text="Browse", command=self._browse_archive).pack(side="left", padx=4)

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

    # ----------------------------------------------------------- helpers
    def _provider_key_from_name(self, display_name: str) -> str:
        """Map display name back to provider key."""
        for key, info in VISION_PROVIDERS.items():
            if info["name"] == display_name:
                return key
        return "openai"

    def _provider_name_from_key(self, key: str) -> str:
        """Map provider key to display name."""
        info = VISION_PROVIDERS.get(key, {})
        return info.get("name", key)

    # --------------------------------------------------------- load / save
    def _load_values(self):
        """Populate widgets from config."""
        prov_key = self.config.get("vision_provider", "openai")
        self.provider_var.set(self._provider_name_from_key(prov_key))
        self._on_provider_change(self.provider_var.get())

        self.key_var.set(self.config.get("vision_api_key", ""))
        self.model_var.set(self.config.get("vision_model", ""))

        self.archive_var.set(self.config.get("archive_folder", ""))
        self.dpi_var.set(str(self.config.get("tiff_dpi", 300)))
        self.compress_var.set(self.config.get("tiff_compression", "lzw"))

        self.theme_var.set(self.config.get("theme", "dark"))
        self.specs_var.set(self.config.get("specs_folder", ""))
        self.auto_detect_var.set(self.config.get("auto_detect_spec", True))
        self.default_spec_var.set(self.config.get("default_spec", ""))

    def _on_save(self):
        dpi_str = self.dpi_var.get()
        if not dpi_str.isdigit():
            messagebox.showwarning("Invalid DPI", "TIFF DPI must be a number.", parent=self.window)
            return

        prov_key = self._provider_key_from_name(self.provider_var.get())
        old_specs_folder = self.config.get("specs_folder", "")

        self.config.update({
            "vision_provider": prov_key,
            "vision_api_key": self.key_var.get().strip(),
            "vision_model": self.model_var.get().strip(),
            "archive_folder": self.archive_var.get().strip(),
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
        self._close()

    def _on_cancel(self):
        self._close()

    def _close(self):
        """Release grab, restore focus to parent, then destroy."""
        self.window.grab_release()
        self.parent.focus_set()
        self.window.destroy()

    # --------------------------------------------------------- callbacks
    def _on_provider_change(self, display_name):
        """Update model list and key field when provider changes."""
        prov_key = self._provider_key_from_name(display_name)
        info = VISION_PROVIDERS.get(prov_key, {})
        models = info.get("models", [])

        if HAS_CTK:
            self.model_combo.configure(values=models)
        else:
            self.model_combo["values"] = models

        # Pre-select first model if current value not in list
        if self.model_var.get() not in models and models:
            self.model_var.set(models[0])

        # Enable/disable API key
        requires_key = info.get("requires_key", True)
        if HAS_CTK:
            self.key_entry.configure(state="normal" if requires_key else "disabled")
        else:
            self.key_entry.configure(state="normal" if requires_key else "disabled")

    def _toggle_key(self):
        current = self.key_entry.cget("show")
        if current == "*":
            self.key_entry.configure(show="")
            if HAS_CTK:
                self.show_key_btn.configure(text="Hide")
            else:
                self.show_key_btn.configure(text="Hide")
        else:
            self.key_entry.configure(show="*")
            if HAS_CTK:
                self.show_key_btn.configure(text="Show")
            else:
                self.show_key_btn.configure(text="Show")

    def _test_connection(self):
        prov_key = self._provider_key_from_name(self.provider_var.get())
        api_key = self.key_var.get().strip()
        model = self.model_var.get().strip()

        if HAS_CTK:
            self.test_btn.configure(state="disabled")
            self.test_label.configure(text="Testing...")
        else:
            self.test_btn.configure(state="disabled")
            self.test_label.configure(text="Testing...")

        def run():
            try:
                provider = create_vision_provider(prov_key, api_key, model)
                ok, msg = provider.test_connection()
            except Exception as e:
                ok, msg = False, str(e)

            def on_done():
                if HAS_CTK:
                    self.test_btn.configure(state="normal")
                    self.test_label.configure(text=msg)
                else:
                    self.test_btn.configure(state="normal")
                    self.test_label.configure(text=msg)

            self.window.after(0, on_done)

        threading.Thread(target=run, daemon=True).start()

    def _browse_archive(self):
        folder = filedialog.askdirectory(title="Select Archive Folder", parent=self.window)
        if folder:
            self.archive_var.set(folder)

    def _browse_specs(self):
        folder = filedialog.askdirectory(title="Select Specs Folder", parent=self.window)
        if folder:
            self.specs_var.set(folder)
