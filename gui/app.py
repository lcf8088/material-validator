"""
Material Cert Validator - Desktop GUI Application

Main application window with drag-drop PDF support.
Uses PaddleOCR + Claude pipeline for extraction and validation.
"""

import json
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, Any

try:
    import customtkinter as ctk
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    import tkinter as tk
    from tkinter import ttk
    ctk = None
    HAS_DND = False

from tkinter import filedialog, messagebox

from lib.spec_loader import SpecLoader
from lib.validator import SpecValidator, format_validation_report
from lib.matcher import SpecMatcher
from lib.sanity import run_all_sanity_checks, format_sanity_report
from lib.history import ValidationHistory
from lib.pipeline import process_document, PipelineResult
from lib.watcher import FolderWatcher

from .config import Config
from .tiff_export import convert_to_archive, generate_archive_filename
from .settings import SettingsDialog

logger = logging.getLogger(__name__)


class MaterialValidatorApp:
    """Main application class."""

    def __init__(self):
        self.config = Config()
        self.spec_loader = SpecLoader.get_instance(str(Path(__file__).parent.parent / 'specs'))
        self.validator = SpecValidator()
        self.matcher = SpecMatcher()
        self.history = ValidationHistory()
        self.watcher = FolderWatcher()

        # Current state
        self.current_file: Optional[str] = None
        self.extracted_data: Optional[Dict[str, Any]] = None
        self.validation_result = None
        self.pipeline_result: Optional[PipelineResult] = None

        self._setup_window()
        self._setup_ui()

        # Auto-start folder watch if configured
        watch_folder = self.config.get('watch_folder', '')
        if watch_folder and Path(watch_folder).is_dir():
            self._start_watching(watch_folder)

    def _setup_window(self):
        """Initialize the main window."""
        if ctk and HAS_DND:
            self.root = TkinterDnD.Tk()
            ctk.set_appearance_mode(self.config.get('theme', 'dark'))
            ctk.set_default_color_theme('blue')
        elif ctk:
            self.root = ctk.CTk()
            ctk.set_appearance_mode(self.config.get('theme', 'dark'))
        else:
            self.root = tk.Tk()

        self.root.title("Material Cert Validator")
        self.root.geometry(f"{self.config.get('window_width', 1000)}x{self.config.get('window_height', 700)}")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_ui(self):
        """Create the UI layout."""
        if ctk:
            main_frame = ctk.CTkFrame(self.root)
            main_frame.pack(fill='both', expand=True, padx=10, pady=10)
        else:
            main_frame = ttk.Frame(self.root, padding=10)
            main_frame.pack(fill='both', expand=True)

        self._create_file_section(main_frame)
        self._create_main_section(main_frame)
        self._create_action_section(main_frame)

    def _create_file_section(self, parent):
        """Create file input section with drag-drop."""
        if ctk:
            frame = ctk.CTkFrame(parent)
            frame.pack(fill='x', pady=(0, 10))

            self.drop_zone = ctk.CTkLabel(
                frame,
                text="Drop MTR PDF/Image here\nor click to browse",
                height=80,
                fg_color=("gray85", "gray20"),
                corner_radius=10,
                cursor="hand2"
            )
            self.drop_zone.pack(fill='x', padx=10, pady=10)
            self.drop_zone.bind("<Button-1>", lambda e: self._browse_file())

            if HAS_DND:
                self.drop_zone.drop_target_register(DND_FILES)
                self.drop_zone.dnd_bind('<<Drop>>', self._on_drop)

            self.file_label = ctk.CTkLabel(frame, text="No file selected")
            self.file_label.pack(pady=(0, 10))
        else:
            frame = ttk.LabelFrame(parent, text="Input File", padding=10)
            frame.pack(fill='x', pady=(0, 10))

            btn = ttk.Button(frame, text="Browse...", command=self._browse_file)
            btn.pack(side='left', padx=5)

            self.file_label = ttk.Label(frame, text="No file selected")
            self.file_label.pack(side='left', padx=10)

    def _create_main_section(self, parent):
        """Create main content section."""
        if ctk:
            columns = ctk.CTkFrame(parent)
            columns.pack(fill='both', expand=True, pady=10)
            columns.grid_columnconfigure(0, weight=1)
            columns.grid_columnconfigure(1, weight=1)
            columns.grid_rowconfigure(0, weight=1)

            # Left: Extracted data
            left_frame = ctk.CTkFrame(columns)
            left_frame.grid(row=0, column=0, sticky='nsew', padx=(0, 5))

            ctk.CTkLabel(left_frame, text="Extracted Data", font=("", 14, "bold")).pack(pady=10)

            self.data_text = ctk.CTkTextbox(left_frame, width=400)
            self.data_text.pack(fill='both', expand=True, padx=10, pady=(0, 10))

            # Right: Validation result
            right_frame = ctk.CTkFrame(columns)
            right_frame.grid(row=0, column=1, sticky='nsew', padx=(5, 0))

            ctk.CTkLabel(right_frame, text="Validation Result", font=("", 14, "bold")).pack(pady=10)

            self.result_text = ctk.CTkTextbox(right_frame, width=400)
            self.result_text.pack(fill='both', expand=True, padx=10, pady=(0, 10))

            # Spec selector
            spec_frame = ctk.CTkFrame(right_frame)
            spec_frame.pack(fill='x', padx=10, pady=(0, 10))

            ctk.CTkLabel(spec_frame, text="Spec:").pack(side='left', padx=5)

            specs = ['Auto-detect'] + self.spec_loader.list_ids()
            self.spec_var = ctk.StringVar(value='Auto-detect')
            self.spec_dropdown = ctk.CTkComboBox(spec_frame, values=specs, variable=self.spec_var)
            self.spec_dropdown.pack(side='left', padx=5, fill='x', expand=True)
        else:
            frame = ttk.Frame(parent)
            frame.pack(fill='both', expand=True)

            self.data_text = tk.Text(frame, width=50, height=20)
            self.data_text.pack(side='left', fill='both', expand=True, padx=5)

            self.result_text = tk.Text(frame, width=50, height=20)
            self.result_text.pack(side='right', fill='both', expand=True, padx=5)

            self.spec_var = tk.StringVar(value='Auto-detect')

    def _create_action_section(self, parent):
        """Create action buttons and status bar."""
        if ctk:
            frame = ctk.CTkFrame(parent)
            frame.pack(fill='x', pady=(10, 0))

            btn_frame = ctk.CTkFrame(frame)
            btn_frame.pack(pady=10)

            self.extract_btn = ctk.CTkButton(
                btn_frame, text="1. Extract", command=self._extract,
                width=120, state='disabled'
            )
            self.extract_btn.pack(side='left', padx=5)

            self.validate_btn = ctk.CTkButton(
                btn_frame, text="2. Validate", command=self._validate,
                width=120, state='disabled'
            )
            self.validate_btn.pack(side='left', padx=5)

            self.archive_btn = ctk.CTkButton(
                btn_frame, text="3. Archive", command=self._archive,
                width=120, state='disabled'
            )
            self.archive_btn.pack(side='left', padx=5)

            # Watch folder toggle
            self.watch_btn = ctk.CTkButton(
                btn_frame, text="Watch: OFF", command=self._toggle_watch,
                width=100, fg_color=("gray70", "gray30")
            )
            self.watch_btn.pack(side='left', padx=10)

            ctk.CTkButton(
                btn_frame, text="Settings", command=self._show_settings,
                width=100
            ).pack(side='left', padx=5)

            # Status / progress bar
            self.status_label = ctk.CTkLabel(frame, text="Ready")
            self.status_label.pack(pady=5)

            self.progress_bar = ctk.CTkProgressBar(frame, width=400)
            self.progress_bar.pack(pady=(0, 10))
            self.progress_bar.set(0)
        else:
            frame = ttk.Frame(parent)
            frame.pack(fill='x', pady=10)

            self.extract_btn = ttk.Button(frame, text="Extract", command=self._extract, state='disabled')
            self.extract_btn.pack(side='left', padx=5)

            self.validate_btn = ttk.Button(frame, text="Validate", command=self._validate, state='disabled')
            self.validate_btn.pack(side='left', padx=5)

            self.archive_btn = ttk.Button(frame, text="Archive", command=self._archive, state='disabled')
            self.archive_btn.pack(side='left', padx=5)

            self.watch_btn = ttk.Button(frame, text="Watch: OFF", command=self._toggle_watch)
            self.watch_btn.pack(side='left', padx=10)

            self.status_label = ttk.Label(frame, text="Ready")
            self.status_label.pack(side='right', padx=10)

            self.progress_bar = None  # No progress bar in fallback mode

    # ------------------------------------------------------------- File I/O

    def _on_drop(self, event):
        """Handle file drop."""
        file_path = event.data
        if file_path.startswith('{') and file_path.endswith('}'):
            file_path = file_path[1:-1]
        self._load_file(file_path)

    def _browse_file(self):
        """Open file browser."""
        file_path = filedialog.askopenfilename(
            title="Select MTR File",
            filetypes=[
                ("PDF files", "*.pdf"),
                ("Images", "*.png *.jpg *.jpeg *.tiff *.tif"),
                ("All files", "*.*")
            ],
            initialdir=self.config.get('last_input_folder', '')
        )
        if file_path:
            self._load_file(file_path)

    def _load_file(self, file_path: str):
        """Load a file for processing."""
        self.current_file = file_path
        self.extracted_data = None
        self.validation_result = None
        self.pipeline_result = None

        filename = Path(file_path).name
        if ctk:
            self.file_label.configure(text=filename)
            self.drop_zone.configure(text=f"{filename}\n(click to change)")
            self.extract_btn.configure(state='normal')
            self.validate_btn.configure(state='disabled')
            self.archive_btn.configure(state='disabled')
        else:
            self.file_label.configure(text=filename)
            self.extract_btn.configure(state='normal')

        self.config.set('last_input_folder', str(Path(file_path).parent))
        self._set_status(f"Loaded: {filename}")
        self._clear_text(self.data_text)
        self._clear_text(self.result_text)

    # ------------------------------------------------------------- Pipeline

    def _extract(self):
        """Run the full OCR + Claude extraction pipeline."""
        if not self.current_file:
            return

        if not self.config.is_configured():
            messagebox.showwarning("Setup Required", "Please configure Anthropic API key and archive folder in Settings first.")
            self._show_settings()
            return

        self._set_status("Running pipeline... (OCR + Claude parsing)")
        self._set_button_state(self.extract_btn, 'disabled')
        self._set_progress(0)

        spec_id = self.spec_var.get()
        if spec_id == 'Auto-detect':
            spec_id = None

        def do_pipeline():
            try:
                def on_progress(step, pct):
                    self.root.after(0, lambda: self._set_progress(pct))
                    self.root.after(0, lambda: self._set_status(f"Pipeline: {step}"))

                result = process_document(
                    pdf_path=self.current_file,
                    output_dir="",  # Don't archive yet (user clicks Archive separately)
                    spec_id=spec_id,
                    anthropic_api_key=self.config.anthropic_api_key,
                    paddle_model_path=self.config.get('paddle_model_path', '') or None,
                    preprocessing_dpi=self.config.get('preprocessing_dpi', 300),
                    tiff_dpi=self.config.get('tiff_dpi', 300),
                    tiff_compression=self.config.get('tiff_compression', 'lzw'),
                    on_progress=on_progress,
                )

                self.root.after(0, lambda: self._on_pipeline_complete(result))

            except Exception as e:
                self.root.after(0, lambda: self._on_extract_error(str(e)))

        threading.Thread(target=do_pipeline, daemon=True).start()

    def _on_pipeline_complete(self, result: PipelineResult):
        """Handle pipeline completion."""
        self.pipeline_result = result
        self.extracted_data = result.normalized_data or result.extracted_data
        self.validation_result = result.validation

        self._set_progress(1.0)

        if result.errors:
            self._set_status(f"Pipeline errors: {'; '.join(result.errors)}")
            self._set_button_state(self.extract_btn, 'normal')
            self._insert_text(self.data_text, "\n".join(result.errors))
            return

        # Display extracted data
        self._clear_text(self.data_text)
        self._insert_text(self.data_text, json.dumps(self.extracted_data, indent=2))

        # Display validation if available
        if result.validation:
            self._clear_text(self.result_text)
            self._insert_text(self.result_text, format_validation_report(result.validation, use_color=False))

            status = result.validation.overall_status
            heat = result.validation.heat_number
            self._set_status(f"{status} - Heat# {heat} (Spec: {result.spec_id})")
        else:
            # Show sanity checks if no validation
            if result.sanity and any(result.sanity.values()):
                self._insert_text(self.result_text, format_sanity_report(result.sanity))
            heat = self.extracted_data.get('heat_number', 'N/A')
            self._set_status(f"Extracted: Heat# {heat}")

        # Show compliance flags from Claude
        if result.compliance_flags:
            flags_text = "\n\nCompliance Flags (from Claude):\n"
            for flag in result.compliance_flags:
                flags_text += f"  - {flag.get('field', '?')}: {flag.get('value', '?')} ({flag.get('status', '?')})\n"
            self._insert_text(self.result_text, flags_text)

        self._set_button_state(self.extract_btn, 'normal')

        # Enable validate if we have data but no validation yet
        if not result.validation and self.extracted_data:
            self._set_button_state(self.validate_btn, 'normal')

        # Enable archive
        if result.validation and result.validation.overall_status in ('PASS', 'INCOMPLETE'):
            self._set_button_state(self.archive_btn, 'normal')
        elif self.extracted_data:
            self._set_button_state(self.archive_btn, 'normal')

    def _on_extract_error(self, error: str):
        """Handle extraction error."""
        self._set_status(f"Error: {error}")
        self._set_button_state(self.extract_btn, 'normal')
        self._set_progress(0)
        messagebox.showerror("Pipeline Failed", error)

    def _validate(self):
        """Run validation on extracted data (if not done by pipeline)."""
        if not self.extracted_data:
            return

        spec_id = self.spec_var.get()
        if spec_id == 'Auto-detect':
            match = self.matcher.select_best_spec(self.extracted_data)
            if match:
                spec_id, confidence, reason = match
                self._set_status(f"Auto-detected: {spec_id} ({confidence:.0%})")
            else:
                messagebox.showwarning("No Match", "Could not auto-detect specification. Please select manually.")
                return

        result = self.validator.validate(self.extracted_data, spec_id)
        self.validation_result = result

        self._clear_text(self.result_text)
        self._insert_text(self.result_text, format_validation_report(result, use_color=False))

        self._set_status(f"{result.overall_status} - Heat# {result.heat_number}")

        spec = self.spec_loader.get(spec_id)
        self.history.record(result, self.extracted_data, spec, self.current_file)

        if result.overall_status in ('PASS', 'INCOMPLETE'):
            self._set_button_state(self.archive_btn, 'normal')

    def _archive(self):
        """Convert and save to archive folder."""
        if not self.current_file or not self.extracted_data:
            return

        archive_folder = self.config.archive_folder
        if not archive_folder:
            messagebox.showwarning("Setup Required", "Please configure archive folder in Settings.")
            self._show_settings()
            return

        po_number = self.extracted_data.get('po_number')
        if not po_number:
            po_number = self._prompt_for_po()

        heat_number = self.extracted_data.get('heat_number', 'UNKNOWN')

        success, message, output_path = convert_to_archive(
            self.current_file,
            archive_folder,
            heat_number,
            po_number,
            self.config.get('tiff_dpi', 300),
            self.config.get('tiff_compression', 'lzw')
        )

        if success:
            self._set_status(f"Archived: {Path(output_path).name}")
            messagebox.showinfo("Archived", f"Saved to:\n{output_path}")
        else:
            self._set_status(f"Archive failed: {message}")
            messagebox.showerror("Archive Failed", message)

    def _prompt_for_po(self) -> Optional[str]:
        """Prompt user for PO number."""
        if ctk:
            dialog = ctk.CTkInputDialog(
                text="Enter PO Number (or leave blank):",
                title="PO Number"
            )
            return dialog.get_input()
        else:
            from tkinter import simpledialog
            return simpledialog.askstring("PO Number", "Enter PO Number (or leave blank):")

    # ------------------------------------------------------------- Watch

    def _toggle_watch(self):
        """Toggle folder watching on/off."""
        if self.watcher.is_watching():
            self._stop_watching()
        else:
            watch_folder = self.config.get('watch_folder', '')
            if not watch_folder:
                messagebox.showinfo("Watch Folder", "Set a watch folder in Settings first.")
                self._show_settings()
                return
            self._start_watching(watch_folder)

    def _start_watching(self, folder: str):
        """Start watching a folder for new files."""
        def on_new_file(file_path: str):
            logger.info("Watch: new file detected: %s", file_path)
            self.root.after(0, lambda: self._load_file(file_path))
            # Auto-extract if configured
            self.root.after(500, lambda: self._extract())

        self.watcher.start_watching(folder, on_new_file)
        self._update_watch_button(True)
        self._set_status(f"Watching: {folder}")

    def _stop_watching(self):
        """Stop the folder watcher."""
        self.watcher.stop_watching()
        self._update_watch_button(False)
        self._set_status("Watch stopped")

    def _update_watch_button(self, is_watching: bool):
        """Update the watch button appearance."""
        if is_watching:
            if ctk:
                self.watch_btn.configure(text="Watch: ON", fg_color=("green", "darkgreen"))
            else:
                self.watch_btn.configure(text="Watch: ON")
        else:
            if ctk:
                self.watch_btn.configure(text="Watch: OFF", fg_color=("gray70", "gray30"))
            else:
                self.watch_btn.configure(text="Watch: OFF")

    # ------------------------------------------------------------- Settings

    def _show_settings(self):
        """Show settings dialog."""
        dialog = SettingsDialog(self.root, self.config, self.spec_loader)
        if dialog.saved:
            specs = ['Auto-detect'] + self.spec_loader.list_ids()
            if ctk:
                self.spec_dropdown.configure(values=specs)
            self._set_status("Settings saved")

    # ------------------------------------------------------------- Helpers

    def _set_status(self, text: str):
        """Update status bar."""
        self.status_label.configure(text=text)

    def _set_button_state(self, button, state: str):
        """Set button state."""
        button.configure(state=state)

    def _set_progress(self, value: float):
        """Update progress bar (0.0 to 1.0)."""
        if ctk and hasattr(self, 'progress_bar') and self.progress_bar:
            self.progress_bar.set(value)

    def _clear_text(self, widget):
        """Clear text widget."""
        widget.delete('1.0', 'end')

    def _insert_text(self, widget, text: str):
        """Insert text into widget."""
        widget.insert('end', text)

    def _on_close(self):
        """Handle window close."""
        if self.watcher.is_watching():
            self.watcher.stop_watching()
        self.config.update({
            'window_width': self.root.winfo_width(),
            'window_height': self.root.winfo_height(),
        })
        self.root.destroy()

    def run(self):
        """Start the application."""
        self.root.mainloop()


def main():
    """Application entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    )
    app = MaterialValidatorApp()
    app.run()


if __name__ == '__main__':
    main()
