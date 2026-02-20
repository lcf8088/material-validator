"""
Downhole & Design MTR Validator - Desktop GUI Application

Main application window with sidebar navigation, D&D branded dark theme,
card-based content panels, and colored status badges.
Uses PaddleOCR + Claude pipeline for extraction and validation.
"""

import glob
import json
import logging
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

# Add NVIDIA CUDA DLL paths before any onnxruntime import (via pipeline -> gpu_ocr)
_site_packages = os.path.join(sys.prefix, 'Lib', 'site-packages')
_nvidia_bins = [d for d in glob.glob(os.path.join(_site_packages, 'nvidia', '*', 'bin'))
                if os.path.isdir(d)]
if _nvidia_bins:
    os.environ['PATH'] = ';'.join(_nvidia_bins) + ';' + os.environ.get('PATH', '')

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
from lib.validator import SpecValidator, CertValidation, format_validation_report
from lib.matcher import SpecMatcher
from lib.sanity import run_all_sanity_checks, format_sanity_report
from lib.history import ValidationHistory
from lib.pipeline import process_document, pre_extract, PipelineResult
from lib.watcher import FolderWatcher

from .config import Config
from .tiff_export import generate_archive_filename, generate_assembly_archive_filename, sanitize_filename
from .settings import SettingsPanel
from .override_dialog import OverrideDialog
from .theme import COLORS, FONTS, ICONS, SIDEBAR_WIDTH, status_color, ScrollableComboBox

logger = logging.getLogger(__name__)

APP_TITLE = "Downhole & Design MTR Validator"
APP_VERSION = "1.0"
LOGO_PATH = Path(__file__).parent / 'logo.jpg'


def _load_logo_image(root):
    """Load the D&D logo as a Tk PhotoImage for the window icon."""
    try:
        from PIL import Image, ImageTk
        img = Image.open(LOGO_PATH)
        photo = ImageTk.PhotoImage(img)
        root.iconphoto(True, photo)
        return photo  # must keep reference
    except Exception:
        return None


def _load_sidebar_logo():
    """Load the D&D logo for the sidebar with transparent background."""
    try:
        import numpy as np
        from PIL import Image
        img = Image.open(LOGO_PATH).convert('RGBA')
        data = np.array(img)
        # Make near-white pixels transparent (white JPG background)
        white_mask = (data[:, :, 0] > 220) & (data[:, :, 1] > 220) & (data[:, :, 2] > 220)
        data[white_mask, 3] = 0
        img = Image.fromarray(data)
        return ctk.CTkImage(light_image=img, dark_image=img, size=(100, 100))
    except Exception:
        try:
            from PIL import Image
            img = Image.open(LOGO_PATH)
            return ctk.CTkImage(light_image=img, dark_image=img, size=(100, 100))
        except Exception:
            return None


def _get_identifier(data: dict) -> tuple:
    """Return (label, value) for the lot identifier — Heat# or Batch# depending on material.

    Elastomers use batch_number; metals use heat_number.
    Falls back to lot_number if neither is present.
    """
    batch = data.get('batch_number')
    heat = data.get('heat_number')
    if batch and not heat:
        return ('Batch', batch)
    if heat:
        return ('Heat', heat)
    lot = data.get('lot_number')
    if lot:
        return ('Lot', lot)
    return ('Heat', 'N/A')


