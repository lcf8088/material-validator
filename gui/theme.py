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
    'SKIP':       COLORS['text_secondary'],
    'UNKNOWN':    COLORS['text_secondary'],
}


def status_color(status: str) -> str:
    """Return the hex color for a given validation status string."""
    return STATUS_COLORS.get(status.upper(), COLORS['text_secondary'])


# ------------------------------------------------------------------ Layout
SIDEBAR_WIDTH = 210
