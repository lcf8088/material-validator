"""
Override Dialog - allows operators to override individual validation results
with mandatory name and per-field reason for audit trail.
"""

import customtkinter as ctk
from tkinter import messagebox

from .theme import COLORS, FONTS

STATUS_OPTIONS = ['PASS', 'FAIL', 'MISSING', 'SKIP']


class OverrideDialog(ctk.CTkToplevel):
    """Modal dialog to override individual validation result statuses."""

    def __init__(self, parent, validation, operator_name: str = ""):
        super().__init__(parent)
        self.title("Override Validation Results")
        self.geometry("780x520")
        self.resizable(True, True)
        self.configure(fg_color=COLORS['bg_darkest'])

        self.validation = validation
        self.applied = False
        self.override_count = 0
        # (category, index, status_var, original_status, reason_var, reason_entry)
        self._rows = []

        # Make modal
        self.transient(parent)
        self.grab_set()

        self._build_ui(operator_name)
        self.after(100, self.focus_force)

    def _build_ui(self, operator_name: str):
        # -- Top: Operator name only --
        top = ctk.CTkFrame(self, fg_color=COLORS['bg_card'], corner_radius=8)
        top.pack(fill='x', padx=12, pady=(12, 6))

        row1 = ctk.CTkFrame(top, fg_color='transparent')
        row1.pack(fill='x', padx=12, pady=10)

        ctk.CTkLabel(
            row1, text="Operator Name:", font=FONTS['label'],
            text_color=COLORS['text_secondary'],
        ).pack(side='left')

        self.operator_var = ctk.StringVar(value=operator_name)
        self.operator_entry = ctk.CTkEntry(
            row1, textvariable=self.operator_var, width=260,
            placeholder_text="Your name (required)",
            fg_color=COLORS['bg_input'], border_color=COLORS['border'],
            text_color=COLORS['text_primary'], font=FONTS['body'],
        )
        self.operator_entry.pack(side='left', padx=(8, 0))

        ctk.CTkLabel(
            row1, text="Change status and enter reason per field below",
            font=FONTS['small'], text_color=COLORS['text_secondary'],
        ).pack(side='right', padx=(12, 0))

        # -- Middle: Scrollable results list --
        scroll = ctk.CTkScrollableFrame(
            self, fg_color=COLORS['bg_darkest'],
            scrollbar_button_color=COLORS['border'],
            scrollbar_button_hover_color=COLORS['surface_hl'],
        )
        scroll.pack(fill='both', expand=True, padx=12, pady=6)

        for category, label, results in [
            ('chemistry', 'Chemistry', self.validation.chemistry_results),
            ('mechanical', 'Mechanical Properties', self.validation.mechanical_results),
            ('special', 'Special Requirements', self.validation.special_results),
        ]:
            if not results:
                continue
            ctk.CTkLabel(
                scroll, text=label, font=FONTS['card_title'],
                text_color=COLORS['accent_light'],
            ).pack(anchor='w', pady=(8, 4), padx=4)

            for i, r in enumerate(results):
                self._add_result_row(scroll, category, i, r)

        # -- Bottom: buttons --
        bottom = ctk.CTkFrame(self, fg_color='transparent')
        bottom.pack(fill='x', padx=12, pady=(6, 12))

        ctk.CTkButton(
            bottom, text="Cancel", width=100,
            font=FONTS['badge'],
            fg_color=COLORS['bg_card'], hover_color=COLORS['surface_hl'],
            border_color=COLORS['border'], border_width=1,
            text_color=COLORS['text_primary'],
            command=self._cancel,
        ).pack(side='right', padx=4)

        ctk.CTkButton(
            bottom, text="Apply Overrides", width=140,
            font=FONTS['badge'],
            fg_color=COLORS['orange'], hover_color=COLORS['orange_hover'],
            text_color='#FFFFFF',
            command=self._apply,
        ).pack(side='right', padx=4)

    def _add_result_row(self, parent, category: str, index: int, result):
        """Add a two-line result row: status line + per-field reason entry."""
        container = ctk.CTkFrame(
            parent, fg_color=COLORS['bg_card'], corner_radius=6,
            border_color=COLORS['border'], border_width=1,
        )
        container.pack(fill='x', pady=2, padx=4)

        # -- Top line: property | current status | arrow | dropdown --
        top_row = ctk.CTkFrame(container, fg_color='transparent')
        top_row.pack(fill='x', padx=10, pady=(4, 0))

        # Property name
        ctk.CTkLabel(
            top_row, text=result.property_name, font=FONTS['body'],
            text_color=COLORS['text_primary'], width=160, anchor='w',
        ).pack(side='left')

        # Current status (colored)
        from .theme import status_color
        color = status_color(result.status)
        ctk.CTkLabel(
            top_row, text=result.status, font=FONTS['badge'],
            text_color=color, width=70, anchor='w',
        ).pack(side='left', padx=(0, 4))

        # Override indicator if already overridden
        if result.is_overridden:
            ctk.CTkLabel(
                top_row, text=f"(was {result.original_status})", font=FONTS['small'],
                text_color=COLORS['orange'], anchor='w',
            ).pack(side='left', padx=(0, 8))

        # Dropdown to change status
        status_var = ctk.StringVar(value=result.status)
        ctk.CTkComboBox(
            top_row, values=STATUS_OPTIONS, variable=status_var, width=100,
            fg_color=COLORS['bg_input'], border_color=COLORS['border'],
            button_color=COLORS['accent'], button_hover_color=COLORS['accent_hover'],
            dropdown_fg_color=COLORS['bg_card'], dropdown_hover_color=COLORS['surface_hl'],
            dropdown_text_color=COLORS['text_primary'],
            text_color=COLORS['text_primary'], font=FONTS['small'],
        ).pack(side='right')

        ctk.CTkLabel(
            top_row, text="\u2192", font=FONTS['body'],
            text_color=COLORS['text_secondary'],
        ).pack(side='right', padx=6)

        # -- Bottom line: per-field reason entry --
        reason_row = ctk.CTkFrame(container, fg_color='transparent')
        reason_row.pack(fill='x', padx=10, pady=(2, 4))

        reason_var = ctk.StringVar(
            value=result.override_reason if result.is_overridden else ''
        )
        reason_entry = ctk.CTkEntry(
            reason_row, textvariable=reason_var,
            placeholder_text="Reason for override (required if changed)",
            fg_color=COLORS['bg_input'], border_color=COLORS['border'],
            text_color=COLORS['text_primary'], font=FONTS['small'], height=26,
        )
        reason_entry.pack(fill='x')

        self._rows.append((
            category, index, status_var, result.status, reason_var, reason_entry,
        ))

    def _apply(self):
        """Apply all changed overrides."""
        # Collect changes
        changes = []
        missing_reasons = []
        for category, index, status_var, original, reason_var, reason_entry in self._rows:
            new_status = status_var.get().strip().upper()
            if new_status != original:
                reason = reason_var.get().strip()
                if not reason:
                    missing_reasons.append((category, index, reason_entry))
                changes.append((category, index, new_status, reason_var, reason_entry))

        if not changes:
            # No changes — just close
            self.grab_release()
            self.destroy()
            return

        # Validate operator name
        operator = self.operator_var.get().strip()
        if not operator:
            messagebox.showwarning(
                "Operator Required",
                "Please enter your name before applying overrides.",
                parent=self,
            )
            self.operator_entry.focus_set()
            return

        # Validate that every changed field has a reason
        if missing_reasons:
            messagebox.showwarning(
                "Reason Required",
                f"{len(missing_reasons)} changed field(s) are missing a reason.\n"
                "Please enter a reason for each overridden field.",
                parent=self,
            )
            # Focus the first missing reason entry
            missing_reasons[0][2].focus_set()
            return

        # Apply each override with its individual reason
        for category, index, new_status, reason_var, _entry in changes:
            reason = reason_var.get().strip()
            self.validation.apply_override(category, index, new_status, operator, reason)

        self.validation.recalculate_overall()

        self.applied = True
        self.override_count = len(changes)
        self.operator_name = operator

        self.grab_release()
        self.destroy()

    def _cancel(self):
        self.grab_release()
        self.destroy()