class MaterialValidatorApp:
    """Main application class with sidebar navigation layout."""

    def __init__(self):
        self.config = Config()
        self.spec_loader = SpecLoader.get_instance(str(Path(__file__).parent.parent.parent / 'specs'))
        self.validator = SpecValidator()
        self.matcher = SpecMatcher()
        self.history = ValidationHistory()
        self.watcher = FolderWatcher()

        # Current state
        self.current_file: Optional[str] = None
        self.extracted_data: Optional[Dict[str, Any]] = None
        self.validation_result = None
        self.pipeline_result: Optional[PipelineResult] = None
        self.settings_panel: Optional[SettingsPanel] = None

        # Approval queue state
        self._batch_running = False
        self._approval_queue: List[PipelineResult] = []
        self.staging_tiff_path: Optional[str] = None
        self._pipeline_lock = threading.Lock()
        self._override_operator: str = ""
        self._current_history_id: Optional[str] = None

        # Watch queue state
        self._watch_queue: List[str] = []
        self._watch_worker_running = False
        self._watch_first_shown = False

        # History filter state
        self._history_filter: str = "all"

        # View navigation state
        self.current_view = 'validate'
        self.content_frames: Dict[str, Any] = {}
        self.nav_buttons: Dict[str, Any] = {}

        # Keep references to images so they aren't garbage collected
        self._logo_photo = None
        self._sidebar_logo = None

        self._setup_window()
        self._setup_ui()

        # Auto-start folder watch if configured
        watch_folder = self.config.get('watch_folder', '')
        if watch_folder and Path(watch_folder).is_dir():
            self._start_watching(watch_folder)

    # ============================================================= Window
    def _setup_window(self):
        """Initialize the main window."""
        if ctk and HAS_DND:
            self.root = TkinterDnD.Tk()
            if not hasattr(self.root, '_block_update_dimensions_event'):
                self.root._block_update_dimensions_event = False
            if not hasattr(self.root, 'block_update_dimensions_event'):
                self.root.block_update_dimensions_event = lambda: setattr(self.root, '_block_update_dimensions_event', True)
            if not hasattr(self.root, 'unblock_update_dimensions_event'):
                self.root.unblock_update_dimensions_event = lambda: setattr(self.root, '_block_update_dimensions_event', False)
            ctk.set_appearance_mode(self.config.get('theme', 'dark'))
            ctk.set_default_color_theme('blue')
        elif ctk:
            self.root = ctk.CTk()
            ctk.set_appearance_mode(self.config.get('theme', 'dark'))
        else:
            self.root = tk.Tk()

        self.root.title(APP_TITLE)
        self.root.geometry(
            f"{self.config.get('window_width', 1200)}x{self.config.get('window_height', 750)}"
        )
        self.root.minsize(900, 600)

        # TkinterDnD.Tk() is a plain Tk root — use bg, not fg_color
        if ctk and not HAS_DND:
            self.root.configure(fg_color=COLORS['bg_darkest'])
        else:
            self.root.configure(bg=COLORS['bg_darkest'])

        # Set window icon from logo
        self._logo_photo = _load_logo_image(self.root)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ============================================================= UI Setup
    def _setup_ui(self):
        """Build the 3-zone layout: header, sidebar, content."""
        if not ctk:
            self._setup_ui_fallback()
            return

        # --- Header bar ---
        self._create_header(self.root)

        # --- Body: sidebar + content ---
        body = ctk.CTkFrame(self.root, fg_color=COLORS['bg_darkest'])
        body.pack(fill='both', expand=True)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self._create_sidebar(body)

        # Content area
        self.content_area = ctk.CTkFrame(body, fg_color=COLORS['bg_darkest'])
        self.content_area.grid(row=0, column=1, sticky='nsew', padx=(0, 8), pady=(0, 8))

        # Build all views (only one shown at a time)
        self._create_validate_view()
        self._create_history_view()
        self._create_settings_view()

        # Show initial view
        self._navigate_to('validate')

    def _setup_ui_fallback(self):
        """Fallback layout for standard tkinter (no customtkinter)."""
        self.main_frame = ttk.Frame(self.root, padding=10)
        self.main_frame.pack(fill='both', expand=True)
        self._create_file_section_fallback(self.main_frame)
        self._create_main_section_fallback(self.main_frame)
        self._create_action_section_fallback(self.main_frame)

    # ============================================================= Header
    def _create_header(self, parent):
        """Create a clean header bar: brand left, file info + badge right."""
        header = ctk.CTkFrame(parent, fg_color=COLORS['bg_dark'], height=48, corner_radius=0)
        header.pack(fill='x')
        header.pack_propagate(False)

        # Left: single clean title
        ctk.CTkLabel(
            header, text="D&D  MTR Validator",
            font=('Segoe UI', 17, 'bold'), text_color=COLORS['text_primary'],
        ).pack(side='left', padx=20, pady=0)

        # Right: file info and status badge, evenly spaced
        right = ctk.CTkFrame(header, fg_color='transparent')
        right.pack(side='right', padx=20)

        self.header_badge = ctk.CTkLabel(
            right, text="  Ready  ", font=FONTS['badge'],
            fg_color=COLORS['surface_hl'], text_color=COLORS['text_secondary'],
            corner_radius=12, height=26,
        )
        self.header_badge.pack(side='right')

        # Subtle separator dot between file and badge
        ctk.CTkLabel(
            right, text="\u2022", font=FONTS['label'],
            text_color=COLORS['border'],
        ).pack(side='right', padx=10)

        self.header_file_label = ctk.CTkLabel(
            right, text="No file loaded", font=FONTS['label'],
            text_color=COLORS['text_secondary'],
        )
        self.header_file_label.pack(side='right')

        # Thin progress bar under header — orange on dark track
        self.progress_bar = ctk.CTkProgressBar(
            parent, height=2, corner_radius=0,
            fg_color=COLORS['bg_dark'], progress_color=COLORS['orange'],
        )
        self.progress_bar.pack(fill='x')
        self.progress_bar.set(0)

    def _update_header_status(self, status: str, info: str = ""):
        """Update the header badge color and text."""
        if not ctk:
            return
        color = status_color(status)
        display = status if not info else f"{status}"
        self.header_badge.configure(text=display, fg_color=color, text_color=COLORS['bg_darkest'])
        if info:
            self.header_file_label.configure(text=info, text_color=COLORS['text_primary'])

    # ============================================================= Sidebar
    def _create_sidebar(self, parent):
        """Create sidebar with D&D logo and navigation items."""
        sidebar = ctk.CTkFrame(
            parent, fg_color=COLORS['bg_dark'], width=SIDEBAR_WIDTH, corner_radius=0,
        )
        sidebar.grid(row=0, column=0, sticky='ns', padx=(8, 0), pady=(0, 8))
        sidebar.grid_propagate(False)

        # ---- Brand area: logo centered with company name ----
        brand_frame = ctk.CTkFrame(sidebar, fg_color='transparent')
        brand_frame.pack(fill='x', pady=(20, 0))

        self._sidebar_logo = _load_sidebar_logo()
        if self._sidebar_logo:
            ctk.CTkLabel(
                brand_frame, image=self._sidebar_logo, text="",
            ).pack()

        ctk.CTkLabel(
            brand_frame, text="DOWNHOLE & DESIGN",
            font=('Segoe UI', 10, 'bold'), text_color=COLORS['accent_light'],
        ).pack(pady=(8, 0))

        ctk.CTkLabel(
            brand_frame, text="MTR VALIDATOR",
            font=('Segoe UI', 9), text_color=COLORS['text_secondary'],
        ).pack(pady=(1, 0))

        # ---- Orange separator ----
        ctk.CTkFrame(
            sidebar, fg_color=COLORS['orange'], height=1, corner_radius=0,
        ).pack(fill='x', padx=24, pady=(16, 16))

        # ---- Navigation ----
        nav_frame = ctk.CTkFrame(sidebar, fg_color='transparent')
        nav_frame.pack(fill='x')

        self._create_sidebar_nav_item(nav_frame, 'validate', ICONS['validate'], "Validate")
        self._create_sidebar_nav_item(nav_frame, 'history', ICONS['history'], "History")
        self._create_sidebar_nav_item(nav_frame, 'settings', ICONS['settings'], "Settings")

        # ---- Spacer ----
        ctk.CTkFrame(sidebar, fg_color='transparent').pack(fill='both', expand=True)

        # ---- Bottom: watch toggle + version ----
        bottom = ctk.CTkFrame(sidebar, fg_color='transparent')
        bottom.pack(fill='x', padx=12, pady=(0, 16))

        self.watch_btn = ctk.CTkButton(
            bottom,
            text=f"{ICONS['watch_off']}  Watch: OFF",
            font=FONTS['label'], anchor='w',
            fg_color='transparent', hover_color=COLORS['surface_hl'],
            text_color=COLORS['text_secondary'], height=32,
            command=self._toggle_watch,
        )
        self.watch_btn.pack(fill='x')

        ctk.CTkLabel(
            bottom, text=f"v{APP_VERSION}",
            font=('Segoe UI', 9), text_color=COLORS['border'],
        ).pack(pady=(8, 0))

    def _create_sidebar_nav_item(self, parent, view_name: str, icon: str, label: str):
        """Create a sidebar nav button with active indicator."""
        item_frame = ctk.CTkFrame(parent, fg_color='transparent', height=40)
        item_frame.pack(fill='x', padx=0, pady=1)
        item_frame.pack_propagate(False)

        # Active indicator bar (left edge) — orange when active
        indicator = ctk.CTkFrame(item_frame, fg_color='transparent', width=3, corner_radius=2)
        indicator.pack(side='left', fill='y')

        btn = ctk.CTkButton(
            item_frame,
            text=f"  {icon}   {label}",
            font=FONTS['body'], anchor='w',
            fg_color='transparent', hover_color=COLORS['surface_hl'],
            text_color=COLORS['text_secondary'], height=38,
            command=lambda v=view_name: self._navigate_to(v),
        )
        btn.pack(side='left', fill='both', expand=True)

        self.nav_buttons[view_name] = {
            'button': btn,
            'indicator': indicator,
            'frame': item_frame,
        }

    def _navigate_to(self, view: str):
        """Switch content view and update sidebar active states."""
        if not ctk:
            return

        self.current_view = view

        # Hide all content frames
        for frame in self.content_frames.values():
            frame.pack_forget()

        # Show selected
        if view in self.content_frames:
            self.content_frames[view].pack(fill='both', expand=True)

        # Update nav button states — active gets orange indicator bar + blue text
        for name, nav in self.nav_buttons.items():
            if name == view:
                nav['indicator'].configure(fg_color=COLORS['orange'])
                nav['button'].configure(
                    fg_color=COLORS['surface_hl'],
                    text_color=COLORS['text_primary'],
                )
            else:
                nav['indicator'].configure(fg_color='transparent')
                nav['button'].configure(
                    fg_color='transparent',
                    text_color=COLORS['text_secondary'],
                )

        # Refresh data views
        if view == 'history':
            self._refresh_history_view()

    # ============================================================= Validate View
    def _create_validate_view(self):
        """Build the main validation view with drop zone, buttons, data + results."""
        view = ctk.CTkFrame(self.content_area, fg_color=COLORS['bg_darkest'])
        self.content_frames['validate'] = view

        # -- Top row: drop zone + spec selector + buttons --
        top = ctk.CTkFrame(view, fg_color='transparent')
        top.pack(fill='x', padx=4, pady=(4, 0))

        self._create_drop_zone(top)

        # Batch buttons row (below drop zone)
        batch_row = ctk.CTkFrame(top, fg_color='transparent')
        batch_row.pack(fill='x', padx=4, pady=(2, 0))

        self.batch_files_btn = ctk.CTkButton(
            batch_row, text="Batch Files...", width=110, height=28,
            font=FONTS['small'],
            fg_color=COLORS['bg_card'], hover_color=COLORS['surface_hl'],
            border_color=COLORS['border'], border_width=1,
            text_color=COLORS['text_secondary'],
            command=self._batch_files,
        )
        self.batch_files_btn.pack(side='left', padx=(4, 4))

        self.batch_folder_btn = ctk.CTkButton(
            batch_row, text="Batch Folder...", width=110, height=28,
            font=FONTS['small'],
            fg_color=COLORS['bg_card'], hover_color=COLORS['surface_hl'],
            border_color=COLORS['border'], border_width=1,
            text_color=COLORS['text_secondary'],
            command=self._batch_folder,
        )
        self.batch_folder_btn.pack(side='left', padx=(0, 4))

        self.batch_status_label = ctk.CTkLabel(
            batch_row, text="", font=FONTS['small'],
            text_color=COLORS['text_secondary'],
        )
        self.batch_status_label.pack(side='left', padx=(8, 0))

        # Controls row: Spec selector + PO field + action buttons
        controls_row = ctk.CTkFrame(view, fg_color='transparent')
        controls_row.pack(fill='x', padx=4, pady=(8, 0))

        # -- Left group: Spec + PO --
        left_controls = ctk.CTkFrame(controls_row, fg_color='transparent')
        left_controls.pack(side='left')

        # Spec selector
        ctk.CTkLabel(
            left_controls, text="Spec:", font=FONTS['label'],
            text_color=COLORS['text_secondary'],
        ).pack(side='left', padx=(4, 6))

        specs = ['Auto-detect', 'Vendor Spec'] + self._spec_display_list()
        self.spec_var = ctk.StringVar(value='Auto-detect')
        self.spec_dropdown = ScrollableComboBox(
            left_controls, values=specs, variable=self.spec_var, width=300,
            fg_color=COLORS['bg_input'], border_color=COLORS['border'],
            button_color=COLORS['accent'], button_hover_color=COLORS['accent_hover'],
            dropdown_fg_color=COLORS['bg_card'], dropdown_hover_color=COLORS['surface_hl'],
            dropdown_text_color=COLORS['text_primary'],
            text_color=COLORS['text_primary'], font=FONTS['body'],
        )
        self.spec_dropdown.pack(side='left')

        # PO number field (sticky — persists between validations)
        ctk.CTkLabel(
            left_controls, text="PO#:", font=FONTS['label'],
            text_color=COLORS['text_secondary'],
        ).pack(side='left', padx=(16, 6))

        self.po_var = ctk.StringVar(value='')
        self.po_entry = ctk.CTkEntry(
            left_controls, textvariable=self.po_var, width=140,
            placeholder_text="Enter or scan PO",
            fg_color=COLORS['bg_input'], border_color=COLORS['border'],
            text_color=COLORS['text_primary'], font=FONTS['body'],
        )
        self.po_entry.pack(side='left')

        ctk.CTkButton(
            left_controls, text="Clear", width=50, height=28,
            font=FONTS['small'],
            fg_color='transparent', hover_color=COLORS['surface_hl'],
            text_color=COLORS['text_secondary'],
            command=lambda: self.po_var.set(''),
        ).pack(side='left', padx=(4, 0))

        # Approved By field (sticky — persists between validations)
        ctk.CTkLabel(
            left_controls, text="Approved By:", font=FONTS['label'],
            text_color=COLORS['text_secondary'],
        ).pack(side='left', padx=(16, 6))

        self.approved_by_var = ctk.StringVar(value='')
        self.approved_by_entry = ctk.CTkEntry(
            left_controls, textvariable=self.approved_by_var, width=150,
            placeholder_text="Your name",
            fg_color=COLORS['bg_input'], border_color=COLORS['border'],
            text_color=COLORS['text_primary'], font=FONTS['body'],
        )
        self.approved_by_entry.pack(side='left')

        # -- Right group: action buttons --
        btn_frame = ctk.CTkFrame(controls_row, fg_color='transparent')
        btn_frame.pack(side='right')

        self.extract_btn = ctk.CTkButton(
            btn_frame, text="Extract & Validate", width=160,
            font=FONTS['badge'], state='disabled',
            fg_color=COLORS['accent'], hover_color=COLORS['accent_hover'],
            text_color='#FFFFFF', text_color_disabled=COLORS['btn_disabled_text'],
            command=self._extract,
        )
        self.extract_btn.pack(side='left', padx=4)

        self.validate_btn = ctk.CTkButton(
            btn_frame, text="Re-Validate", width=110,
            font=FONTS['badge'], state='disabled',
            fg_color=COLORS['bg_card'], hover_color=COLORS['surface_hl'],
            border_color=COLORS['border'], border_width=1,
            text_color='#FFFFFF', text_color_disabled=COLORS['btn_disabled_text'],
            command=self._validate,
        )
        self.validate_btn.pack(side='left', padx=4)

        self.override_btn = ctk.CTkButton(
            btn_frame, text="Override", width=100,
            font=FONTS['badge'], state='disabled',
            fg_color=COLORS['orange'], hover_color=COLORS['orange_hover'],
            text_color='#FFFFFF', text_color_disabled=COLORS['btn_disabled_text'],
            command=self._open_override_dialog,
        )
        self.override_btn.pack(side='left', padx=4)

        self.add_heat_btn = ctk.CTkButton(
            btn_frame, text="Add Missing Heat", width=130,
            font=FONTS['badge'], state='disabled',
            fg_color=COLORS['orange'], hover_color=COLORS['orange_hover'],
            text_color='#FFFFFF', text_color_disabled=COLORS['btn_disabled_text'],
            command=self._add_missing_heat,
        )
        # Hidden by default — shown only for assembly results with missing heats

        self.preview_btn = ctk.CTkButton(
            btn_frame, text="Preview", width=90,
            font=FONTS['badge'], state='disabled',
            fg_color=COLORS['bg_card'], hover_color=COLORS['surface_hl'],
            border_color=COLORS['border'], border_width=1,
            text_color='#FFFFFF', text_color_disabled=COLORS['btn_disabled_text'],
            command=self._preview_tiff,
        )
        self.preview_btn.pack(side='left', padx=4)

        self.approve_btn = ctk.CTkButton(
            btn_frame, text="Approve", width=110,
            font=FONTS['badge'], state='disabled',
            fg_color=COLORS['success'], hover_color='#4A9A3A',
            text_color='#FFFFFF', text_color_disabled=COLORS['btn_disabled_text'],
            command=self._approve,
        )
        self.approve_btn.pack(side='left', padx=4)

        # Queue indicator (visible when watch queues items)
        self.queue_label = ctk.CTkLabel(
            btn_frame, text="", font=FONTS['small'],
            text_color=COLORS['orange'],
        )
        self.queue_label.pack(side='left', padx=(8, 0))

        # -- Assembly row (hidden by default, shown when assembly detected) --
        self.assembly_row = ctk.CTkFrame(view, fg_color='transparent')
        # Not packed by default — shown dynamically

        ctk.CTkLabel(
            self.assembly_row, text="Mode:", font=FONTS['label'],
            text_color=COLORS['text_secondary'],
        ).pack(side='left', padx=(4, 6))

        self.assembly_var = ctk.StringVar(value='Auto')
        self.assembly_dropdown = ctk.CTkOptionMenu(
            self.assembly_row, values=['Auto', 'Assembly', 'Single Part'],
            variable=self.assembly_var, width=110,
            font=FONTS['body'],
            fg_color=COLORS['bg_input'], button_color=COLORS['accent'],
            button_hover_color=COLORS['accent_hover'],
            dropdown_fg_color=COLORS['bg_card'], dropdown_hover_color=COLORS['surface_hl'],
            dropdown_text_color=COLORS['text_primary'],
            text_color=COLORS['text_primary'],
            command=self._on_assembly_mode_change,
        )
        self.assembly_dropdown.pack(side='left')

        self.cust_part_label = ctk.CTkLabel(
            self.assembly_row, text="Cust Part#:", font=FONTS['label'],
            text_color=COLORS['text_secondary'],
        )
        self.cust_part_var = ctk.StringVar(value='')
        self.cust_part_entry = ctk.CTkEntry(
            self.assembly_row, textvariable=self.cust_part_var, width=180,
            placeholder_text="Customer part number",
            fg_color=COLORS['bg_input'], border_color=COLORS['border'],
            text_color=COLORS['text_primary'], font=FONTS['body'],
        )
        self._assembly_result = None  # store for approval flow

        # -- Bottom row: data card + result card --
        self.cards_frame = ctk.CTkFrame(view, fg_color='transparent')
        cards = self.cards_frame
        cards.pack(fill='both', expand=True, padx=4, pady=(8, 4))
        cards.grid_columnconfigure(0, weight=1)
        cards.grid_columnconfigure(1, weight=1)
        cards.grid_rowconfigure(0, weight=1)

        # Extracted Data card
        data_card = self._create_card(cards, "Extracted Data")
        data_card.grid(row=0, column=0, sticky='nsew', padx=(0, 4))

        self.data_text = ctk.CTkTextbox(
            data_card, font=FONTS['mono'],
            fg_color=COLORS['bg_darkest'], text_color=COLORS['text_primary'],
            border_color=COLORS['border'], border_width=1, corner_radius=6,
        )
        self.data_text.pack(fill='both', expand=True, padx=10, pady=(0, 10))

        # Validation Result card
        result_card = self._create_card(cards, "Validation Result")
        result_card.grid(row=0, column=1, sticky='nsew', padx=(4, 0))

        self.result_text = ctk.CTkTextbox(
            result_card, font=FONTS['mono'],
            fg_color=COLORS['bg_darkest'], text_color=COLORS['text_primary'],
            border_color=COLORS['border'], border_width=1, corner_radius=6,
        )
        self.result_text.pack(fill='both', expand=True, padx=10, pady=(0, 10))

        # Configure colored text tags on the underlying tk Text widget
        self._configure_result_tags()

        # Status label (bottom of validate view)
        self.status_label = ctk.CTkLabel(
            view, text="Ready", font=FONTS['label'],
            text_color=COLORS['text_secondary'],
        )
        self.status_label.pack(pady=(0, 6))

    def _create_drop_zone(self, parent):
        """Create the file drop zone — orange border glow on hover."""
        # Outer border frame
        outer = ctk.CTkFrame(
            parent, fg_color=COLORS['border'], corner_radius=12,
        )
        outer.pack(fill='x', padx=4, pady=4)

        # Inner drop area
        self.drop_zone = ctk.CTkLabel(
            outer,
            text=f"{ICONS['drop']}   Drop MTR PDF / Image here\nor click to browse",
            font=FONTS['body'], text_color=COLORS['text_secondary'],
            fg_color=COLORS['bg_card'], corner_radius=10,
            height=72, cursor='hand2',
        )
        self.drop_zone.pack(fill='x', padx=2, pady=2)
        self.drop_zone.bind("<Button-1>", lambda e: self._browse_file())

        # Hover effects — orange border pop
        def on_enter(e):
            outer.configure(fg_color=COLORS['orange'])
            self.drop_zone.configure(text_color=COLORS['text_primary'])

        def on_leave(e):
            outer.configure(fg_color=COLORS['border'])
            self.drop_zone.configure(text_color=COLORS['text_secondary'])

        self.drop_zone.bind("<Enter>", on_enter)
        self.drop_zone.bind("<Leave>", on_leave)

        if HAS_DND:
            self.drop_zone.drop_target_register(DND_FILES)
            self.drop_zone.dnd_bind('<<Drop>>', self._on_drop)

        self._drop_zone_outer = outer

    def _create_card(self, parent, title: str):
        """Reusable card factory: bg_card panel with title header."""
        card = ctk.CTkFrame(
            parent, fg_color=COLORS['bg_card'], corner_radius=8,
            border_color=COLORS['border'], border_width=1,
        )

        # Card title row with subtle orange left accent
        title_bar = ctk.CTkFrame(card, fg_color='transparent', height=36)
        title_bar.pack(fill='x', padx=10, pady=(8, 4))
        title_bar.pack_propagate(False)

        # Small orange dot before title
        ctk.CTkLabel(
            title_bar, text=ICONS['pass'], font=('Segoe UI', 8),
            text_color=COLORS['orange'],
        ).pack(side='left', padx=(0, 6))

        ctk.CTkLabel(
            title_bar, text=title, font=FONTS['card_title'],
            text_color=COLORS['text_primary'],
        ).pack(side='left')

        return card

    def _create_status_badge(self, parent, text: str, status: str):
        """Create a small colored pill badge."""
        color = status_color(status)
        badge = ctk.CTkLabel(
            parent, text=f" {text} ", font=FONTS['badge'],
            fg_color=color, text_color=COLORS['bg_darkest'],
            corner_radius=12, height=24,
        )
        return badge

    def _configure_result_tags(self):
        """Set up text tags on the result textbox for colored output."""
        tw = self.result_text._textbox
        tw.tag_configure('pass', foreground=COLORS['success'])
        tw.tag_configure('fail', foreground=COLORS['error'])
        tw.tag_configure('missing', foreground=COLORS['text_secondary'])
        tw.tag_configure('skip', foreground=COLORS['text_secondary'])
        tw.tag_configure('warn', foreground=COLORS['orange'])
        tw.tag_configure('header', foreground=COLORS['accent_light'])
        tw.tag_configure('label', foreground=COLORS['text_secondary'])
        tw.tag_configure('value', foreground=COLORS['text_primary'])
        tw.tag_configure('override', foreground=COLORS['orange'], font=('Consolas', 11, 'italic'))

        dtw = self.data_text._textbox
        dtw.tag_configure('key', foreground=COLORS['accent_light'])
        dtw.tag_configure('value', foreground=COLORS['text_primary'])
        dtw.tag_configure('label', foreground=COLORS['text_secondary'])

    # ============================================================= History View
    def _create_history_view(self):
        """Build the history view with stats bar, filter bar, and scrollable rows."""
        view = ctk.CTkFrame(self.content_area, fg_color=COLORS['bg_darkest'])
        self.content_frames['history'] = view

        # Stats bar
        self.history_stats_frame = ctk.CTkFrame(view, fg_color=COLORS['bg_card'], corner_radius=8, height=60)
        self.history_stats_frame.pack(fill='x', padx=8, pady=(8, 4))
        self.history_stats_frame.pack_propagate(False)

        # Filter bar
        filter_frame = ctk.CTkFrame(view, fg_color='transparent', height=36)
        filter_frame.pack(fill='x', padx=8, pady=(4, 0))
        filter_frame.pack_propagate(False)

        self._history_filter_buttons: Dict[str, Any] = {}
        for filter_name in ['All', 'Pending', 'Approved', 'Pass', 'Fail', 'Incomplete']:
            btn = ctk.CTkButton(
                filter_frame, text=filter_name, width=90, height=28,
                font=FONTS['label'], corner_radius=14,
                fg_color=COLORS['bg_card'], hover_color=COLORS['surface_hl'],
                border_color=COLORS['border'], border_width=1,
                text_color=COLORS['text_secondary'],
                command=lambda f=filter_name.lower(): self._set_history_filter(f),
            )
            btn.pack(side='left', padx=2)
            self._history_filter_buttons[filter_name.lower()] = btn

        # Clear history button (right-aligned)
        ctk.CTkButton(
            filter_frame, text="Clear History", width=110, height=28,
            font=FONTS['label'], corner_radius=14,
            fg_color=COLORS['error'], hover_color='#c0392b',
            text_color='#ffffff',
            command=self._clear_history,
        ).pack(side='right', padx=2)

        # Scrollable history list
        self.history_scroll = ctk.CTkScrollableFrame(
            view, fg_color=COLORS['bg_darkest'],
            scrollbar_button_color=COLORS['border'],
            scrollbar_button_hover_color=COLORS['surface_hl'],
        )
        self.history_scroll.pack(fill='both', expand=True, padx=8, pady=(4, 8))

    def _clear_history(self):
        """Clear all history after user confirmation."""
        stats = self.history.stats()
        if stats['total'] == 0:
            messagebox.showinfo("Clear History", "History is already empty.")
            return
        confirmed = messagebox.askyesno(
            "Clear History",
            f"This will permanently delete all {stats['total']} history records.\n\nAre you sure?",
        )
        if confirmed:
            self.history.clear()
            self._refresh_history_view()
            self._set_status("History cleared")

    def _delete_history_record(self, validation_id: str):
        """Delete a single history record after user confirmation."""
        record = self.history.get(validation_id)
        if not record:
            messagebox.showwarning("Delete", "Record not found.")
            return

        heat = record.get('heat_number', 'N/A')
        spec = record.get('spec_id', 'N/A')
        confirmed = messagebox.askyesno(
            "Delete Record",
            f"Delete this record?\n\nHeat: {heat}\nSpec: {spec}\nID: {validation_id}",
        )
        if confirmed:
            self.history.delete(validation_id)
            self._refresh_history_view()
            self._set_status(f"Deleted record {validation_id}")

    def _set_history_filter(self, filter_name: str):
        """Update the active history filter and refresh the view."""
        self._history_filter = filter_name
        self._refresh_history_view()

    def _refresh_history_view(self):
        """Populate history view from history data with active filter applied."""
        for w in self.history_stats_frame.winfo_children():
            w.destroy()

        stats = self.history.stats()
        stats_inner = ctk.CTkFrame(self.history_stats_frame, fg_color='transparent')
        stats_inner.pack(expand=True, fill='both', padx=16, pady=8)

        for label_text, count, color in [
            ("Total", stats.get('total', 0), COLORS['text_primary']),
            ("Pending", stats.get('pending', 0), COLORS['orange']),
            ("Pass", stats.get('pass', 0), COLORS['success']),
            ("Fail", stats.get('fail', 0), COLORS['error']),
            ("Incomplete", stats.get('incomplete', 0), COLORS['text_secondary']),
        ]:
            col = ctk.CTkFrame(stats_inner, fg_color='transparent')
            col.pack(side='left', expand=True)
            ctk.CTkLabel(
                col, text=str(count), font=FONTS['section_header'], text_color=color,
            ).pack()
            ctk.CTkLabel(
                col, text=label_text, font=FONTS['label'], text_color=COLORS['text_secondary'],
            ).pack()

        # Update filter button styling
        if hasattr(self, '_history_filter_buttons'):
            for name, btn in self._history_filter_buttons.items():
                if name == self._history_filter:
                    btn.configure(
                        fg_color=COLORS['accent'], text_color='#FFFFFF',
                        border_color=COLORS['accent'],
                    )
                else:
                    btn.configure(
                        fg_color=COLORS['bg_card'], text_color=COLORS['text_secondary'],
                        border_color=COLORS['border'],
                    )

        for w in self.history_scroll.winfo_children():
            w.destroy()

        records = self.history.recent(limit=100)
        if not records:
            ctk.CTkLabel(
                self.history_scroll, text="No validation history yet.",
                font=FONTS['body'], text_color=COLORS['text_secondary'],
            ).pack(pady=30)
            return

        # Apply filter
        active_filter = self._history_filter
        filtered = []
        for record in records:
            if active_filter == 'all':
                filtered.append(record)
            elif active_filter == 'pending':
                if not record.get('approved', False):
                    filtered.append(record)
            elif active_filter == 'approved':
                if record.get('approved', False):
                    filtered.append(record)
            elif active_filter == 'pass':
                if record.get('result', '').upper() == 'PASS':
                    filtered.append(record)
            elif active_filter == 'fail':
                if record.get('result', '').upper() == 'FAIL':
                    filtered.append(record)
            elif active_filter == 'incomplete':
                if record.get('result', '').upper() in ('INCOMPLETE', 'UNKNOWN'):
                    filtered.append(record)

        if not filtered:
            ctk.CTkLabel(
                self.history_scroll, text=f"No {active_filter} records.",
                font=FONTS['body'], text_color=COLORS['text_secondary'],
            ).pack(pady=30)
            return

        for record in reversed(filtered):
            self._create_history_row(self.history_scroll, record)

    def _create_history_row(self, parent, record: dict):
        """Create a single history row — pending items show Review, approved show View Report."""
        is_approved = record.get('approved', False)

        row = ctk.CTkFrame(
            parent, fg_color=COLORS['bg_card'], corner_radius=6, height=44,
            border_color=COLORS['orange'] if not is_approved else COLORS['border'],
            border_width=1,
        )
        row.pack(fill='x', pady=2)
        row.pack_propagate(False)

        inner = ctk.CTkFrame(row, fg_color='transparent')
        inner.pack(fill='both', expand=True, padx=12, pady=4)

        # -- Left side: result badge + approval badge + identifier + spec --
        result_status = record.get('result', 'UNKNOWN')
        badge = self._create_status_badge(inner, result_status, result_status)
        badge.pack(side='left', padx=(0, 6))

        # Approval status badge
        if is_approved:
            ctk.CTkLabel(
                inner, text=" APPROVED ", font=FONTS['badge'],
                fg_color=COLORS['success'], text_color=COLORS['bg_darkest'],
                corner_radius=12, height=22,
            ).pack(side='left', padx=(0, 4))
            approver = record.get('approved_by', '')
            if approver:
                ctk.CTkLabel(
                    inner, text=approver, font=FONTS['small'],
                    text_color=COLORS['text_secondary'],
                ).pack(side='left', padx=(0, 6))
        else:
            ctk.CTkLabel(
                inner, text=" PENDING ", font=FONTS['badge'],
                fg_color=COLORS['orange'], text_color=COLORS['bg_darkest'],
                corner_radius=12, height=22,
            ).pack(side='left', padx=(0, 6))

        # Determine Heat# vs Batch# from the stored mtr_data
        mtr = record.get('mtr_data', {})
        id_label, id_value = _get_identifier(mtr)
        if id_value == 'N/A':
            id_value = record.get('heat_number', 'N/A')

        ctk.CTkLabel(
            inner, text=f"{id_label}# {id_value}", font=FONTS['body'],
            text_color=COLORS['text_primary'],
        ).pack(side='left', padx=(0, 8))

        spec = record.get('spec_id', '')
        ctk.CTkLabel(
            inner, text=spec, font=FONTS['label'],
            text_color=COLORS['text_secondary'],
        ).pack(side='left', padx=(0, 8))

        # -- Right side: timestamp + action buttons --
        if is_approved:
            # View Report button for approved records
            ctk.CTkButton(
                inner, text="View Report", width=90, height=28,
                font=FONTS['label'],
                fg_color=COLORS['accent'], hover_color=COLORS['accent_hover'],
                text_color='#FFFFFF',
                command=lambda r=record: self._view_history_report(r),
            ).pack(side='right', padx=(4, 0))
        else:
            # Review button for pending records
            ctk.CTkButton(
                inner, text="Review", width=80, height=28,
                font=FONTS['label'],
                fg_color=COLORS['orange'], hover_color=COLORS['orange_hover'],
                text_color='#FFFFFF',
                command=lambda r=record: self._review_from_history(r),
            ).pack(side='right', padx=(4, 0))

        # Copy PO# button (if PO available)
        po_number = mtr.get('po_number', '') or ''
        if po_number:
            ctk.CTkButton(
                inner, text="Copy PO#", width=80, height=28,
                font=FONTS['label'],
                fg_color=COLORS['bg_dark'], hover_color=COLORS['surface_hl'],
                border_color=COLORS['border'], border_width=1,
                text_color=COLORS['text_primary'],
                command=lambda v=po_number: self._copy_identifier(v, "PO"),
            ).pack(side='right', padx=(4, 0))

        # Copy identifier button (Heat# or Batch#)
        ctk.CTkButton(
            inner, text=f"Copy {id_label}#", width=90, height=28,
            font=FONTS['label'],
            fg_color=COLORS['bg_dark'], hover_color=COLORS['surface_hl'],
            border_color=COLORS['border'], border_width=1,
            text_color=COLORS['text_primary'],
            command=lambda v=id_value, lbl=id_label: self._copy_identifier(v, lbl),
        ).pack(side='right', padx=(4, 0))

        # Delete button
        vid = record.get('validation_id', '')
        ctk.CTkButton(
            inner, text="Delete", width=60, height=28,
            font=FONTS['label'],
            fg_color=COLORS['bg_dark'], hover_color=COLORS['error'],
            border_color=COLORS['border'], border_width=1,
            text_color=COLORS['text_secondary'],
            command=lambda v=vid: self._delete_history_record(v),
        ).pack(side='right', padx=(4, 0))

        # Processing time
        proc_time = record.get('processing_time')
        if proc_time:
            ctk.CTkLabel(
                inner, text=self._format_elapsed(proc_time), font=FONTS['small'],
                text_color=COLORS['accent_light'],
            ).pack(side='right', padx=(0, 8))

        # Timestamp
        ts = record.get('timestamp', '')
        if ts:
            display_ts = ts[:19].replace('T', '  ')
        else:
            display_ts = ''
        ctk.CTkLabel(
            inner, text=display_ts, font=FONTS['small'],
            text_color=COLORS['text_secondary'],
        ).pack(side='right', padx=(0, 8))

    def _copy_identifier(self, value: str, label: str = "Heat"):
        """Copy heat/batch number to clipboard with visual feedback."""
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.root.update()  # Required for clipboard to persist
        self._set_status(f"Copied {label}#: {value}")

    def _view_history_report(self, record: dict):
        """Load a history record into the validate view as a full report."""
        # Switch to validate view
        self._navigate_to('validate')

        # Populate extracted data panel from stored mtr_data
        mtr_data = record.get('mtr_data', {})
        if ctk and mtr_data:
            self._display_extracted_data(mtr_data)
        elif mtr_data:
            self._clear_text(self.data_text)
            self._insert_text(self.data_text, json.dumps(mtr_data, indent=2))

        # Check for assembly data first
        assembly_data = record.get('assembly_data')
        if assembly_data and assembly_data.get('is_assembly'):
            from lib.assembly import AssemblyResult, AssemblyComponent
            assy = AssemblyResult(
                is_assembly=True,
                po_number=assembly_data.get('po_number', ''),
                customer_part_number=assembly_data.get('customer_part_number', ''),
                invoice_number=assembly_data.get('invoice_number', ''),
                vendor_name=assembly_data.get('vendor_name', ''),
                assembly_description=assembly_data.get('assembly_description', ''),
                overall_status=assembly_data.get('overall_status', 'UNKNOWN'),
                warnings=assembly_data.get('warnings', []),
                mtr_heats={int(k): v for k, v in assembly_data.get('mtr_heats', {}).items()},
            )
            for cd in assembly_data.get('components', []):
                assy.components.append(AssemblyComponent(
                    line_item=cd.get('line_item', ''),
                    qty=cd.get('qty', ''),
                    part_description=cd.get('part_description', ''),
                    part_number=cd.get('part_number', ''),
                    heat_number=cd.get('heat_number', ''),
                    status=cd.get('status', 'MISSING'),
                    found_on_pages=cd.get('found_on_pages', []),
                    manual_note=cd.get('manual_note', ''),
                ))
            self._display_assembly_data(assy)
            self._display_assembly_results(assy)
            self._assembly_result = assy

            overall = assy.overall_status
            self._update_header_status(overall, f"Assembly | PO {assy.po_number or 'N/A'}")
            self._set_status(f"Viewing history: Assembly PO {assy.po_number} ({overall})")
            return

        # Populate validation result panel from stored validation_details
        details = record.get('validation_details', {})
        if not details:
            self._clear_text(self.result_text)
            self._insert_text(self.result_text, "No validation details stored for this record.")
            return

        self._clear_text(self.result_text)
        tw = self.result_text._textbox if ctk else None

        if not tw:
            # Fallback: plain text
            self._insert_text(self.result_text, json.dumps(details, indent=2))
            return

        # Header info — use smart identifier
        mtr = record.get('mtr_data', {})
        id_label, id_value = _get_identifier(mtr)
        if id_value == 'N/A':
            id_value = details.get('heat_number', record.get('heat_number', 'N/A'))

        # Show source filename at top for traceability
        if record.get('source_file'):
            tw.insert('end', f"  File: ", 'label')
            tw.insert('end', f"{Path(record['source_file']).name}\n", 'value')
        tw.insert('end', f"  Spec: ", 'label')
        tw.insert('end', f"{details.get('spec_id', record.get('spec_id', 'N/A'))}\n", 'header')
        tw.insert('end', f"  {id_label}#: ", 'label')
        tw.insert('end', f"{id_value}\n", 'value')
        tw.insert('end', f"  Grade: ", 'label')
        tw.insert('end', f"{details.get('material_grade', record.get('material_grade', 'N/A'))}\n", 'value')
        tw.insert('end', f"  Overall: ", 'label')

        overall = details.get('overall_status', record.get('result', 'UNKNOWN'))
        tag = overall.lower() if overall.lower() in ('pass', 'fail', 'missing') else 'warn'
        tw.insert('end', f"{overall}\n", tag)

        # Summary from record
        summary = record.get('summary', {})
        if summary:
            tw.insert('end', f"\n  Summary: ", 'label')
            tw.insert('end', f"{summary.get('pass_count', 0)} pass", 'pass')
            tw.insert('end', f"  {summary.get('fail_count', 0)} fail", 'fail')
            tw.insert('end', f"  {summary.get('missing_count', 0)} missing\n", 'missing')

        # Chemistry
        chem = details.get('chemistry', [])
        if chem:
            tw.insert('end', "\n  Chemistry\n", 'header')
            tw.insert('end', f"  {'Element':<10}{'Min':>8}{'Max':>8}{'Actual':>10}  {'Status'}\n", 'label')
            tw.insert('end', "  " + "-" * 48 + "\n", 'label')
            for r in chem:
                smin = f"{r['spec_min']}" if r.get('spec_min') is not None else "-"
                smax = f"{r['spec_max']}" if r.get('spec_max') is not None else "-"
                actual = f"{r['actual_value']}" if r.get('actual_value') is not None else "-"
                tw.insert('end', f"  {r['property_name']:<10}{smin:>8}{smax:>8}{actual:>10}  ", 'value')
                st = r.get('status', 'UNKNOWN')
                stag = st.lower() if st.lower() in ('pass', 'fail', 'missing', 'skip') else 'warn'
                tw.insert('end', f"{st}\n", stag)
                if r.get('original_status'):
                    tw.insert('end', f"         ^^ OVERRIDDEN from {r['original_status']} by {r.get('override_by', '?')}: {r.get('override_reason', '')}\n", 'override')

        # Mechanical
        mech = details.get('mechanical', [])
        if mech:
            tw.insert('end', "\n  Mechanical Properties\n", 'header')
            tw.insert('end', f"  {'Property':<20}{'Min':>8}{'Max':>8}{'Actual':>10}  {'Status'}\n", 'label')
            tw.insert('end', "  " + "-" * 58 + "\n", 'label')
            for r in mech:
                smin = f"{r['spec_min']}" if r.get('spec_min') is not None else "-"
                smax = f"{r['spec_max']}" if r.get('spec_max') is not None else "-"
                actual = f"{r['actual_value']}" if r.get('actual_value') is not None else "-"
                tw.insert('end', f"  {r['property_name']:<20}{smin:>8}{smax:>8}{actual:>10}  ", 'value')
                st = r.get('status', 'UNKNOWN')
                stag = st.lower() if st.lower() in ('pass', 'fail', 'missing', 'skip') else 'warn'
                tw.insert('end', f"{st}\n", stag)
                if r.get('original_status'):
                    tw.insert('end', f"         ^^ OVERRIDDEN from {r['original_status']} by {r.get('override_by', '?')}: {r.get('override_reason', '')}\n", 'override')

        # Special
        special = details.get('special', [])
        if special:
            tw.insert('end', "\n  Special Requirements\n", 'header')
            for r in special:
                st = r.get('status', 'UNKNOWN')
                stag = st.lower() if st.lower() in ('pass', 'fail', 'missing', 'skip') else 'warn'
                tw.insert('end', f"  {ICONS['arrow']} {r['property_name']}: ", 'value')
                tw.insert('end', f"{st}", stag)
                if r.get('note'):
                    tw.insert('end', f"  ({r['note']})", 'label')
                tw.insert('end', "\n")
                if r.get('original_status'):
                    tw.insert('end', f"         ^^ OVERRIDDEN from {r['original_status']} by {r.get('override_by', '?')}: {r.get('override_reason', '')}\n", 'override')

        # Errors / Warnings
        for section, label_tag in [('errors', 'fail'), ('warnings', 'warn')]:
            items = details.get(section, [])
            if items:
                tw.insert('end', f"\n  {section.title()}\n", label_tag)
                for item in items:
                    tw.insert('end', f"    {item}\n", label_tag)

        # Metadata footer
        tw.insert('end', "\n  " + "-" * 48 + "\n", 'label')
        tw.insert('end', f"  Validated by: ", 'label')
        tw.insert('end', f"{record.get('validated_by', 'N/A')}\n", 'value')
        tw.insert('end', f"  Timestamp: ", 'label')
        ts = record.get('timestamp', '')
        tw.insert('end', f"{ts[:19].replace('T', ' ') if ts else 'N/A'}\n", 'value')
        if record.get('source_file'):
            tw.insert('end', f"  Source: ", 'label')
            tw.insert('end', f"{Path(record['source_file']).name}\n", 'value')

        # Update header with smart identifier
        self._update_header_status(overall, f"{id_label}# {id_value} | {record.get('spec_id', '')}")
        self._set_status(f"Viewing history: {id_label}# {id_value} ({overall})")

    def _review_from_history(self, record: dict):
        """Load a pending history record into the validate view for review/override/approval."""
        self.extracted_data = record.get('mtr_data', {})
        self.current_file = record.get('source_file')
        self._current_history_id = record.get('validation_id')
        self.staging_tiff_path = record.get('staging_tiff_path') or None

        # Switch to validate view
        self._navigate_to('validate')

        # Check for assembly record
        assembly_data = record.get('assembly_data')
        if assembly_data and assembly_data.get('is_assembly'):
            from lib.assembly import AssemblyResult, AssemblyComponent
            assy = AssemblyResult(
                is_assembly=True,
                po_number=assembly_data.get('po_number', ''),
                customer_part_number=assembly_data.get('customer_part_number', ''),
                invoice_number=assembly_data.get('invoice_number', ''),
                vendor_name=assembly_data.get('vendor_name', ''),
                assembly_description=assembly_data.get('assembly_description', ''),
                overall_status=assembly_data.get('overall_status', 'UNKNOWN'),
                warnings=assembly_data.get('warnings', []),
                mtr_heats={int(k): v for k, v in assembly_data.get('mtr_heats', {}).items()},
            )
            for cd in assembly_data.get('components', []):
                assy.components.append(AssemblyComponent(
                    line_item=cd.get('line_item', ''),
                    qty=cd.get('qty', ''),
                    part_description=cd.get('part_description', ''),
                    part_number=cd.get('part_number', ''),
                    heat_number=cd.get('heat_number', ''),
                    status=cd.get('status', 'MISSING'),
                    found_on_pages=cd.get('found_on_pages', []),
                    manual_note=cd.get('manual_note', ''),
                ))
            self._assembly_result = assy
            self._display_assembly_data(assy)
            self._display_assembly_results(assy)

            # Reconstruct a minimal CertValidation for approval flow
            self.validation_result = CertValidation(
                spec_id=f"Assembly: {assy.customer_part_number or 'N/A'}",
                heat_number=f"PO-{assy.po_number}" if assy.po_number else 'ASSEMBLY',
                material_grade=assy.assembly_description or 'Assembly',
                overall_status=assy.overall_status,
            )

            # Show assembly row with customer part field
            self._show_assembly_row(show_cust_part=True)
            if assy.customer_part_number:
                self.cust_part_var.set(assy.customer_part_number)
            if assy.po_number and not self.po_var.get().strip():
                self.po_var.set(assy.po_number)

            overall = assy.overall_status
            if ctk:
                filename = Path(self.current_file).name if self.current_file else 'History review'
                self.drop_zone.configure(
                    text=f"{ICONS['file']}  {filename}\n(reviewing from history)",
                    text_color=COLORS['text_primary'],
                )
                self.header_file_label.configure(text=filename, text_color=COLORS['text_primary'])
                self._update_header_status(overall, f"Assembly | PO {assy.po_number or 'N/A'}")
                self._set_button_state(self.approve_btn, 'normal')
                self._set_button_state(self.validate_btn, 'normal')
                self._set_button_state(self.override_btn, 'normal')
                if assy.missing_count > 0:
                    self.add_heat_btn.pack_forget()
                    self.add_heat_btn.pack(side='left', padx=4, before=self.approve_btn)
                    self._set_button_state(self.add_heat_btn, 'normal')
                if self.staging_tiff_path and Path(self.staging_tiff_path).exists():
                    self._set_button_state(self.preview_btn, 'normal')

            self._set_status(f"Reviewing: Assembly PO {assy.po_number} ({overall}) — Approve")
            return

        # Standard (non-assembly) record
        details = record.get('validation_details', {})
        if details:
            self.validation_result = CertValidation.from_dict(details)
        else:
            self.validation_result = None

        # Populate extracted data panel
        if ctk and self.extracted_data:
            self._display_extracted_data(self.extracted_data)

        # Populate validation result panel
        if self.validation_result and ctk:
            self._display_validation_results(self.validation_result)
        elif details:
            self._view_history_report(record)
            # Re-set the history id after _view_history_report
            self._current_history_id = record.get('validation_id')
            self.staging_tiff_path = record.get('staging_tiff_path') or None

        # Update header
        mtr = record.get('mtr_data', {})
        id_label, id_value = _get_identifier(mtr)
        if id_value == 'N/A':
            id_value = record.get('heat_number', 'N/A')
        overall = record.get('result', 'UNKNOWN')
        if ctk:
            filename = Path(self.current_file).name if self.current_file else 'History review'
            self.drop_zone.configure(
                text=f"{ICONS['file']}  {filename}\n(reviewing from history)",
                text_color=COLORS['text_primary'],
            )
            self.header_file_label.configure(text=filename, text_color=COLORS['text_primary'])
            self._update_header_status(overall, f"{id_label}# {id_value} | {record.get('spec_id', '')}")

        # Update spec dropdown
        spec_id = record.get('spec_id', '')
        if spec_id and hasattr(self, 'spec_var'):
            self.spec_var.set(spec_id)

        # Enable buttons
        if ctk:
            self._set_button_state(self.approve_btn, 'normal')
            if self.validation_result:
                self._set_button_state(self.override_btn, 'normal')
                self._set_button_state(self.validate_btn, 'normal')
            if self.staging_tiff_path and Path(self.staging_tiff_path).exists():
                self._set_button_state(self.preview_btn, 'normal')
            else:
                self._set_button_state(self.preview_btn, 'disabled')

        self._set_status(f"Reviewing: {id_label}# {id_value} ({overall}) — Override or Approve")

    # ============================================================= Settings View
    def _create_settings_view(self):
        """Wrap SettingsPanel as a sidebar nav view."""
        view = ctk.CTkFrame(self.content_area, fg_color=COLORS['bg_darkest'])
        self.content_frames['settings'] = view

        def on_settings_done(saved: bool):
            if saved:
                specs = ['Auto-detect', 'Vendor Spec'] + self._spec_display_list()
                self.spec_dropdown.configure(values=specs)

                # Restart watcher if the watch folder changed while watching
                if self.watcher.is_watching():
                    new_watch = self.config.get('watch_folder', '')
                    if new_watch and new_watch != self.watcher.watched_folder:
                        self._stop_watching()
                        self._start_watching(new_watch)
                    elif not new_watch:
                        self._stop_watching()

                self._set_status("Settings saved")
            self._navigate_to('validate')

        self.settings_panel = SettingsPanel(
            view, self.config, self.spec_loader, on_done=on_settings_done
        )
        self.settings_panel.show()

    # ============================================================= Display Methods
    def _display_extracted_data(self, data: dict):
        """Display extracted data with structured key/value formatting."""
        self._clear_text(self.data_text)
        tw = self.data_text._textbox

        # Show the right identifier label
        id_label, id_value = _get_identifier(data)
        header_fields = [
            (None, f'{id_label} Number', id_value),
            ('material_grade', 'Material Grade', None),
            ('specification', 'Specification', None),
            ('batch_number', 'Batch Number', None),
            ('po_number', 'PO Number', None),
            ('product_form', 'Product Form', None),
            ('condition', 'Condition', None),
            ('size', 'Size', None),
        ]
        for key, label, override in header_fields:
            val = override if override else data.get(key)
            if val:
                tw.insert('end', f"  {label}: ", 'label')
                tw.insert('end', f"{val}\n", 'value')

        chem = data.get('chemistry', {})
        if chem:
            tw.insert('end', "\n  Chemistry\n", 'key')
            tw.insert('end', "  " + "-" * 36 + "\n", 'label')
            for elem, val in sorted(chem.items()):
                tw.insert('end', f"    {elem:<6}", 'label')
                tw.insert('end', f"{val}\n", 'value')

        mech = data.get('mechanical_properties', {})
        if mech:
            tw.insert('end', "\n  Mechanical Properties\n", 'key')
            tw.insert('end', "  " + "-" * 36 + "\n", 'label')
            for prop, val in mech.items():
                tw.insert('end', f"    {prop:<24}", 'label')
                tw.insert('end', f"{val}\n", 'value')

        shown_keys = {'heat_number', 'batch_number', 'lot_number',
                      'material_grade', 'specification',
                      'po_number', 'product_form', 'condition', 'size',
                      'chemistry', 'mechanical_properties'}
        extra = {k: v for k, v in data.items() if k not in shown_keys and v}
        if extra:
            tw.insert('end', "\n  Other Fields\n", 'key')
            tw.insert('end', "  " + "-" * 36 + "\n", 'label')
            for k, v in extra.items():
                tw.insert('end', f"    {k}: ", 'label')
                if isinstance(v, (dict, list)):
                    tw.insert('end', f"{json.dumps(v, indent=4)}\n", 'value')
                else:
                    tw.insert('end', f"{v}\n", 'value')

    def _display_validation_results(self, result):
        """Display validation results with colored PASS/FAIL/MISSING per element."""
        self._clear_text(self.result_text)
        tw = self.result_text._textbox

        # Determine Heat# vs Batch# from extracted data context
        id_label, id_value = _get_identifier(self.extracted_data or {})
        # Prefer the value from the validation result if available
        if result.heat_number and result.heat_number != 'N/A':
            id_value = result.heat_number

        # Show source filename at top for traceability
        if self.current_file:
            tw.insert('end', f"  File: ", 'label')
            tw.insert('end', f"{Path(self.current_file).name}\n", 'value')
        tw.insert('end', f"  Spec: ", 'label')
        tw.insert('end', f"{result.spec_id}\n", 'header')
        tw.insert('end', f"  {id_label}#: ", 'label')
        tw.insert('end', f"{id_value}\n", 'value')
        tw.insert('end', f"  Grade: ", 'label')
        tw.insert('end', f"{result.material_grade}\n", 'value')
        tw.insert('end', f"  Overall: ", 'label')

        overall_tag = result.overall_status.lower()
        if overall_tag not in ('pass', 'fail', 'missing'):
            overall_tag = 'warn'
        tw.insert('end', f"{result.overall_status}\n", overall_tag)

        tw.insert('end', f"\n  Summary: ", 'label')
        tw.insert('end', f"{result.pass_count} pass", 'pass')
        tw.insert('end', f"  {result.fail_count} fail", 'fail')
        tw.insert('end', f"  {result.missing_count} missing\n", 'missing')

        if result.chemistry_results:
            tw.insert('end', "\n  Chemistry\n", 'header')
            tw.insert('end', f"  {'Element':<10}{'Min':>10}{'Max':>10}{'Actual':>10}  {'Status'}\n", 'label')
            tw.insert('end', "  " + "-" * 52 + "\n", 'label')
            for r in result.chemistry_results:
                smin = f"{r.spec_min:.4f}" if r.spec_min is not None else "-"
                smax = f"{r.spec_max:.4f}" if r.spec_max is not None else "-"
                actual = f"{r.actual_value:.4f}" if r.actual_value is not None else "-"
                tw.insert('end', f"  {r.property_name:<10}{smin:>10}{smax:>10}{actual:>10}  ", 'value')
                tag = r.status.lower() if r.status.lower() in ('pass', 'fail', 'missing', 'skip') else 'warn'
                tw.insert('end', f"{r.status}\n", tag)
                if r.is_overridden:
                    tw.insert('end', f"         ^^ OVERRIDDEN from {r.original_status} by {r.override_by}: {r.override_reason}\n", 'override')

        if result.mechanical_results:
            tw.insert('end', "\n  Mechanical Properties\n", 'header')
            tw.insert('end', f"  {'Property':<25}{'Min':>8}{'Max':>8}{'Actual':>10}  {'Status'}\n", 'label')
            tw.insert('end', "  " + "-" * 63 + "\n", 'label')
            for r in result.mechanical_results:
                smin = f"{r.spec_min:.1f}" if r.spec_min is not None else "-"
                smax = f"{r.spec_max:.1f}" if r.spec_max is not None else "-"
                actual = f"{r.actual_value:.1f}" if r.actual_value is not None else "-"
                tw.insert('end', f"  {r.property_name:<25}{smin:>8}{smax:>8}{actual:>10}  ", 'value')
                tag = r.status.lower() if r.status.lower() in ('pass', 'fail', 'missing', 'skip') else 'warn'
                tw.insert('end', f"{r.status}\n", tag)
                if r.is_overridden:
                    tw.insert('end', f"         ^^ OVERRIDDEN from {r.original_status} by {r.override_by}: {r.override_reason}\n", 'override')

        if result.special_results:
            tw.insert('end', "\n  Special Requirements\n", 'header')
            for r in result.special_results:
                tag = r.status.lower() if r.status.lower() in ('pass', 'fail', 'missing', 'skip') else 'warn'
                tw.insert('end', f"  {ICONS['arrow']} {r.property_name}: ", 'value')
                tw.insert('end', f"{r.status}", tag)
                if r.note:
                    tw.insert('end', f"  ({r.note})", 'label')
                tw.insert('end', "\n")
                if r.is_overridden:
                    tw.insert('end', f"         ^^ OVERRIDDEN from {r.original_status} by {r.override_by}: {r.override_reason}\n", 'override')

        if result.errors:
            tw.insert('end', "\n  Errors\n", 'fail')
            for err in result.errors:
                tw.insert('end', f"    {err}\n", 'fail')

        if result.warnings:
            tw.insert('end', "\n  Warnings\n", 'warn')
            for w in result.warnings:
                tw.insert('end', f"    {w}\n", 'warn')

    def _display_assembly_data(self, assy):
        """Display assembly COC data in the Extracted Data card."""
        self._clear_text(self.data_text)
        tw = self.data_text._textbox

        tw.insert('end', "  ASSEMBLY PACKET\n\n", 'header')
        tw.insert('end', f"  Vendor: ", 'label')
        tw.insert('end', f"{assy.vendor_name}\n", 'value')
        tw.insert('end', f"  PO Number: ", 'label')
        tw.insert('end', f"{assy.po_number}\n", 'value')
        tw.insert('end', f"  Customer Part#: ", 'label')
        tw.insert('end', f"{assy.customer_part_number}\n", 'value')
        tw.insert('end', f"  Invoice: ", 'label')
        tw.insert('end', f"{assy.invoice_number}\n", 'value')
        tw.insert('end', f"  Description: ", 'label')
        tw.insert('end', f"{assy.assembly_description}\n", 'value')
        tw.insert('end', f"\n  Components: {len(assy.components)}\n", 'header')
        tw.insert('end', f"  Unique Heats on MTR pages: {len(assy.mtr_heats)}\n\n", 'label')

        # Component table
        tw.insert('end', f"  {'#':<4}{'Part Number':<20}{'Heat':<16}{'Description'}\n", 'label')
        tw.insert('end', "  " + "-" * 70 + "\n", 'label')
        for i, c in enumerate(assy.components, 1):
            tw.insert('end', f"  {i:<4}{c.part_number:<20}{c.heat_number:<16}{c.part_description}\n", 'value')

    def _display_assembly_results(self, assy):
        """Display assembly traceability results in the Validation Result card."""
        self._clear_text(self.result_text)
        tw = self.result_text._textbox

        tw.insert('end', "  HEAT TRACEABILITY\n\n", 'header')
        tw.insert('end', f"  Overall: ", 'label')
        tag = 'pass' if assy.overall_status == 'PASS' else 'warn'
        tw.insert('end', f"{assy.overall_status}\n", tag)

        tw.insert('end', f"\n  Found: ", 'label')
        tw.insert('end', f"{assy.found_count}", 'pass')
        tw.insert('end', f"  Missing: ", 'label')
        tw.insert('end', f"{assy.missing_count}", 'fail' if assy.missing_count else 'pass')
        tw.insert('end', f"  Manual: ", 'label')
        tw.insert('end', f"{assy.manual_count}\n", 'warn' if assy.manual_count else 'value')

        # Traceability matrix
        tw.insert('end', f"\n  {'Part Number':<20}{'Heat':<16}{'Pages':<12}{'Status'}\n", 'label')
        tw.insert('end', "  " + "-" * 60 + "\n", 'label')

        for c in assy.components:
            tw.insert('end', f"  {c.part_number:<20}{c.heat_number:<16}", 'value')
            if c.found_on_pages:
                pages_str = ','.join(str(p) for p in c.found_on_pages)
            else:
                pages_str = '-'
            tw.insert('end', f"{pages_str:<12}", 'value')

            if c.status == 'FOUND':
                tw.insert('end', "FOUND\n", 'pass')
            elif c.status == 'MANUAL':
                tw.insert('end', f"MANUAL\n", 'warn')
                if c.manual_note:
                    tw.insert('end', f"    Note: {c.manual_note}\n", 'label')
            else:
                tw.insert('end', "MISSING\n", 'fail')

        # MTR heat map
        tw.insert('end', "\n  MTR Pages Heat Map\n", 'header')
        tw.insert('end', f"  {'Page':<8}{'Heat Number'}\n", 'label')
        tw.insert('end', "  " + "-" * 30 + "\n", 'label')
        for page in sorted(assy.mtr_heats.keys()):
            tw.insert('end', f"  {page:<8}{assy.mtr_heats[page]}\n", 'value')

        if assy.warnings:
            tw.insert('end', "\n  Warnings\n", 'warn')
            for w in assy.warnings:
                tw.insert('end', f"    {w}\n", 'warn')

        # Add "Mark as Verified" button hint for missing heats
        if assy.missing_count > 0:
            tw.insert('end', "\n  Use 'Add Missing Heat' button to manually verify missing heats.\n", 'label')

    def _show_assembly_row(self, show_cust_part: bool = False):
        """Show the assembly controls row below the main controls."""
        if not ctk or not hasattr(self, 'assembly_row'):
            return
        self.assembly_row.pack_forget()
        self.assembly_row.pack(fill='x', padx=4, pady=(2, 0),
                               before=self.cards_frame)
        if show_cust_part:
            self.cust_part_label.pack(side='left', padx=(16, 6))
            self.cust_part_entry.pack(side='left')
        else:
            self.cust_part_label.pack_forget()
            self.cust_part_entry.pack_forget()

    def _hide_assembly_row(self):
        """Hide the assembly controls row."""
        if ctk and hasattr(self, 'assembly_row'):
            self.assembly_row.pack_forget()

    def _on_assembly_mode_change(self, value):
        """Handle assembly mode dropdown change."""
        if value == 'Assembly':
            self.cust_part_label.pack(side='left', padx=(16, 6))
            self.cust_part_entry.pack(side='left')
        elif value == 'Single Part':
            self.cust_part_label.pack_forget()
            self.cust_part_entry.pack_forget()
        # 'Auto' — leave as-is (will be shown/hidden by pipeline result)

    def _add_missing_heat(self):
        """Dialog to manually mark a missing heat as verified."""
        if not self._assembly_result:
            return

        missing = [c for c in self._assembly_result.components if c.status == 'MISSING']
        if not missing:
            messagebox.showinfo("No Missing Heats", "All heats are accounted for.")
            return

        # Show dialog with missing components
        missing_list = "\n".join(
            f"  {c.part_number} — Heat: {c.heat_number} ({c.part_description})"
            for c in missing
        )

        if ctk:
            dialog = ctk.CTkInputDialog(
                text=f"Missing heats:\n{missing_list}\n\nEnter part number to mark as verified:",
                title="Add Missing Heat",
            )
            part_num = dialog.get_input()
        else:
            from tkinter import simpledialog
            part_num = simpledialog.askstring(
                "Add Missing Heat",
                f"Missing heats:\n{missing_list}\n\nEnter part number to mark as verified:",
            )

        if not part_num:
            return

        from lib.assembly import mark_heat_manual
        note = "Manually verified by operator"
        self._assembly_result = mark_heat_manual(self._assembly_result, part_num.strip(), note)

        # Refresh display
        self._display_assembly_results(self._assembly_result)

        # Update status
        if self._assembly_result.overall_status == 'PASS':
            self._set_status("All heats now accounted for (including manual)")
            if ctk:
                self._update_header_status('PASS', "Assembly — all heats verified")

    # ============================================================= File I/O
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
        # Don't delete staging TIFF — it's now tracked in history for pending records
        self.staging_tiff_path = None
        self._current_history_id = None

        self.current_file = file_path
        self.extracted_data = None
        self.validation_result = None
        self.pipeline_result = None

        filename = Path(file_path).name
        if ctk:
            self.drop_zone.configure(
                text=f"{ICONS['file']}  {filename}\n(click to change)",
                text_color=COLORS['text_primary'],
            )
            self.header_file_label.configure(text=filename, text_color=COLORS['text_primary'])
            self._update_header_status('Ready', filename)
            self.extract_btn.configure(state='normal')
            self.validate_btn.configure(state='disabled')
            self.override_btn.configure(state='disabled')
            self.preview_btn.configure(state='disabled')
            self.approve_btn.configure(state='disabled')
        else:
            self.file_label.configure(text=filename)
            self.extract_btn.configure(state='normal')

        self.config.set('last_input_folder', str(Path(file_path).parent))
        self._set_status(f"Loaded: {filename}")
        self._clear_text(self.data_text)
        self._clear_text(self.result_text)

    # ============================================================= Pipeline
    def _extract(self):
        """Run the full OCR + Claude extraction pipeline."""
        if not self.current_file:
            return

        if not self.config.is_configured():
            messagebox.showwarning(
                "Setup Required",
                "Please configure Anthropic API key and archive folder in Settings first."
            )
            self._navigate_to('settings')
            return

        self._set_status("Running pipeline... (OCR + Claude parsing)")
        self._set_button_state(self.extract_btn, 'disabled')
        self._set_progress(0)
        if ctk:
            self._update_header_status('INCOMPLETE', "Processing...")

        spec_id = self._resolve_spec_id(self.spec_var.get())
        if spec_id in ('Auto-detect', '---'):
            spec_id = None

        def do_pipeline():
            self._lower_process_priority()
            try:
                def on_progress(step, pct):
                    self.root.after(0, lambda: self._set_progress(pct))
                    self.root.after(0, lambda: self._set_status(f"Pipeline: {step}"))

                # Always generate staging TIFF when archive folder is configured
                output_dir = self.config.effective_output_folder

                # PO from sticky field
                po_from_field = ''
                if hasattr(self, 'po_var'):
                    po_from_field = self.po_var.get().strip()

                # Assembly mode
                assembly_mode = self.assembly_var.get() if hasattr(self, 'assembly_var') else 'Auto'
                force_assembly = None
                if assembly_mode == 'Assembly':
                    force_assembly = True
                elif assembly_mode == 'Single Part':
                    force_assembly = False

                t0 = time.time()
                result = process_document(
                    pdf_path=self.current_file,
                    output_dir=output_dir,
                    spec_id=spec_id,
                    anthropic_api_key=self.config.anthropic_api_key,
                    paddle_model_path=self.config.get('paddle_model_path', '') or None,
                    preprocessing_dpi=self.config.get('preprocessing_dpi', 300),
                    tiff_dpi=self.config.get('tiff_dpi', 300),
                    tiff_compression=self.config.get('tiff_compression', 'lzw'),
                    on_progress=on_progress,
                    po_number=po_from_field or None,
                    organize_by_po=self.config.get('organize_by_po', False),
                    extraction_model=self.config.get('extraction_model', 'sonnet'),
                    use_gpu_ocr=self.config.get('use_gpu_ocr', True),
                    force_assembly=force_assembly,
                )
                elapsed = time.time() - t0

                self.root.after(0, lambda: self._on_pipeline_complete(result, elapsed))

            except Exception as e:
                self.root.after(0, lambda: self._on_extract_error(str(e)))
            finally:
                self._restore_process_priority()

        threading.Thread(target=do_pipeline, daemon=True).start()

    # ============================================================= Batch
    def _batch_files(self):
        """Open multi-file picker and start batch processing."""
        if self._batch_running:
            messagebox.showinfo("Batch Running", "A batch is already in progress.")
            return
        file_paths = filedialog.askopenfilenames(
            title="Select MTR Files for Batch Processing",
            filetypes=[
                ("PDF files", "*.pdf"),
                ("Images", "*.png *.jpg *.jpeg *.tiff *.tif"),
                ("All files", "*.*"),
            ],
            initialdir=self.config.get('last_input_folder', ''),
        )
        if file_paths:
            self.config.set('last_input_folder', str(Path(file_paths[0]).parent))
            self._start_batch(list(file_paths))

    def _batch_folder(self):
        """Open folder picker and start batch processing all supported files."""
        if self._batch_running:
            messagebox.showinfo("Batch Running", "A batch is already in progress.")
            return
        folder = filedialog.askdirectory(
            title="Select Folder for Batch Processing",
            initialdir=self.config.get('last_input_folder', ''),
        )
        if not folder:
            return
        self.config.set('last_input_folder', folder)
        supported = {'.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.tif'}
        files = sorted(
            str(p) for p in Path(folder).iterdir()
            if p.is_file() and p.suffix.lower() in supported
        )
        if not files:
            messagebox.showinfo("No Files", "No supported files found in the selected folder.")
            return
        self._start_batch(files)

    def _start_batch(self, file_paths: list):
        """Process a list of files sequentially, queuing results for approval."""
        if not self.config.is_configured():
            messagebox.showwarning(
                "Setup Required",
                "Please configure Anthropic API key and archive folder in Settings first.",
            )
            self._navigate_to('settings')
            return

        total = len(file_paths)
        spec_id = self._resolve_spec_id(self.spec_var.get())
        if spec_id in ('Auto-detect', '---'):
            spec_id = None

        po_from_field = ''
        if hasattr(self, 'po_var'):
            po_from_field = self.po_var.get().strip()

        # Disable buttons during processing
        self._batch_running = True
        self._set_button_state(self.batch_files_btn, 'disabled')
        self._set_button_state(self.batch_folder_btn, 'disabled')
        self._set_button_state(self.extract_btn, 'disabled')

        first_result_shown = False

        def do_batch():
            nonlocal first_result_shown
            self._lower_process_priority()
            from concurrent.futures import ThreadPoolExecutor

            api_key = self.config.anthropic_api_key
            paddle_path = self.config.get('paddle_model_path', '') or None
            dpi = self.config.get('preprocessing_dpi', 300)
            gpu_ocr = self.config.get('use_gpu_ocr', True)

            executor = ThreadPoolExecutor(max_workers=1)
            next_pre = None  # Future for next file's Phase A

            for idx, fpath in enumerate(file_paths, 1):
                # Update batch progress on UI thread
                self.root.after(0, lambda i=idx, t=total, f=fpath: (
                    self.batch_status_label.configure(
                        text=f"Batch: {i}/{t} \u2014 {Path(f).name}"
                    ),
                    self._set_status(f"Batch: processing {i}/{t} \u2014 {Path(f).name}"),
                    self._set_progress(0),
                ))

                try:
                    def on_progress(step, pct):
                        self.root.after(0, lambda: self._set_progress(pct))

                    # Wait for this file's pre-extraction (or run inline for first)
                    if next_pre is not None:
                        pre_result = next_pre.result()
                    else:
                        pre_result = pre_extract(
                            fpath, api_key=api_key,
                            paddle_model_path=paddle_path,
                            preprocessing_dpi=dpi,
                            use_gpu=gpu_ocr,
                        )

                    # Kick off Phase A for NEXT file while we do Phase B
                    if idx < total:
                        next_fpath = file_paths[idx]
                        next_pre = executor.submit(
                            pre_extract, next_fpath,
                            api_key=api_key,
                            paddle_model_path=paddle_path,
                            preprocessing_dpi=dpi,
                            use_gpu=gpu_ocr,
                        )

                    t0 = time.time()
                    # Assembly mode from dropdown
                    asm = self.assembly_var.get() if hasattr(self, 'assembly_var') else 'Auto'
                    fa = True if asm == 'Assembly' else (False if asm == 'Single Part' else None)

                    result = process_document(
                        pdf_path=fpath,
                        output_dir=self.config.effective_output_folder,
                        spec_id=spec_id,
                        anthropic_api_key=api_key,
                        paddle_model_path=paddle_path,
                        preprocessing_dpi=dpi,
                        tiff_dpi=self.config.get('tiff_dpi', 300),
                        tiff_compression=self.config.get('tiff_compression', 'lzw'),
                        on_progress=on_progress,
                        po_number=po_from_field or None,
                        organize_by_po=self.config.get('organize_by_po', False),
                        extraction_model=self.config.get('extraction_model', 'sonnet'),
                        pre_extracted=pre_result,
                        use_gpu_ocr=gpu_ocr,
                        force_assembly=fa,
                    )
                    batch_elapsed = time.time() - t0

                    # Store source file on result for _load_queued_result
                    result.source_file = fpath

                    def handle_result(r=result, fp=fpath, is_first=not first_result_shown, el=batch_elapsed):
                        if is_first:
                            # Display first result directly
                            self.current_file = fp
                            filename = Path(fp).name
                            self.drop_zone.configure(
                                text=f"{ICONS['file']}  {filename}\n(click to change)",
                                text_color=COLORS['text_primary'],
                            )
                            self.header_file_label.configure(
                                text=filename, text_color=COLORS['text_primary'],
                            )
                            self._on_pipeline_complete(r, el)
                        else:
                            # Queue subsequent results
                            if r.validation:
                                ed = r.normalized_data or r.extracted_data
                                spec = self.spec_loader.get(r.spec_id) if r.spec_id else {}
                                vid = self.history.record(
                                    r.validation, ed, spec, fp,
                                    staging_tiff_path=r.output_tiff_path,
                                )
                                if el > 0:
                                    self.history.update(vid, processing_time=round(el, 1))
                            self._approval_queue.append(r)
                            self._update_queue_indicator()

                    self.root.after(0, handle_result)
                    first_result_shown = True

                except Exception as e:
                    logger.exception("Batch error for %s: %s", fpath, e)
                    try:
                        self.history.record_error(
                            source_file=fpath,
                            error_type="BATCH_PIPELINE_FAILED",
                            error_message=str(e),
                        )
                    except Exception:
                        pass

            executor.shutdown(wait=False)
            self._restore_process_priority()

            # Batch complete — re-enable buttons
            def on_batch_done():
                self._batch_running = False
                self._set_button_state(self.batch_files_btn, 'normal')
                self._set_button_state(self.batch_folder_btn, 'normal')
                self._set_button_state(self.extract_btn, 'normal')
                self.batch_status_label.configure(
                    text=f"Batch complete: {total} files processed"
                )
                self._set_status(
                    f"Batch complete: {total} files. "
                    f"Queue: {len(self._approval_queue)} pending review."
                )

            self.root.after(0, on_batch_done)

        threading.Thread(target=do_batch, daemon=True).start()

    def _on_pipeline_complete(self, result: PipelineResult, elapsed: float = 0.0):
        """Handle pipeline completion — display results for review (no archiving yet)."""
        self._processing_time_sec = elapsed
        self.pipeline_result = result
        self.extracted_data = result.normalized_data or result.extracted_data
        self.validation_result = result.validation
        self._assembly_result = result.assembly_result

        # Store staging TIFF path for preview/approve
        self.staging_tiff_path = result.output_tiff_path

        self._set_progress(1.0)

        if result.errors:
            self._set_status(f"Pipeline errors: {'; '.join(result.errors)}")
            self._set_button_state(self.extract_btn, 'normal')
            self._clear_text(self.data_text)
            self._insert_text(self.data_text, "\n".join(result.errors))
            if ctk:
                self._update_header_status('ERROR')
            return

        # --- Assembly result display ---
        if result.assembly_result and result.assembly_result.is_assembly:
            assy = result.assembly_result
            if ctk:
                self._display_assembly_data(assy)
                self._display_assembly_results(assy)
                # Show assembly row with customer part number field
                self._show_assembly_row(show_cust_part=True)
                if assy.customer_part_number and not self.cust_part_var.get().strip():
                    self.cust_part_var.set(assy.customer_part_number)
                if assy.po_number and not self.po_var.get().strip():
                    self.po_var.set(assy.po_number)

            time_str = self._format_elapsed(elapsed)
            status = assy.overall_status
            self._set_status(
                f"Assembly {status} — PO {assy.po_number or 'N/A'} — "
                f"{assy.found_count}/{len(assy.components)} heats matched — {time_str}"
            )
            if ctk:
                self._update_header_status(
                    status,
                    f"Assembly | PO {assy.po_number or 'N/A'} | {time_str}"
                )

            self._set_button_state(self.extract_btn, 'normal')
            self._set_button_state(self.validate_btn, 'normal')
            self._set_button_state(self.override_btn, 'normal')
            if self.staging_tiff_path and Path(self.staging_tiff_path).exists():
                self._set_button_state(self.preview_btn, 'normal')
            self._set_button_state(self.approve_btn, 'normal')
            # Show/hide "Add Missing Heat" button (pack before approve for visibility)
            if assy.missing_count > 0:
                # Ensure it's visible — remove first then re-add in the right spot
                self.add_heat_btn.pack_forget()
                self.add_heat_btn.pack(side='left', padx=4, before=self.approve_btn)
                self._set_button_state(self.add_heat_btn, 'normal')
            else:
                self.add_heat_btn.pack_forget()

            # Record assembly to history using a minimal CertValidation
            try:
                assy_validation = CertValidation(
                    spec_id=f"Assembly: {assy.customer_part_number or 'N/A'}",
                    heat_number=f"PO-{assy.po_number}" if assy.po_number else 'ASSEMBLY',
                    material_grade=assy.assembly_description or 'Assembly',
                    overall_status=assy.overall_status,
                )
                assy_spec = {'material': assy.assembly_description or 'Assembly'}
                vid = self.history.record(
                    assy_validation,
                    self.extracted_data,
                    assy_spec,
                    self.current_file,
                    staging_tiff_path=self.staging_tiff_path,
                )
                self._current_history_id = vid
                if elapsed > 0:
                    self.history.update(vid, processing_time=round(elapsed, 1))
                # Store the full assembly result in the validation record
                self.history.update(vid, assembly_data=assy.to_dict())
                self.validation_result = assy_validation
            except Exception as e:
                logger.warning("Could not record assembly to history: %s", e)

            self._update_queue_indicator()
            return

        # Hide assembly-specific controls for non-assembly
        if ctk and hasattr(self, 'add_heat_btn'):
            self.add_heat_btn.pack_forget()
        self._hide_assembly_row()

        if ctk:
            self._display_extracted_data(self.extracted_data)
        else:
            self._clear_text(self.data_text)
            self._insert_text(self.data_text, json.dumps(self.extracted_data, indent=2))

        # Determine identifier label (Heat# vs Batch#)
        id_label, id_value = _get_identifier(self.extracted_data)

        # Auto-populate PO field from extracted data (don't overwrite manual entry)
        if ctk and hasattr(self, 'po_var'):
            extracted_po = self.extracted_data.get('po_number', '')
            if extracted_po and not self.po_var.get().strip():
                self.po_var.set(extracted_po)

        if result.validation:
            if ctk:
                self._display_validation_results(result.validation)
            else:
                self._clear_text(self.result_text)
                self._insert_text(self.result_text, format_validation_report(result.validation, use_color=False))

            status = result.validation.overall_status
            if result.validation.heat_number and result.validation.heat_number != 'N/A':
                id_value = result.validation.heat_number
            time_str = self._format_elapsed(elapsed)
            self._set_status(f"{status} - {id_label}# {id_value} (Spec: {result.spec_id}) — {time_str} — Review & Approve")
            if ctk:
                self._update_header_status(status, f"{id_label}# {id_value} | {result.spec_id} | {time_str}")
        else:
            if result.sanity and any(result.sanity.values()):
                self._insert_text(self.result_text, format_sanity_report(result.sanity))
            time_str = self._format_elapsed(elapsed)
            self._set_status(f"Extracted: {id_label}# {id_value} — {time_str} — Review & Approve")
            if ctk:
                self._update_header_status('INCOMPLETE', f"{id_label}# {id_value}")

        if result.compliance_flags:
            tw = self.result_text._textbox if ctk else None
            if tw:
                tw.insert('end', "\n  Compliance Flags (Claude)\n", 'header')
                for flag in result.compliance_flags:
                    field = flag.get('field', '?')
                    value = flag.get('value', '?')
                    fstatus = flag.get('status', '?')
                    tag = fstatus.lower() if fstatus.lower() in ('pass', 'fail') else 'warn'
                    tw.insert('end', f"    {field}: {value} ", 'value')
                    tw.insert('end', f"({fstatus})\n", tag)
            else:
                flags_text = "\n\nCompliance Flags (from Claude):\n"
                for flag in result.compliance_flags:
                    flags_text += f"  - {flag.get('field', '?')}: {flag.get('value', '?')} ({flag.get('status', '?')})\n"
                self._insert_text(self.result_text, flags_text)

        self._set_button_state(self.extract_btn, 'normal')

        # Enable Re-Validate when we have extracted data
        if self.extracted_data:
            self._set_button_state(self.validate_btn, 'normal')

        # Re-rank spec dropdown based on extracted data
        if self.extracted_data and hasattr(self, 'spec_dropdown'):
            self._rerank_spec_dropdown(self.extracted_data, result.spec_id)
        elif result.spec_id and hasattr(self, 'spec_var'):
            self.spec_var.set(result.spec_id)

        # Record to history immediately as PENDING
        if result.validation:
            spec_id = result.spec_id
            spec = self.spec_loader.get(spec_id) if spec_id else {}
            vid = self.history.record(
                result.validation, self.extracted_data, spec,
                self.current_file,
                staging_tiff_path=self.staging_tiff_path,
            )
            self._current_history_id = vid
            # Store processing time in history
            if elapsed > 0:
                self.history.update(vid, processing_time=round(elapsed, 1))

        # Enable approve/preview/override buttons for the approval gate
        if ctk:
            if self.staging_tiff_path and Path(self.staging_tiff_path).exists():
                self._set_button_state(self.preview_btn, 'normal')
            self._set_button_state(self.approve_btn, 'normal')
            if self.validation_result:
                self._set_button_state(self.override_btn, 'normal')
        self._update_queue_indicator()

    def _on_extract_error(self, error: str):
        """Handle extraction error."""
        self._set_status(f"Error: {error}")
        self._set_button_state(self.extract_btn, 'normal')
        self._set_progress(0)
        if ctk:
            self._update_header_status('ERROR')

        # Record the error in history so every file has an audit trail
        try:
            self.history.record_error(
                source_file=getattr(self, 'current_file', None),
                error_type="PIPELINE_FAILED",
                error_message=error,
            )
        except Exception:
            logger.debug("Could not record error to history", exc_info=True)

        messagebox.showerror("Pipeline Failed", error)

    def _rerank_spec_dropdown(self, mtr_data: dict, selected_spec_id: Optional[str] = None):
        """Re-rank the spec dropdown based on extracted MTR data.

        Shows top matching specs with confidence at the top, then Vendor Spec,
        then all remaining specs alphabetically.
        """
        matches = self.matcher.find_matching_specs(mtr_data)
        matched_ids = {m[0] for m in matches}
        all_ids = self.spec_loader.list_ids()

        # Build ranked list: top matches with confidence, then divider, then rest
        ranked = ['Auto-detect']
        for spec_id, confidence, reason in matches[:5]:  # Top 5 matches
            spec = self.spec_loader.get(spec_id)
            material = spec.get('material', '') if spec else ''
            material = self._abbreviate_material(material, max_len=20)
            ranked.append(f"{spec_id}, {material} ({confidence:.0%})")

        ranked.append('---')  # Visual separator
        ranked.append('Vendor Spec')

        # Add remaining specs (not in top matches) with material description
        for sid in all_ids:
            if sid not in matched_ids:
                spec = self.spec_loader.get(sid)
                material = spec.get('material', '') if spec else ''
                if material:
                    material = self._abbreviate_material(material)
                    ranked.append(f"{sid}, {material}")
                else:
                    ranked.append(sid)

        self.spec_dropdown.configure(values=ranked)

        # Set the selected spec
        if selected_spec_id:
            # Find the display string for the selected spec
            for item in ranked:
                if item.startswith(selected_spec_id):
                    self.spec_var.set(item)
                    return
            self.spec_var.set(selected_spec_id)

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        """Format elapsed seconds as a human-readable string."""
        if seconds < 60:
            return f"{seconds:.1f}s"
        m, s = divmod(seconds, 60)
        return f"{int(m)}m {s:.0f}s"

    @staticmethod
    def _abbreviate_material(name: str, max_len: int = 26) -> str:
        """Shorten a material name to fit the spec dropdown."""
        # Common abbreviations (order matters — longest/most-specific first)
        abbrevs = [
            ('Drawn Over Mandrel (DOM)', 'DOM'),
            ('Nickel-Cobalt-Chromium-Molybdenum', 'NiCoCrMo'),
            ('Cobalt-Chromium-Nickel-Molybdenum', 'CoCrNiMo'),
            ('Copper Nickel-Tin Bronze Alloy', 'CuNiSn'),
            ('Nitriding #3 (135 Modified)', 'Nitride #3'),
            ('Chromium Molybdenum Low Alloy Steel', 'CrMo LAS'),
            ('Chromium Molybdenum', 'CrMo'),
            ('Low Alloy Steel', 'LAS'),
            ('Alloy Steel', 'AS'),
            ('Stainless Steel', 'SS'),
            ('Carbon Steel', 'CS'),
            ('Tool Steel', 'TS'),
            ('Polyetheretherketone', 'PEEK'),
            ('Polytetrafluoroethylene', 'PTFE'),
            ('Martensitic', 'Mart.'),
            ('Durometer Molded', 'Duro Mld'),
            ('Durometer', 'Duro'),
            ('High Carbon', 'Hi-C'),
            ('Low Carbon', 'Lo-C'),
            ('Aluminum', 'Al'),
            ('Reconstituted', 'Recon.'),
            ('Re-Processed', 'Reproc.'),
            ('Extruded Nylon', 'Ext. Nylon'),
            ('Double Aged', 'DA'),
            ('Annealed', 'Ann.'),
            ('Spring Wire', 'Sprg Wire'),
            ('Spring Alloy', 'Spring'),
            ('Half Hard', 'HH'),
            ('Nickel Chrome', 'NiCr'),
            ('Tungsten Carbide Balls', 'WC Balls'),
            ('Plastic Bushing', 'Bushing'),
            ('Set Screws', 'Screws'),
            ('Chromium Alloy Steel', 'Cr AS'),
            ('Chromium', 'Cr'),
            (' Modified ', ' Mod. '),
        ]
        s = name
        for long, short in abbrevs:
            s = s.replace(long, short)
        if len(s) > max_len:
            s = s[:max_len - 3].rstrip() + '...'
        return s

    def _spec_display_list(self) -> list:
        """Build spec dropdown items with material descriptions."""
        result = []
        for sid in self.spec_loader.list_ids():
            spec = self.spec_loader.get(sid)
            material = spec.get('material', '') if spec else ''
            if material:
                material = self._abbreviate_material(material)
                result.append(f"{sid}, {material}")
            else:
                result.append(sid)
        return result

    def _resolve_spec_id(self, display_value: str) -> str:
        """Extract the spec ID from a dropdown display value.

        Handles plain IDs ('ES-M0009B'), comma-separated display strings
        ('ES-M0009B, Inconel X-750'), and ranked strings
        ('ES-M0009B, Inconel X-750 (90%)').
        """
        if display_value in ('Auto-detect', 'Vendor Spec', '---'):
            return display_value
        # Extract spec ID (everything before the first comma or space)
        return display_value.split(',')[0].split(' (')[0].strip()

    def _check_spec_mismatch(self, spec_id: str) -> bool:
        """Check if selected spec is a material type mismatch with extracted data.

        Returns True if user confirmed to proceed (or no mismatch), False to cancel.
        """
        if not self.extracted_data or spec_id in ('Auto-detect', 'Vendor Spec', '---'):
            return True

        from lib.matcher import SpecMatcher, _NON_METAL_FAMILIES, _extract_family_number

        mtr_is_metallic = SpecMatcher._is_metallic(self.extracted_data)
        spec = self.spec_loader.get(spec_id)
        if not spec:
            return True

        spec_is_non_metal = SpecMatcher._is_non_metal_spec(spec_id, spec)

        if mtr_is_metallic and spec_is_non_metal:
            grade = self.extracted_data.get('material_grade', 'Unknown')
            spec_material = spec.get('material', spec_id)
            # Find suggested alternatives
            matches = self.matcher.find_matching_specs(self.extracted_data)
            suggestions = ""
            if matches:
                top = [f"  - {m[0]} ({m[1]:.0%})" for m in matches[:3]]
                suggestions = "\n\nSuggested specs:\n" + "\n".join(top)

            answer = messagebox.askyesno(
                "Material Type Mismatch",
                f"The extracted material appears to be metallic ({grade}) "
                f"but the selected spec is for non-metal ({spec_material}).\n\n"
                f"This will likely produce incorrect validation results.\n"
                f"Continue anyway?{suggestions}",
            )
            return answer

        if not mtr_is_metallic and not spec_is_non_metal and self.extracted_data.get('chemistry'):
            spec_material = spec.get('material', spec_id)
            answer = messagebox.askyesno(
                "Material Type Mismatch",
                f"The extracted material appears to be non-metallic "
                f"but the selected spec is for metal ({spec_material}).\n\n"
                f"Continue anyway?",
            )
            return answer

        return True

    def _validate(self):
        """Re-validate extracted data against the currently selected spec."""
        if not self.extracted_data:
            return

        # Ensure weighted/ranked choices are available in the dropdown
        if hasattr(self, 'spec_dropdown'):
            self._rerank_spec_dropdown(self.extracted_data, self._resolve_spec_id(self.spec_var.get()))

        spec_id = self._resolve_spec_id(self.spec_var.get())
        if spec_id == '---':
            return
        if spec_id == 'Auto-detect':
            match = self.matcher.select_best_spec(self.extracted_data)
            if match:
                spec_id, confidence, reason = match
                self.spec_var.set(spec_id)
                self._set_status(f"Auto-detected: {spec_id} ({confidence:.0%})")
            else:
                messagebox.showwarning("No Match", "Could not auto-detect specification. Please select manually.")
                return

        # Check for material type mismatch before validating
        if not self._check_spec_mismatch(spec_id):
            return

        result = self.validator.validate(self.extracted_data, spec_id)
        self.validation_result = result

        id_label, id_value = _get_identifier(self.extracted_data or {})
        if result.heat_number and result.heat_number != 'N/A':
            id_value = result.heat_number

        if ctk:
            self._display_validation_results(result)
            self._update_header_status(result.overall_status, f"{id_label}# {id_value} | {spec_id}")
        else:
            self._clear_text(self.result_text)
            self._insert_text(self.result_text, format_validation_report(result, use_color=False))

        # Update pending history record with new validation
        if self._current_history_id:
            self.history.update(
                self._current_history_id,
                validation_details=result.to_dict(),
                result=result.overall_status,
                spec_id=spec_id,
                summary={
                    'pass_count': result.pass_count,
                    'fail_count': result.fail_count,
                    'missing_count': result.missing_count,
                },
            )

        self._set_status(f"{result.overall_status} - {id_label}# {id_value} (Spec: {spec_id}) — Review & Approve")

    def _open_override_dialog(self):
        """Open the override dialog for the current validation result."""
        if not self.validation_result:
            return
        # Pre-fill operator from Approved By field or previous override
        operator = ''
        if ctk and hasattr(self, 'approved_by_var'):
            operator = self.approved_by_var.get().strip()
        if not operator:
            operator = self._override_operator
        dialog = OverrideDialog(self.root, self.validation_result, operator)
        self.root.wait_window(dialog)
        if dialog.applied:
            self._override_operator = dialog.operator_name
            # Sync back to Approved By field
            if ctk and hasattr(self, 'approved_by_var'):
                self.approved_by_var.set(dialog.operator_name)
            self._display_validation_results(self.validation_result)
            self._update_header_status(
                self.validation_result.overall_status,
                self.header_file_label.cget('text'),
            )
            # Persist overrides to pending history record
            if self._current_history_id:
                self.history.update(
                    self._current_history_id,
                    validation_details=self.validation_result.to_dict(),
                    result=self.validation_result.overall_status,
                    summary={
                        'pass_count': self.validation_result.pass_count,
                        'fail_count': self.validation_result.fail_count,
                        'missing_count': self.validation_result.missing_count,
                    },
                )
            self._set_status(f"Applied {dialog.override_count} override(s) by {dialog.operator_name}")

    def _preview_tiff(self):
        """Open the staging TIFF in the system's default viewer."""
        if self.staging_tiff_path and Path(self.staging_tiff_path).exists():
            os.startfile(self.staging_tiff_path)
        else:
            messagebox.showwarning("No Preview", "No staging TIFF available to preview.")

    def _approve(self):
        """Approve the current result: move staging TIFF to archive, record history, generate report."""
        if not self.extracted_data:
            return

        is_assembly = self._assembly_result is not None and self._assembly_result.is_assembly

        # Material-type guardrail: block metal-vs-polymer cross-approval (skip for assemblies)
        if not is_assembly and self.validation_result and self.extracted_data:
            mismatch = self._check_material_spec_mismatch()
            if mismatch:
                messagebox.showerror(
                    "Material / Spec Type Mismatch",
                    mismatch + "\n\nApproval blocked. Select the correct spec and re-validate.",
                )
                return

        # Block approval unless validation is PASS (assemblies allow PASS or WARN)
        if is_assembly:
            assy_status = self._assembly_result.overall_status.upper()
            if assy_status == 'WARN' and self._assembly_result.missing_count > 0:
                missing_parts = [c for c in self._assembly_result.components if c.status == 'MISSING']
                missing_list = "\n".join(f"  - {c.part_number}: Heat {c.heat_number}" for c in missing_parts)
                proceed = messagebox.askyesno(
                    "Missing Heats",
                    f"The following heats are not accounted for:\n\n{missing_list}\n\n"
                    "Approve anyway? (Missing heats will be noted in the report.)",
                )
                if not proceed:
                    return
        elif self.validation_result:
            overall = self.validation_result.overall_status.upper()
            if overall != 'PASS':
                messagebox.showwarning(
                    "Cannot Approve",
                    f"Overall status is {overall}.\n\n"
                    "Only PASS results can be approved.\n"
                    "Use Override to correct any incorrect results first.",
                )
                return

        # Require "Approved By" name
        approved_by = ''
        if ctk and hasattr(self, 'approved_by_var'):
            approved_by = self.approved_by_var.get().strip()
        if not approved_by:
            # Fall back to override operator if set
            approved_by = self._override_operator
        if not approved_by:
            messagebox.showwarning(
                "Name Required",
                "Please enter your name in the 'Approved By' field before approving.",
            )
            if ctk and hasattr(self, 'approved_by_entry'):
                self.approved_by_entry.focus_set()
            return

        # Keep override operator in sync
        self._override_operator = approved_by

        archive_folder = self.config.effective_output_folder
        if not archive_folder:
            messagebox.showwarning("Setup Required", "Please configure archive folder in Settings.")
            self._navigate_to('settings')
            return

        if is_assembly:
            # Assembly naming: PO_CustomerPartNumber.tiff
            po_number = self.po_var.get().strip() if hasattr(self, 'po_var') else ''
            if not po_number:
                po_number = self._assembly_result.po_number
            if not po_number:
                po_number = self._prompt_for_po()

            cust_part = self.cust_part_var.get().strip() if hasattr(self, 'cust_part_var') else ''
            if not cust_part:
                cust_part = self._assembly_result.customer_part_number
            if not cust_part:
                if ctk:
                    dialog = ctk.CTkInputDialog(
                        text="Enter Customer Part Number:",
                        title="Customer Part Number Required",
                    )
                    cust_part = dialog.get_input() or ''
                else:
                    from tkinter import simpledialog
                    cust_part = simpledialog.askstring("Customer Part Number", "Enter Customer Part Number:") or ''

            archive_name = generate_assembly_archive_filename(po_number, cust_part)
        else:
            # Standard single-part naming: HeatNumber-PO.tiff
            _, id_value = _get_identifier(self.extracted_data)
            heat_number = id_value if id_value != 'N/A' else 'UNKNOWN'

            po_number = None
            if ctk and hasattr(self, 'po_var'):
                po_number = self.po_var.get().strip()
            if not po_number:
                po_number = self.extracted_data.get('po_number')
            if not po_number:
                po_number = self._prompt_for_po()

            archive_name = generate_archive_filename(heat_number, po_number)
        effective_output_dir = Path(archive_folder)
        if self.config.get('organize_by_po', False) and po_number:
            effective_output_dir = effective_output_dir / sanitize_filename(po_number)
            effective_output_dir.mkdir(parents=True, exist_ok=True)
        else:
            effective_output_dir.mkdir(parents=True, exist_ok=True)

        final_path = effective_output_dir / archive_name

        # Handle filename conflicts
        if final_path.exists():
            base = final_path.stem
            counter = 1
            while final_path.exists():
                final_path = effective_output_dir / f"{base}_{counter}.tiff"
                counter += 1

        # Move staging TIFF to archive
        if self.staging_tiff_path and Path(self.staging_tiff_path).exists():
            shutil.move(self.staging_tiff_path, str(final_path))
            self.staging_tiff_path = None
            logger.info("Approved: %s -> %s", archive_name, final_path)
        else:
            # No staging TIFF (e.g. non-PDF input) — nothing to move
            logger.info("Approved (no TIFF): %s", heat_number)

        # Generate verification report alongside the TIFF
        report_path = final_path.with_suffix('').with_name(
            final_path.stem + '_APPROVAL REPORT.txt'
        )
        try:
            from lib.report import generate_verification_report
            report_text = generate_verification_report(
                validation=self.validation_result,
                mtr_data=self.extracted_data,
                approved_by=approved_by,
                source_file=self.current_file,
                po_number=po_number,
            )
            report_path.write_text(report_text, encoding='utf-8')
            logger.info("Verification report: %s", report_path)
        except Exception as e:
            logger.error("Failed to write verification report: %s", e)

        # Approve the existing pending history record (or create one if missing)
        if self._current_history_id:
            # Update validation_details in case overrides were applied
            if self.validation_result:
                self.history.update(
                    self._current_history_id,
                    validation_details=self.validation_result.to_dict(),
                    result=self.validation_result.overall_status,
                    summary={
                        'pass_count': self.validation_result.pass_count,
                        'fail_count': self.validation_result.fail_count,
                        'missing_count': self.validation_result.missing_count,
                    },
                )
            self.history.approve(self._current_history_id, approved_by)
            self._current_history_id = None
        elif self.validation_result:
            # Fallback: no pending record exists — create an approved one
            spec_id = self._resolve_spec_id(self.spec_var.get()) if hasattr(self, 'spec_var') else None
            if spec_id in ('Auto-detect', '---'):
                spec_id = self.pipeline_result.spec_id if self.pipeline_result else None
            spec = self.spec_loader.get(spec_id) if spec_id else {}
            vid = self.history.record(
                self.validation_result, self.extracted_data,
                spec, self.current_file,
            )
            self.history.approve(vid, approved_by)

        # Update UI
        self._set_status(f"Approved: {final_path.name}")
        if ctk:
            self._update_header_status('PASS', f"Approved: {final_path.name}")
            self._set_button_state(self.approve_btn, 'disabled')
            self._set_button_state(self.override_btn, 'disabled')
            self._set_button_state(self.preview_btn, 'disabled')

        # Load next queued item if any
        if self._approval_queue:
            self.root.after(500, self._load_queued_result)

    def _load_queued_result(self):
        """Pop the next result from the approval queue and display it."""
        if not self._approval_queue:
            return
        next_result = self._approval_queue.pop(0)
        # Set the source file so _approve knows the origin
        self.current_file = next_result.source_file
        if ctk:
            filename = Path(next_result.source_file).name
            self.drop_zone.configure(
                text=f"{ICONS['file']}  {filename}\n(click to change)",
                text_color=COLORS['text_primary'],
            )
            self.header_file_label.configure(text=filename, text_color=COLORS['text_primary'])
        self._on_pipeline_complete(next_result)

    def _update_queue_indicator(self):
        """Update the queue count label."""
        if ctk and hasattr(self, 'queue_label'):
            count = len(self._approval_queue)
            if count > 0:
                self.queue_label.configure(text=f"Queue: {count} pending")
            else:
                self.queue_label.configure(text="")

    def _cleanup_staging(self):
        """Remove the current staging TIFF if it exists (unapproved)."""
        if self.staging_tiff_path and Path(self.staging_tiff_path).exists():
            try:
                os.remove(self.staging_tiff_path)
                logger.info("Cleaned up staging TIFF: %s", self.staging_tiff_path)
            except OSError:
                pass
        self.staging_tiff_path = None

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

    # ============================================================= Watch
    def _toggle_watch(self):
        """Toggle folder watching on/off."""
        if self.watcher.is_watching():
            self._stop_watching()
        else:
            watch_folder = self.config.get('watch_folder', '')
            if not watch_folder:
                messagebox.showinfo("Watch Folder", "Set a watch folder in Settings first.")
                self._navigate_to('settings')
                return
            self._start_watching(watch_folder)

    def _start_watching(self, folder: str):
        """Start watching a folder for new files."""
        auto_process = self.config.get('watch_auto_process', True)

        def on_new_file(file_path: str):
            logger.info("Watch: new file detected: %s", file_path)
            if auto_process:
                self.root.after(0, lambda fp=file_path: self._auto_process_watched_file(fp))
            else:
                self.root.after(0, lambda fp=file_path: self._load_file(fp))
                self.root.after(500, lambda: self._extract())

        self.watcher.start_watching(folder, on_new_file)
        self._update_watch_button(True)
        self._set_status(f"Watching: {folder}")

    def _stop_watching(self):
        """Stop the folder watcher."""
        self.watcher.stop_watching()
        self._watch_queue.clear()
        self._update_watch_button(False)
        self._set_status("Watch stopped")

    def _update_watch_button(self, is_watching: bool):
        """Update the watch button appearance."""
        if ctk:
            if is_watching:
                self.watch_btn.configure(
                    text=f"{ICONS['watch_on']}  Watch: ON",
                    text_color=COLORS['success'],
                )
            else:
                self.watch_btn.configure(
                    text=f"{ICONS['watch_off']}  Watch: OFF",
                    text_color=COLORS['text_secondary'],
                )
        else:
            self.watch_btn.configure(text="Watch: ON" if is_watching else "Watch: OFF")

    # ============================================================= Watch Auto-Process
    def _auto_process_watched_file(self, file_path: str):
        """Queue a watched file for processing and start the worker if idle."""
        if not self.config.is_configured():
            self._set_status("Watch: skipping — not configured")
            return

        self._watch_queue.append(file_path)
        logger.info("Watch: queued %s (%d in queue)", Path(file_path).name, len(self._watch_queue))

        if not self._watch_worker_running:
            self._watch_first_shown = False
            self._watch_worker_running = True
            self._set_button_state(self.extract_btn, 'disabled')
            self._start_progress_pulse()
            if ctk:
                self._update_header_status('INCOMPLETE', "Watch: processing...")
            self._set_status(f"Watch: {len(self._watch_queue)} file(s) queued...")
            threading.Thread(target=self._watch_worker, daemon=True).start()

    @staticmethod
    def _lower_process_priority():
        """Lower current process priority so GUI stays responsive during heavy OCR."""
        try:
            import sys
            if sys.platform == 'win32':
                import ctypes
                BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
                handle = ctypes.windll.kernel32.GetCurrentProcess()
                ctypes.windll.kernel32.SetPriorityClass(handle, BELOW_NORMAL_PRIORITY_CLASS)
                logger.debug("Lowered process priority to BELOW_NORMAL")
        except Exception:
            pass

    @staticmethod
    def _restore_process_priority():
        """Restore normal process priority."""
        try:
            import sys
            if sys.platform == 'win32':
                import ctypes
                NORMAL_PRIORITY_CLASS = 0x00000020
                handle = ctypes.windll.kernel32.GetCurrentProcess()
                ctypes.windll.kernel32.SetPriorityClass(handle, NORMAL_PRIORITY_CLASS)
                logger.debug("Restored process priority to NORMAL")
        except Exception:
            pass

    def _watch_worker(self):
        """Process watch queue with pre-extraction pipelining.

        Overlaps Phase A (OCR) of the next file with Phase B (Claude) of
        the current file for ~40% throughput improvement on multi-file drops.
        """
        from concurrent.futures import ThreadPoolExecutor

        # Lower process priority so GUI/system stays responsive
        self._lower_process_priority()

        api_key = self.config.anthropic_api_key
        paddle_path = self.config.get('paddle_model_path', '') or None
        dpi = self.config.get('preprocessing_dpi', 300)
        gpu_ocr = self.config.get('use_gpu_ocr', True)

        spec_id = None
        po_from_field = ''

        # Read UI values on main thread via synchronous callback
        ready = threading.Event()

        def _read_ui():
            nonlocal spec_id, po_from_field
            spec_id = self._resolve_spec_id(self.spec_var.get())
            if spec_id in ('Auto-detect', '---'):
                spec_id = None
            if hasattr(self, 'po_var'):
                po_from_field = self.po_var.get().strip()
            ready.set()

        self.root.after(0, _read_ui)
        ready.wait(timeout=5)

        executor = ThreadPoolExecutor(max_workers=1)
        next_pre = None
        processed_count = 0

        def _watch_total():
            """Live count: processed + remaining in queue."""
            return processed_count + len(self._watch_queue)

        try:
            t_worker_start = time.time()
            while True:
                # Inner loop: process all queued files
                while self._watch_queue:
                    file_path = self._watch_queue.pop(0)
                    processed_count += 1
                    t_file_start = time.time()
                    logger.info("[WATCH] === Starting file %d: %s ===", processed_count, Path(file_path).name)

                    # Update progress on UI (use live total via closure)
                    self.root.after(0, lambda i=processed_count, f=file_path: (
                        self._set_status(f"Watch: {i}/{_watch_total()} — {Path(f).name}"),
                        self._set_progress(0.05),
                        self._update_header_status('INCOMPLETE', f"Watch: {i}/{_watch_total()} — {Path(f).name}"),
                    ))

                    try:
                        # Wait for pre-extraction (or run inline for first)
                        # Start pulsing animation during OCR (no granular progress)
                        if next_pre is not None:
                            self.root.after(0, lambda fp=file_path, i=processed_count: (
                                self._set_status(f"Watch: {i}/{_watch_total()} — {Path(fp).name} — Waiting for OCR..."),
                                self._start_progress_pulse(),
                            ))
                            pre_result = next_pre.result()
                        else:
                            self.root.after(0, lambda fp=file_path, i=processed_count: (
                                self._set_status(f"Watch: {i}/{_watch_total()} — {Path(fp).name} — Running OCR..."),
                                self._update_header_status('INCOMPLETE', f"Watch: {i}/{_watch_total()} — OCR..."),
                                self._start_progress_pulse(),
                            ))
                            pre_result = pre_extract(
                                file_path, api_key=api_key,
                                paddle_model_path=paddle_path,
                                preprocessing_dpi=dpi,
                                use_gpu=gpu_ocr,
                            )
                        # OCR done — stop pulse (process_document will set determinate progress)
                        self.root.after(0, self._stop_progress_pulse)
                        logger.info("[WATCH] %s | pre_extract done: %.1fs into file",
                                    Path(file_path).name, time.time() - t_file_start)

                        # Kick off pre-extraction for NEXT file while we run Claude
                        next_pre = None
                        if self._watch_queue:
                            next_fpath = self._watch_queue[0]
                            next_pre = executor.submit(
                                pre_extract, next_fpath,
                                api_key=api_key,
                                paddle_model_path=paddle_path,
                                preprocessing_dpi=dpi,
                                use_gpu=gpu_ocr,
                            )

                        def on_progress(step, pct, fp=file_path, idx=processed_count):
                            self.root.after(0, lambda: (
                                self._set_progress(pct),
                                self._set_status(f"Watch: {idx}/{_watch_total()} — {Path(fp).name} — {step}"),
                                self._update_header_status('INCOMPLETE', f"Watch: {idx}/{_watch_total()} — {step}"),
                            ))

                        t0 = time.time()
                        # Assembly mode from dropdown
                        _asm = self.assembly_var.get() if hasattr(self, 'assembly_var') else 'Auto'
                        _fa = True if _asm == 'Assembly' else (False if _asm == 'Single Part' else None)

                        result = process_document(
                            pdf_path=file_path,
                            output_dir=self.config.effective_output_folder,
                            spec_id=spec_id,
                            anthropic_api_key=api_key,
                            paddle_model_path=paddle_path,
                            preprocessing_dpi=dpi,
                            tiff_dpi=self.config.get('tiff_dpi', 300),
                            tiff_compression=self.config.get('tiff_compression', 'lzw'),
                            on_progress=on_progress,
                            po_number=po_from_field or None,
                            organize_by_po=self.config.get('organize_by_po', False),
                            extraction_model=self.config.get('extraction_model', 'sonnet'),
                            pre_extracted=pre_result,
                            use_gpu_ocr=gpu_ocr,
                            force_assembly=_fa,
                        )
                        elapsed = time.time() - t0
                        logger.info("[WATCH] %s | process_document: %.1fs | file total: %.1fs",
                                    Path(file_path).name, elapsed, time.time() - t_file_start)

                        self.watcher.mark_processed(file_path)
                        result.source_file = file_path

                        def handle_watch_result(r=result, fp=file_path, el=elapsed):
                            # Check review state NOW (at result time), not at queue time
                            is_reviewing = (
                                ctk and hasattr(self, 'approve_btn')
                                and self.approve_btn.cget('state') == 'normal'
                            )

                            if is_reviewing or self._watch_first_shown:
                                # Queue for later review
                                if r.validation:
                                    ed = r.normalized_data or r.extracted_data
                                    spec = self.spec_loader.get(r.spec_id) if r.spec_id else {}
                                    vid = self.history.record(
                                        r.validation, ed, spec, fp,
                                        staging_tiff_path=r.output_tiff_path,
                                    )
                                    if el > 0:
                                        self.history.update(vid, processing_time=round(el, 1))
                                self._approval_queue.append(r)
                                self._update_queue_indicator()
                                remaining = len(self._watch_queue)
                                self._set_status(
                                    f"Watch: queued {Path(fp).name} "
                                    f"(Queue: {len(self._approval_queue)} pending"
                                    f"{f', {remaining} processing' if remaining else ''})"
                                )
                            else:
                                # First result — display directly
                                self._watch_first_shown = True
                                self.current_file = fp
                                if ctk:
                                    filename = Path(fp).name
                                    self.drop_zone.configure(
                                        text=f"{ICONS['file']}  {filename}\n(click to change)",
                                        text_color=COLORS['text_primary'],
                                    )
                                    self.header_file_label.configure(
                                        text=filename, text_color=COLORS['text_primary'],
                                    )
                                self._on_pipeline_complete(r, el)

                        self.root.after(0, handle_watch_result)

                    except Exception as e:
                        logger.exception("Watch error for %s: %s", file_path, e)
                        self.watcher.mark_processed(file_path)
                        try:
                            self.history.record_error(
                                source_file=file_path,
                                error_type="WATCH_PIPELINE_FAILED",
                                error_message=str(e),
                            )
                        except Exception:
                            logger.debug("Could not record watcher error to history", exc_info=True)

                # Inner queue drained — wait for late-arriving files
                logger.info("[WATCH] Queue drained, waiting 2.5s for late files...")
                time.sleep(2.5)
                if not self._watch_queue:
                    break  # No more files arrived, exit outer loop
                logger.info("[WATCH] %d late file(s) arrived, continuing...", len(self._watch_queue))

            executor.shutdown(wait=False)
            logger.info("[WATCH] === Worker complete: %d files in %.1fs ===",
                        processed_count, time.time() - t_worker_start)

        finally:
            self._restore_process_priority()

            def on_watch_done():
                self._watch_worker_running = False
                self._stop_progress_pulse()
                self._set_progress(0)
                self._set_button_state(self.extract_btn, 'normal')
                queue_count = len(self._approval_queue)
                if queue_count > 0:
                    self._set_status(
                        f"Watch: {processed_count} files processed. "
                        f"Queue: {queue_count} pending review."
                    )
                elif processed_count > 0:
                    self._set_status(f"Watch: {processed_count} files processed.")

            self.root.after(0, on_watch_done)

    # ============================================= Material / Spec Guard
    def _check_material_spec_mismatch(self) -> str:
        """Return a warning string if extracted material type doesn't match spec type, else ''."""
        if not self.validation_result or not self.extracted_data:
            return ''

        spec_id = self.validation_result.spec_id or ''
        chem = self.extracted_data.get('chemistry', {})

        # Determine if the extracted material is metallic
        from lib.matcher import SpecMatcher
        has_metals = SpecMatcher._is_metallic(self.extracted_data)

        # Determine if the spec is non-metal using the DDIC family number convention
        spec_data = self.spec_loader.get(spec_id) if spec_id else {}
        is_non_metal_spec = SpecMatcher._is_non_metal_spec(spec_id, spec_data or {})

        if has_metals and is_non_metal_spec:
            return (
                f"The extracted material has metallic chemistry (Fe, Cr, Ni, etc.) "
                f"but is being validated against a non-metal spec ({spec_id}).\n"
                f"This is almost certainly wrong."
            )
        if not has_metals and not is_non_metal_spec and chem:
            return (
                f"The extracted material has no metallic chemistry "
                f"but is being validated against a metal spec ({spec_id}).\n"
                f"This is almost certainly wrong."
            )

        return ''

    # ============================================================= Helpers
    def _set_status(self, text: str):
        """Update status bar."""
        self.status_label.configure(text=text)

    def _set_button_state(self, button, state: str):
        """Set button state with clear visual feedback."""
        # Store original colors on first use
        if not hasattr(button, '_orig_fg'):
            button._orig_fg = button.cget('fg_color')
            button._orig_text = button.cget('text_color')

        button.configure(state=state)
        if state == 'disabled':
            button.configure(
                fg_color=COLORS['btn_disabled_fg'],
                text_color=COLORS['btn_disabled_text'],
            )
        else:
            button.configure(
                fg_color=button._orig_fg,
                text_color=button._orig_text,
            )

    def _set_progress(self, value: float):
        """Update progress bar (0.0 to 1.0)."""
        if ctk and hasattr(self, 'progress_bar') and self.progress_bar:
            self._stop_progress_pulse()
            self.progress_bar.set(value)

    def _start_progress_pulse(self):
        """Start indeterminate progress bar animation (pulsing/bouncing)."""
        if ctk and hasattr(self, 'progress_bar') and self.progress_bar:
            self.progress_bar.configure(mode='indeterminate')
            self.progress_bar.start()

    def _stop_progress_pulse(self):
        """Stop indeterminate animation and switch back to determinate mode."""
        if ctk and hasattr(self, 'progress_bar') and self.progress_bar:
            try:
                self.progress_bar.stop()
            except Exception:
                pass
            self.progress_bar.configure(mode='determinate')

    def _clear_text(self, widget):
        """Clear text widget."""
        widget.delete('1.0', 'end')

    def _insert_text(self, widget, text: str):
        """Insert text into widget."""
        widget.insert('end', text)

    def _on_close(self):
        """Handle window close.

        Staging TIFFs for pending history records are kept — they'll be needed
        when the user reviews them later.  Only TIFFs that were never recorded
        to history (e.g. error cases with no _current_history_id) are removed.
        """
        if self.watcher.is_watching():
            self.watcher.stop_watching()
        # Only clean up staging TIFF if it was never persisted to history
        if self.staging_tiff_path and not self._current_history_id:
            try:
                if Path(self.staging_tiff_path).exists():
                    os.remove(self.staging_tiff_path)
            except OSError:
                pass
        self.staging_tiff_path = None
        # Queued items are already in history — don't delete their TIFFs
        self._approval_queue.clear()
        self.config.update({
            'window_width': self.root.winfo_width(),
            'window_height': self.root.winfo_height(),
        })
        self.root.destroy()

    def run(self):
        """Start the application."""
        self.root.mainloop()

    # ============================================================= TTK Fallback
    def _create_file_section_fallback(self, parent):
        """Fallback file section for standard tkinter."""
        frame = ttk.LabelFrame(parent, text="Input File", padding=10)
        frame.pack(fill='x', pady=(0, 10))

        btn = ttk.Button(frame, text="Browse...", command=self._browse_file)
        btn.pack(side='left', padx=5)

        self.file_label = ttk.Label(frame, text="No file selected")
        self.file_label.pack(side='left', padx=10)

    def _create_main_section_fallback(self, parent):
        """Fallback main section for standard tkinter."""
        frame = ttk.Frame(parent)
        frame.pack(fill='both', expand=True)

        self.data_text = tk.Text(frame, width=50, height=20)
        self.data_text.pack(side='left', fill='both', expand=True, padx=5)

        self.result_text = tk.Text(frame, width=50, height=20)
        self.result_text.pack(side='right', fill='both', expand=True, padx=5)

        self.spec_var = tk.StringVar(value='Auto-detect')

    def _create_action_section_fallback(self, parent):
        """Fallback action section for standard tkinter."""
        frame = ttk.Frame(parent)
        frame.pack(fill='x', pady=10)

        self.extract_btn = ttk.Button(frame, text="Extract", command=self._extract, state='disabled')
        self.extract_btn.pack(side='left', padx=5)

        self.validate_btn = ttk.Button(frame, text="Validate", command=self._validate, state='disabled')
        self.validate_btn.pack(side='left', padx=5)

        self.override_btn = ttk.Button(frame, text="Override", command=self._open_override_dialog, state='disabled')
        self.override_btn.pack(side='left', padx=5)

        self.preview_btn = ttk.Button(frame, text="Preview", command=self._preview_tiff, state='disabled')
        self.preview_btn.pack(side='left', padx=5)

        self.approve_btn = ttk.Button(frame, text="Approve", command=self._approve, state='disabled')
        self.approve_btn.pack(side='left', padx=5)

        ttk.Label(frame, text="Approved By:").pack(side='left', padx=(10, 2))
        self.approved_by_var = tk.StringVar(value='')
        self.approved_by_entry = ttk.Entry(frame, textvariable=self.approved_by_var, width=15)
        self.approved_by_entry.pack(side='left', padx=2)

        self.watch_btn = ttk.Button(frame, text="Watch: OFF", command=self._toggle_watch)
        self.watch_btn.pack(side='left', padx=10)

        self.queue_label = ttk.Label(frame, text="")
        self.queue_label.pack(side='left', padx=5)

        self.status_label = ttk.Label(frame, text="Ready")
        self.status_label.pack(side='right', padx=10)

        self.progress_bar = None


def main():
    """Application entry point."""
    # Log to both console and file so timing data is always captured
    log_format = '%(asctime)s [%(name)s] %(levelname)s: %(message)s'
    logging.basicConfig(level=logging.INFO, format=log_format)

    log_file = Path(__file__).resolve().parent.parent.parent / 'pipeline.log'
    file_handler = logging.FileHandler(str(log_file), mode='w', encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(log_format))
    logging.getLogger().addHandler(file_handler)
    logging.info("Logging to %s", log_file)

    app = MaterialValidatorApp()
    app.run()


if __name__ == '__main__':
    main()
