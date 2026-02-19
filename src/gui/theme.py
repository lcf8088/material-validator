"""
Centralized theme constants for Downhole & Design MTR Validator GUI.

D&D branded palette: royal blue, silver-gray, and orange accents.
"""

# ------------------------------------------------------------------ Colors
# D&D brand: royal blue from logo, silver-gray text, orange for pops
COLORS = {
    # Backgrounds (dark with subtle blue undertone)
    'bg_darkest':    '#0f1219',
    'bg_dark':       '#161b28',
    'bg_card':       '#1e2538',
    'bg_input':      '#131824',

    # Brand blue (from D&D logo)
    'accent':        '#2E50A0',
    'accent_hover':  '#3B63B8',
    'accent_light':  '#5A82D0',

    # Brand orange (subtle pops - borders, highlights)
    'orange':        '#D47B2E',
    'orange_hover':  '#E08D3E',

    # Text (silver-gray from logo)
    'text_primary':  '#C8CDD8',
    'text_secondary':'#6B7394',

    # Functional
    'success':       '#5DAE4A',
    'warning':       '#D47B2E',
    'error':         '#D94848',

    # Surfaces
    'border':        '#2E3650',
    'border_orange': '#5C3A1A',
    'surface_hl':    '#232C42',

    # Disabled buttons
    'btn_disabled_fg':   '#1a2030',
    'btn_disabled_text': '#4a5068',
}

# ------------------------------------------------------------------ Fonts
FONTS = {
    'app_title':      ('Segoe UI', 18, 'bold'),
    'section_header': ('Segoe UI', 16, 'bold'),
    'card_title':     ('Segoe UI', 14, 'bold'),
    'body':           ('Segoe UI', 13),
    'label':          ('Segoe UI', 12),
    'badge':          ('Segoe UI', 12, 'bold'),
    'small':          ('Segoe UI', 10),
    'mono':           ('Consolas', 12),
}

# ------------------------------------------------------------------ Icons
ICONS = {
    'validate': '\u2714',    # heavy check mark
    'history':  '\u23F0',    # alarm clock
    'settings': '\u2699',    # gear
    'drop':     '\u21E9',    # downwards white arrow
    'pass':     '\u25CF',    # black circle (filled)
    'fail':     '\u25CF',    # black circle (filled) - colored red
    'watch_on': '\u25C9',    # fisheye (filled circle)
    'watch_off':'\u25CB',    # white circle
    'file':     '\u25A0',    # black square
    'arrow':    '\u25B6',    # right-pointing triangle
    'batch':    '\u25A6',    # square with orthogonal crosshatch fill
}

# ------------------------------------------------------------------ Status
STATUS_COLORS = {
    'PASS':       COLORS['success'],
    'FAIL':       COLORS['error'],
    'INCOMPLETE': COLORS['warning'],
    'MISSING':    COLORS['text_secondary'],
    'ERROR':      COLORS['error'],
    'SKIP':        COLORS['text_secondary'],
    'UNKNOWN':     COLORS['text_secondary'],
    'VENDOR SPEC': COLORS['accent'],
}


def status_color(status: str) -> str:
    """Return the hex color for a given validation status string."""
    return STATUS_COLORS.get(status.upper(), COLORS['text_secondary'])


# ------------------------------------------------------------------ Layout
SIDEBAR_WIDTH = 210


# --------------------------------------------------------- ScrollableComboBox
import tkinter as _tk

