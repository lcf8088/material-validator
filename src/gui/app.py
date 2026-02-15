"""
Downhole & Design MTR Validator - Desktop GUI Application

Main application window with sidebar navigation, D&D branded dark theme,
card-based content panels, and colored status badges.
Uses PaddleOCR + Claude pipeline for extraction and validation.
"""

import json
import logging
import os
import shutil
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List

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
from lib.pipeline import process_document, PipelineResult
from lib.watcher import FolderWatcher

from .config import Config
from .tiff_export import generate_archive_filename, sanitize_filename
from .settings import SettingsPanel
from .override_dialog import OverrideDialog
from .theme import COLORS, FONTS, ICONS, SIDEBAR_WIDTH, status_color

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
        self._approval_queue: List[PipelineResult] = []
        self.staging_tiff_path: Optional[str] = None
        self._pipeline_lock = threading.Lock()
        self._override_operator: str = ""
        self._current_history_id: Optional[str] = None

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

        specs = ['Auto-detect'] + self.spec_loader.list_ids()
        self.spec_var = ctk.StringVar(value='Auto-detect')
        self.spec_dropdown = ctk.CTkComboBox(
            left_controls, values=specs, variable=self.spec_var, width=170,
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
            text_color='#FFFFFF',
            command=self._extract,
        )
        self.extract_btn.pack(side='left', padx=4)

        self.validate_btn = ctk.CTkButton(
            btn_frame, text="Re-Validate", width=110,
            font=FONTS['badge'], state='disabled',
            fg_color=COLORS['bg_card'], hover_color=COLORS['surface_hl'],
            border_color=COLORS['border'], border_width=1,
            text_color=COLORS['text_primary'],
            command=self._validate,
        )
        self.validate_btn.pack(side='left', padx=4)

        self.override_btn = ctk.CTkButton(
            btn_frame, text="Override", width=100,
            font=FONTS['badge'], state='disabled',
            fg_color=COLORS['orange'], hover_color=COLORS['orange_hover'],
            text_color='#FFFFFF',
            command=self._open_override_dialog,
        )
        self.override_btn.pack(side='left', padx=4)

        self.preview_btn = ctk.CTkButton(
            btn_frame, text="Preview", width=90,
            font=FONTS['badge'], state='disabled',
            fg_color=COLORS['bg_card'], hover_color=COLORS['surface_hl'],
            border_color=COLORS['border'], border_width=1,
            text_color=COLORS['text_primary'],
            command=self._preview_tiff,
        )
        self.preview_btn.pack(side='left', padx=4)

        self.approve_btn = ctk.CTkButton(
            btn_frame, text="Approve", width=110,
            font=FONTS['badge'], state='disabled',
            fg_color=COLORS['success'], hover_color='#4A9A3A',
            text_color='#FFFFFF',
            command=self._approve,
        )
        self.approve_btn.pack(side='left', padx=4)

        # Queue indicator (visible when watch queues items)
        self.queue_label = ctk.CTkLabel(
            btn_frame, text="", font=FONTS['small'],
            text_color=COLORS['orange'],
        )
        self.queue_label.pack(side='left', padx=(8, 0))

        # -- Bottom row: data card + result card --
        cards = ctk.CTkFrame(view, fg_color='transparent')
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
        # Reconstruct CertValidation from stored details
        details = record.get('validation_details', {})
        if details:
            self.validation_result = CertValidation.from_dict(details)
        else:
            self.validation_result = None

        self.extracted_data = record.get('mtr_data', {})
        self.current_file = record.get('source_file')
        self._current_history_id = record.get('validation_id')
        self.staging_tiff_path = record.get('staging_tiff_path') or None

        # Switch to validate view
        self._navigate_to('validate')

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
                specs = ['Auto-detect'] + self.spec_loader.list_ids()
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
            tw.insert('end', f"  {'Element':<10}{'Min':>8}{'Max':>8}{'Actual':>10}  {'Status'}\n", 'label')
            tw.insert('end', "  " + "-" * 48 + "\n", 'label')
            for r in result.chemistry_results:
                smin = f"{r.spec_min}" if r.spec_min is not None else "-"
                smax = f"{r.spec_max}" if r.spec_max is not None else "-"
                actual = f"{r.actual_value}" if r.actual_value is not None else "-"
                tw.insert('end', f"  {r.property_name:<10}{smin:>8}{smax:>8}{actual:>10}  ", 'value')
                tag = r.status.lower() if r.status.lower() in ('pass', 'fail', 'missing', 'skip') else 'warn'
                tw.insert('end', f"{r.status}\n", tag)
                if r.is_overridden:
                    tw.insert('end', f"         ^^ OVERRIDDEN from {r.original_status} by {r.override_by}: {r.override_reason}\n", 'override')

        if result.mechanical_results:
            tw.insert('end', "\n  Mechanical Properties\n", 'header')
            tw.insert('end', f"  {'Property':<20}{'Min':>8}{'Max':>8}{'Actual':>10}  {'Status'}\n", 'label')
            tw.insert('end', "  " + "-" * 58 + "\n", 'label')
            for r in result.mechanical_results:
                smin = f"{r.spec_min}" if r.spec_min is not None else "-"
                smax = f"{r.spec_max}" if r.spec_max is not None else "-"
                actual = f"{r.actual_value}" if r.actual_value is not None else "-"
                tw.insert('end', f"  {r.property_name:<20}{smin:>8}{smax:>8}{actual:>10}  ", 'value')
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

        spec_id = self.spec_var.get()
        if spec_id == 'Auto-detect':
            spec_id = None

        def do_pipeline():
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
                )

                self.root.after(0, lambda: self._on_pipeline_complete(result))

            except Exception as e:
                self.root.after(0, lambda: self._on_extract_error(str(e)))

        threading.Thread(target=do_pipeline, daemon=True).start()

    def _on_pipeline_complete(self, result: PipelineResult):
        """Handle pipeline completion — display results for review (no archiving yet)."""
        self.pipeline_result = result
        self.extracted_data = result.normalized_data or result.extracted_data
        self.validation_result = result.validation

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
            self._set_status(f"{status} - {id_label}# {id_value} (Spec: {result.spec_id}) — Review & Approve")
            if ctk:
                self._update_header_status(status, f"{id_label}# {id_value} | {result.spec_id}")
        else:
            if result.sanity and any(result.sanity.values()):
                self._insert_text(self.result_text, format_sanity_report(result.sanity))
            self._set_status(f"Extracted: {id_label}# {id_value} — Review & Approve")
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

        # Update spec dropdown to show which spec was used
        if result.spec_id and hasattr(self, 'spec_var'):
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

    def _validate(self):
        """Re-validate extracted data against the currently selected spec."""
        if not self.extracted_data:
            return

        spec_id = self.spec_var.get()
        if spec_id == 'Auto-detect':
            match = self.matcher.select_best_spec(self.extracted_data)
            if match:
                spec_id, confidence, reason = match
                self.spec_var.set(spec_id)
                self._set_status(f"Auto-detected: {spec_id} ({confidence:.0%})")
            else:
                messagebox.showwarning("No Match", "Could not auto-detect specification. Please select manually.")
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

        # Material-type guardrail: block metal-vs-polymer cross-approval
        if self.validation_result and self.extracted_data:
            mismatch = self._check_material_spec_mismatch()
            if mismatch:
                messagebox.showerror(
                    "Material / Spec Type Mismatch",
                    mismatch + "\n\nApproval blocked. Select the correct spec and re-validate.",
                )
                return

        # Block approval unless validation is PASS
        if self.validation_result:
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

        # Get identifier (heat/batch number)
        _, id_value = _get_identifier(self.extracted_data)
        heat_number = id_value if id_value != 'N/A' else 'UNKNOWN'

        # Get PO from the entry field first, then extracted data, then prompt
        po_number = None
        if ctk and hasattr(self, 'po_var'):
            po_number = self.po_var.get().strip()
        if not po_number:
            po_number = self.extracted_data.get('po_number')
        if not po_number:
            po_number = self._prompt_for_po()

        # Compute final filename and destination
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
            spec_id = self.spec_var.get() if hasattr(self, 'spec_var') else None
            if spec_id == 'Auto-detect':
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
        """Auto-process a file detected by the watcher — queues if a review is active."""
        if not self.config.is_configured():
            self._set_status("Watch: skipping — not configured")
            return

        # Check if currently reviewing (approve_btn enabled means active review)
        currently_reviewing = (
            ctk and hasattr(self, 'approve_btn')
            and self.approve_btn.cget('state') == 'normal'
        )

        self._set_status(f"Watch: processing {Path(file_path).name}...")
        if not currently_reviewing:
            self._set_button_state(self.extract_btn, 'disabled')
            self._set_progress(0)
            if ctk:
                self._update_header_status('INCOMPLETE', "Processing...")

        spec_id = self.spec_var.get()
        if spec_id == 'Auto-detect':
            spec_id = None

        def do_auto():
            if not self._pipeline_lock.acquire(timeout=0.1):
                logger.info("Watch: pipeline busy, queueing %s", file_path)
                self._pipeline_lock.acquire()
            try:
                output_dir = self.config.effective_output_folder
                po_from_field = ''
                if hasattr(self, 'po_var'):
                    po_from_field = self.po_var.get().strip()

                def on_progress(step, pct):
                    if not currently_reviewing:
                        self.root.after(0, lambda: self._set_progress(pct))
                    self.root.after(0, lambda: self._set_status(f"Watch: {step}"))

                result = process_document(
                    pdf_path=file_path,
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
                )

                self.watcher.mark_processed(file_path)

                def handle_result():
                    if currently_reviewing:
                        # Record to history immediately even when queuing
                        if result.validation:
                            ed = result.normalized_data or result.extracted_data
                            spec = self.spec_loader.get(result.spec_id) if result.spec_id else {}
                            self.history.record(
                                result.validation, ed, spec, file_path,
                                staging_tiff_path=result.output_tiff_path,
                            )
                        self._approval_queue.append(result)
                        self._update_queue_indicator()
                        self._set_status(
                            f"Watch: queued {Path(file_path).name} "
                            f"(Queue: {len(self._approval_queue)} pending)"
                        )
                    else:
                        # No active review — display directly
                        self.current_file = file_path
                        if ctk:
                            filename = Path(file_path).name
                            self.drop_zone.configure(
                                text=f"{ICONS['file']}  {filename}\n(click to change)",
                                text_color=COLORS['text_primary'],
                            )
                            self.header_file_label.configure(
                                text=filename, text_color=COLORS['text_primary']
                            )
                        self._on_pipeline_complete(result)

                self.root.after(0, handle_result)

            except Exception as e:
                logger.exception("Watch auto-process error: %s", e)
                self.watcher.mark_processed(file_path)
                # Record error in history for audit trail
                try:
                    self.history.record_error(
                        source_file=file_path,
                        error_type="WATCH_PIPELINE_FAILED",
                        error_message=str(e),
                    )
                except Exception:
                    logger.debug("Could not record watcher error to history", exc_info=True)
                if not currently_reviewing:
                    self.root.after(0, lambda: self._on_extract_error(str(e)))
            finally:
                self._pipeline_lock.release()

        threading.Thread(target=do_auto, daemon=True).start()

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
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    )
    app = MaterialValidatorApp()
    app.run()


if __name__ == '__main__':
    main()