try:
    import customtkinter as _ctk

    class ScrollableComboBox(_ctk.CTkFrame):
        """Drop-down selector with a scrollable popup list.

        Drop-in replacement for CTkComboBox when the item list is long.
        Uses a native tk.Toplevel + tk.Listbox for reliable popup behavior
        on Windows.
        """

        def __init__(self, master, values=None, variable=None, width=300,
                     fg_color=None, border_color=None, text_color=None,
                     font=None, button_color=None, button_hover_color=None,
                     dropdown_fg_color=None, dropdown_hover_color=None,
                     dropdown_text_color=None, **kwargs):
            super().__init__(master, fg_color='transparent', **kwargs)

            self._values = list(values or [])
            self._variable = variable or _ctk.StringVar()
            self._popup = None
            self._width = width
            self._dropdown_fg = dropdown_fg_color or COLORS['bg_card']
            self._dropdown_hover = dropdown_hover_color or COLORS['surface_hl']
            self._dropdown_text = dropdown_text_color or COLORS['text_primary']
            self._btn_color = button_color or COLORS['accent']
            self._btn_hover = button_hover_color or COLORS['accent_hover']
            self._font = font or FONTS['body']
            self._input_fg = fg_color or COLORS['bg_input']
            self._border_color = border_color or COLORS['border']

            # Display label (shows current selection)
            self._label = _ctk.CTkLabel(
                self, textvariable=self._variable, width=width - 36,
                height=32, anchor='w',
                fg_color=self._input_fg, corner_radius=6,
                text_color=COLORS['text_primary'], font=self._font,
                padx=8,
            )
            self._label.pack(side='left', fill='y')
            self._label.bind('<Button-1>', lambda e: self._toggle_popup())

            # Arrow button
            self._arrow_btn = _ctk.CTkButton(
                self, text='\u25BC', width=36, height=32,
                fg_color=self._btn_color, hover_color=self._btn_hover,
                text_color='#FFFFFF', font=('Segoe UI', 10),
                corner_radius=6,
                command=self._toggle_popup,
            )
            self._arrow_btn.pack(side='left')

        # -- Public API (CTkComboBox compatible) --

        def configure(self, **kwargs):
            if 'values' in kwargs:
                self._values = list(kwargs.pop('values'))
                if self._popup:
                    self._close_popup()
            super().configure(**kwargs)

        def cget(self, key):
            if key == 'values':
                return self._values
            return super().cget(key)

        def set(self, value):
            self._variable.set(value)

        def get(self):
            return self._variable.get()

        # -- Popup management --

        def _toggle_popup(self):
            if self._popup and self._popup.winfo_exists():
                self._close_popup()
            else:
                self._open_popup()

        def _open_popup(self):
            if self._popup and self._popup.winfo_exists():
                return

            self.update_idletasks()
            x = self.winfo_rootx()
            y = self.winfo_rooty() + self.winfo_height()
            visible = min(len(self._values), 15)

            # Plain tk.Toplevel — reliable on Windows
            self._popup = _tk.Toplevel(self)
            self._popup.overrideredirect(True)
            self._popup.configure(bg=self._dropdown_fg)

            # Listbox + scrollbar
            frame = _tk.Frame(self._popup, bg=self._dropdown_fg,
                              highlightbackground=self._border_color,
                              highlightthickness=1)
            frame.pack(fill='both', expand=True)

            scrollbar = _tk.Scrollbar(frame)
            scrollbar.pack(side='right', fill='y')

            # Use tkinter font matching the app body font.
            # CTk size 13 ≈ tk size -13 (negative = pixels in tkinter)
            import tkinter.font as _tkfont
            lb_font = _tkfont.Font(family='Segoe UI', size=-13)

            self._listbox = _tk.Listbox(
                frame,
                height=visible,
                width=0,  # auto-size
                bg=self._dropdown_fg,
                fg=self._dropdown_text,
                selectbackground=self._btn_color,
                selectforeground='#FFFFFF',
                highlightthickness=0,
                borderwidth=0,
                font=lb_font,
                activestyle='none',
                yscrollcommand=scrollbar.set,
                relief='flat',
            )
            self._listbox.pack(side='left', fill='both', expand=True)
            scrollbar.config(command=self._listbox.yview)

            current = self.get()
            select_idx = None
            for i, val in enumerate(self._values):
                # Add left padding for readability
                self._listbox.insert('end', f'  {val}')
                if val == '---':
                    self._listbox.itemconfig(i, fg=COLORS['border'],
                                             selectbackground=self._dropdown_fg)
                elif val == current or (current and val.startswith(
                        current.split(',')[0].split(' (')[0])):
                    select_idx = i

            if select_idx is not None:
                self._listbox.selection_set(select_idx)
                self._listbox.see(select_idx)

            self._listbox.bind('<<ListboxSelect>>', self._on_listbox_select)
            self._listbox.bind('<Escape>', lambda e: self._close_popup())

            # Size the popup
            self._popup.update_idletasks()
            popup_w = max(self._width, self._listbox.winfo_reqwidth() + 20)
            popup_h = self._listbox.winfo_reqheight() + 4
            self._popup.geometry(f'{popup_w}x{popup_h}+{x}+{y}')

            self._listbox.focus_set()

            # Close when clicking outside
            self._popup.bind('<Deactivate>', lambda e: self.after(50, self._close_popup))

        def _on_listbox_select(self, event):
            sel = self._listbox.curselection()
            if not sel:
                return
            value = self._values[sel[0]]
            if value == '---':
                return
            self._variable.set(value)
            self._close_popup()

        def _close_popup(self):
            if self._popup and self._popup.winfo_exists():
                self._popup.destroy()
            self._popup = None

except ImportError:
    ScrollableComboBox = None
