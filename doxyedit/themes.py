"""Theme system — color palettes for the entire app.

Each theme maps semantic role names to hex colors.
Vinik24 palette reference: https://lospec.com/palette-list/vinik24
Additional themes ported from StageDirector/Visualizer projects.
"""
from dataclasses import dataclass


@dataclass
class Theme:
    name: str
    # Core surfaces
    bg_deep: str        # deepest background (canvas, scroll areas)
    bg_main: str        # main panels
    bg_raised: str      # toolbars, tabs, elevated surfaces
    bg_input: str       # text inputs, combo boxes
    bg_hover: str       # hover state on buttons/items

    # Accent
    accent: str         # primary accent (selected tab, active states)
    accent_dim: str     # softer accent for borders, subtle highlights
    accent_bright: str  # bright accent for focus rings, active buttons

    # Text
    text_primary: str   # main text
    text_secondary: str # dimmer labels, hints
    text_muted: str     # very dim text, placeholders
    text_on_accent: str # text on accent-colored backgrounds

    # Status bar
    statusbar_bg: str
    statusbar_text: str

    # Borders
    border: str
    border_light: str

    # Selection
    selection_bg: str
    selection_border: str

    # Thumb/grid
    thumb_bg: str       # thumbnail placeholder background

    # Font
    font_size: int = 12       # base font size in px — all other sizes scale from this
    font_family: str = "Segoe UI"

    # Semantic (consistent across themes)
    success: str = "#6eaa78"
    warning: str = "#be955c"
    error: str = "#9a4f50"
    star: str = "#be955c"

    def btn_style(self) -> str:
        """Shared button stylesheet — scales with font_size."""
        f = self.font_size
        pad = max(3, f // 3)
        pad_lg = max(6, f // 2)
        return (f"QPushButton {{ padding: {pad}px {pad_lg}px; font-size: {f}px; }}"
                f"QPushButton:checked {{ background: {self.accent}; color: {self.text_on_accent}; }}")


# ---------------------------------------------------------------------------
# Vinik 24 — the default theme
# Faithful to the Visualizer/StageDirector mapping
# ---------------------------------------------------------------------------

VINIK24 = Theme(
    name="Vinik 24",
    bg_deep="#000000",
    bg_main="#433455",
    bg_raised="#433455",
    bg_input="#332845",
    bg_hover="#5d6872",
    accent="#666092",
    accent_dim="#433455",
    accent_bright="#7ca1c0",
    text_primary="#c5ccb8",
    text_secondary="#9a9a97",
    text_muted="#6f6776",
    text_on_accent="#c5ccb8",
    statusbar_bg="#387080",
    statusbar_text="#c5ccb8",
    border="#666092",
    border_light="#6f6776",
    selection_bg="#666092",
    selection_border="#7ca1c0",
    thumb_bg="#332845",
)

# ---------------------------------------------------------------------------
# Warm Charcoal — warm dark tones (from StageDirector)
# ---------------------------------------------------------------------------

WARM_CHARCOAL = Theme(
    name="Warm Charcoal",
    bg_deep="#100f0e",
    bg_main="#1a1816",
    bg_raised="#22201e",
    bg_input="#2a2724",
    bg_hover="#3a3228",
    accent="#a08040",
    accent_dim="#5a4820",
    accent_bright="#c0a050",
    text_primary="#ccc5b8",
    text_secondary="#9a9488",
    text_muted="#6a6458",
    text_on_accent="#100f0e",
    statusbar_bg="#3a3228",
    statusbar_text="#ccc5b8",
    border="#3a3228",
    border_light="#4a4238",
    selection_bg="#5a4820",
    selection_border="#a08040",
    thumb_bg="#22201e",
)

# ---------------------------------------------------------------------------
# Soot — cool dark purple (from StageDirector)
# ---------------------------------------------------------------------------

SOOT = Theme(
    name="Soot",
    bg_deep="#0c0b0e",
    bg_main="#141218",
    bg_raised="#1a181e",
    bg_input="#201e26",
    bg_hover="#28222e",
    accent="#7868b0",
    accent_dim="#483868",
    accent_bright="#9888d0",
    text_primary="#b8b0c0",
    text_secondary="#8880a0",
    text_muted="#585060",
    text_on_accent="#0c0b0e",
    statusbar_bg="#28222e",
    statusbar_text="#b8b0c0",
    border="#28222e",
    border_light="#383040",
    selection_bg="#483868",
    selection_border="#7868b0",
    thumb_bg="#1a181e",
)

# ---------------------------------------------------------------------------
# Bone — light warm theme (from StageDirector)
# ---------------------------------------------------------------------------

BONE = Theme(
    name="Bone",
    bg_deep="#d8d0c4",
    bg_main="#e8e2d8",
    bg_raised="#ede8e0",
    bg_input="#f4f0e8",
    bg_hover="#d0c8b8",
    accent="#8a6830",
    accent_dim="#c0a878",
    accent_bright="#6a4818",
    text_primary="#302820",
    text_secondary="#605848",
    text_muted="#908878",
    text_on_accent="#f4f0e8",
    statusbar_bg="#3a3228",
    statusbar_text="#ede8e0",
    border="#c0b8a8",
    border_light="#d0c8b8",
    selection_bg="#c0a878",
    selection_border="#8a6830",
    thumb_bg="#ede8e0",
    success="#5a8850",
    warning="#a08040",
    error="#a04838",
    star="#8a6830",
)

# ---------------------------------------------------------------------------
# Milk Glass — light cool theme (from StageDirector)
# ---------------------------------------------------------------------------

MILK_GLASS = Theme(
    name="Milk Glass",
    bg_deep="#d0d8d8",
    bg_main="#e0e8e8",
    bg_raised="#eef0f0",
    bg_input="#f4f8f8",
    bg_hover="#c8d0d0",
    accent="#3a8888",
    accent_dim="#a0c0c0",
    accent_bright="#288080",
    text_primary="#283838",
    text_secondary="#506060",
    text_muted="#889898",
    text_on_accent="#f4f8f8",
    statusbar_bg="#3a8888",
    statusbar_text="#eef0f0",
    border="#b0c0c0",
    border_light="#c8d0d0",
    selection_bg="#a0c0c0",
    selection_border="#3a8888",
    thumb_bg="#eef0f0",
    success="#508060",
    warning="#808040",
    error="#a04848",
    star="#808040",
)

# ---------------------------------------------------------------------------
# Forest — greens from Vinik palette
# ---------------------------------------------------------------------------

FOREST = Theme(
    name="Forest",
    bg_deep="#0a1210",
    bg_main="#1a2820",
    bg_raised="#223828",
    bg_input="#1e3020",
    bg_hover="#2a4030",
    accent="#68aca9",
    accent_dim="#387080",
    accent_bright="#6eaa78",
    text_primary="#c5ccb8",
    text_secondary="#9d9f7f",
    text_muted="#557064",
    text_on_accent="#0a1210",
    statusbar_bg="#387080",
    statusbar_text="#c5ccb8",
    border="#387080",
    border_light="#557064",
    selection_bg="#387080",
    selection_border="#68aca9",
    thumb_bg="#1a2820",
)

# ---------------------------------------------------------------------------
# Dark (classic dark IDE theme)
# ---------------------------------------------------------------------------

DARK = Theme(
    name="Grey",
    bg_deep="#1e1e1e",
    bg_main="#252526",
    bg_raised="#333337",
    bg_input="#2d2d2d",
    bg_hover="#444444",
    accent="#0078d4",
    accent_dim="#094771",
    accent_bright="#0078d4",
    text_primary="#cccccc",
    text_secondary="#888888",
    text_muted="#555555",
    text_on_accent="#ffffff",
    statusbar_bg="#007acc",
    statusbar_text="#ffffff",
    border="#444444",
    border_light="#555555",
    selection_bg="#094771",
    selection_border="#0078d4",
    thumb_bg="#2d2d2d",
)


# All available themes
THEMES: dict[str, Theme] = {
    "vinik24": VINIK24,
    "warm_charcoal": WARM_CHARCOAL,
    "soot": SOOT,
    "bone": BONE,
    "milk_glass": MILK_GLASS,
    "forest": FOREST,
    "dark": DARK,
}

DEFAULT_THEME = "vinik24"


def generate_stylesheet(theme: Theme) -> str:
    """Generate a complete Qt stylesheet from a theme."""
    # --- Design tokens ---
    f = theme.font_size          # base font
    fs = max(8, f - 1)           # small (labels, hints)
    fxs = max(7, f - 2)          # extra small (dim text)
    fl = f + 1                   # large (headers)
    ff = theme.font_family
    cb = max(14, f + 2)          # checkbox indicator
    pad = max(4, f // 3)         # standard padding
    pad_lg = max(6, f // 2)      # large padding
    rad = max(3, f // 4)         # border radius

    return f"""
        * {{ font-family: "{ff}"; font-size: {f}px; }}

        QMainWindow {{ background: {theme.bg_deep}; }}

        QSplitter {{ background: {theme.bg_deep}; }}
        QSplitter::handle {{ background: {theme.border}; }}
        QSplitter::handle:vertical {{ height: 9px; }}
        QSplitter::handle:horizontal {{ width: 8px; }}

        #doxyedit_browser, #doxyedit_tagpanel, #doxyedit_grid,
        #doxyedit_grid_scroll, #doxyedit_grid_scroll > QWidget,
        #doxyedit_tray, #doxyedit_tray QListWidget {{
            background: {theme.bg_deep};
        }}

        QToolBar {{
            background: {theme.bg_raised}; border: none;
            spacing: {pad}px; padding: {pad}px;
        }}
        QToolBar QToolButton {{
            background: {theme.bg_input}; color: {theme.text_primary};
            border: 1px solid {theme.border}; border-radius: {rad}px;
            padding: {pad_lg}px {pad_lg * 2}px; font-size: {f}px;
        }}
        QToolBar QToolButton:hover {{ background: {theme.bg_hover}; font-size: {f}px; }}
        QToolBar QToolButton:checked {{
            background: {theme.accent}; border-color: {theme.accent_bright};
            color: {theme.text_on_accent}; font-size: {f}px;
        }}

        QStatusBar {{
            background: {theme.bg_raised}; color: {theme.text_secondary};
            font-size: {f}px;
        }}

        QMenuBar {{
            background: {theme.bg_raised}; color: {theme.text_secondary};
            font-size: {f}px; padding: {pad // 2}px;
        }}
        QMenuBar::item {{ padding: {pad}px {pad_lg}px; font-size: {f}px; }}
        QMenuBar::item:selected {{ background: {theme.accent_dim}; font-size: {f}px; }}
        QMenu {{
            background: {theme.bg_raised}; color: {theme.text_primary};
            border: 1px solid {theme.border}; font-size: {f}px;
        }}
        QMenu::item {{ padding: {pad_lg}px {pad_lg * 3}px; font-size: {f}px; }}
        QMenu::item:selected, QMenu::item:hover {{
            background: {theme.accent_dim}; color: {theme.text_on_accent};
            font-size: {f}px;
        }}
        QMenu::separator {{ background: {theme.border}; height: 1px; margin: {pad}px {pad_lg}px; }}

        QSplitter::handle {{ background: {theme.border}; width: 7px; }}

        QTabWidget {{ background: {theme.bg_raised}; }}
        QTabWidget::pane {{ border: none; background: {theme.bg_deep}; }}
        QTabWidget > QTabBar {{ background: {theme.bg_raised}; }}
        QTabBar {{ background: {theme.bg_raised}; }}
        QWidget#proj_tab_bar_row {{ background: {theme.bg_raised}; }}
        QTabBar::tab {{
            background: {theme.bg_raised}; color: {theme.text_muted}; border: none;
            padding: {pad_lg}px {pad_lg * 3}px; font-size: {f}px; min-width: 80px;
        }}
        QTabBar::tab:selected {{ background: {theme.bg_deep}; color: {theme.text_primary}; font-size: {f}px; }}
        QTabBar::tab:hover {{ color: {theme.text_secondary}; font-size: {f}px; }}
        QTabBar::scroller {{ background: {theme.bg_raised}; }}

        QScrollArea {{ border: none; background: {theme.bg_deep}; }}
        QScrollBar:vertical {{
            background: {theme.bg_main}; width: 10px; border: none;
        }}
        QScrollBar::handle:vertical {{
            background: {theme.border}; border-radius: 4px; min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {theme.border_light}; }}
        QScrollBar:horizontal {{
            background: {theme.bg_main}; height: 10px; border: none;
        }}
        QScrollBar::handle:horizontal {{
            background: {theme.border}; border-radius: 4px; min-width: 30px;
        }}
        QScrollBar::handle:horizontal:hover {{ background: {theme.border_light}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}

        QLineEdit {{
            background: {theme.bg_input}; color: {theme.text_primary};
            border: 1px solid {theme.border}; border-radius: {rad}px;
            padding: {pad}px {pad_lg}px; font-size: {f}px;
            selection-background-color: {theme.selection_bg};
        }}
        QLineEdit:focus {{ border-color: {theme.accent_bright}; }}

        QComboBox {{
            background: {theme.bg_input}; color: {theme.text_primary};
            border: 1px solid {theme.border}; border-radius: {rad}px;
            padding: {pad}px {pad_lg}px; font-size: {f}px;
        }}
        QComboBox QAbstractItemView {{
            background: {theme.bg_raised}; color: {theme.text_primary};
            selection-background-color: {theme.selection_bg};
            border: 1px solid {theme.border}; font-size: {f}px;
        }}

        QTextEdit, QPlainTextEdit, QTextBrowser {{
            background: {theme.bg_input}; color: {theme.text_primary};
            border: 1px solid {theme.border}; border-radius: {rad}px;
            padding: {pad}px; font-size: {f}px;
            selection-background-color: {theme.selection_bg};
        }}

        QCheckBox {{ color: {theme.text_secondary}; font-size: {f}px; }}
        QCheckBox::indicator {{
            width: {cb}px; height: {cb}px; border: 1px solid {theme.border};
            border-radius: {rad}px; background: {theme.bg_input};
        }}
        QCheckBox::indicator:checked {{
            background: {theme.accent}; border-color: {theme.accent_bright};
        }}

        QTreeWidget {{
            background: {theme.bg_deep}; color: {theme.text_primary};
            border: none; font-size: {f}px;
        }}
        QTreeWidget::item {{ padding: {pad}px; }}
        QTreeWidget::item:selected {{ background: {theme.accent_dim}; }}
        QHeaderView::section {{
            background: {theme.bg_raised}; color: {theme.text_muted};
            border: none; padding: {pad}px {pad_lg}px; font-size: {fs}px;
        }}

        QPushButton {{
            background: {theme.bg_input}; color: {theme.text_primary};
            border: 1px solid {theme.border}; border-radius: {rad}px;
            padding: {pad_lg}px {pad_lg * 2}px; font-size: {f}px;
        }}
        QPushButton:hover {{ background: {theme.bg_hover}; font-size: {f}px; }}
        QPushButton:pressed {{ background: {theme.accent_dim}; }}
        QPushButton:checked {{
            background: {theme.accent}; border-color: {theme.accent_bright};
            color: {theme.text_on_accent};
        }}

        QProgressBar {{
            background: {theme.bg_input}; border: 1px solid {theme.border};
            border-radius: {rad}px; font-size: {fs}px;
            color: {theme.text_primary}; text-align: center;
        }}
        QProgressBar::chunk {{
            background: {theme.accent}; border-radius: {rad}px;
        }}

        QLabel {{ color: {theme.text_primary}; }}
        QLabel[role="muted"] {{ color: {theme.text_muted}; }}
        QLabel[role="secondary"] {{ color: {theme.text_secondary}; }}
        QLabel[role="accent"] {{ color: {theme.accent_bright}; font-weight: bold; }}

        /* ── New panel backgrounds ──────────────────────────────────────── */
        QWidget#platform_panel, QWidget#checklist_panel,
        QWidget#health_panel, QWidget#stats_panel {{
            background: {theme.bg_deep};
        }}
        QTextBrowser#project_info_panel, QTextBrowser#project_notes_preview {{
            background: {theme.bg_deep};
            border: none;
            padding-left: 20px;
        }}
        QPlainTextEdit#project_notes_tab {{
            background: {theme.bg_deep};
            color: {theme.text_primary};
            border: none;
            font-family: Consolas, monospace;
            font-size: {f}px;
            padding-left: 24px;
        }}
        QWidget#health_toolbar {{
            background: {theme.bg_raised};
        }}

        /* Scroll area viewports inside new panels inherit bg_deep */
        QWidget#platform_panel QScrollArea,
        QWidget#platform_panel QScrollArea > QWidget,
        QWidget#platform_panel QScrollArea QWidget,
        QWidget#checklist_panel QScrollArea,
        QWidget#checklist_panel QScrollArea > QWidget,
        QWidget#checklist_panel QScrollArea QWidget,
        QWidget#health_panel QScrollArea,
        QWidget#health_panel QScrollArea > QWidget,
        QWidget#health_panel QScrollArea QWidget,
        QWidget#stats_panel QScrollArea,
        QWidget#stats_panel QScrollArea > QWidget,
        QWidget#stats_panel QScrollArea QWidget {{
            background: {theme.bg_deep};
        }}

        /* Platform cards */
        QFrame#platform_card {{
            border: 1px solid {theme.border};
            border-radius: 6px;
            background: {theme.bg_raised};
        }}
        QFrame#card_divider {{
            background: {theme.border}; max-height: 1px; margin: 4px 0;
        }}

        /* Size badge in slot rows */
        QLabel#size_badge {{
            color: {theme.text_muted};
            background: {theme.bg_input};
            border-radius: 3px;
            padding: 0 5px;
        }}

        /* Stats overview cards */
        QFrame#stat_card {{
            border: 1px solid {theme.border};
            border-radius: 6px;
            background: {theme.bg_raised};
            padding: 4px;
        }}

        /* Image hive */
        QWidget#hive_container {{
            background: {theme.bg_main};
            border-top: 1px solid {theme.border};
        }}
        QWidget#hive_container QScrollArea,
        QWidget#hive_container QScrollArea > QWidget {{
            background: {theme.bg_main};
        }}
        QLabel#hive_thumb {{
            background: {theme.thumb_bg};
            border: 1px solid {theme.border};
            border-radius: 4px;
        }}

        QDialog {{
            background: {theme.bg_main}; color: {theme.text_primary};
        }}
        QInputDialog, QMessageBox {{
            background: {theme.bg_main};
        }}
        QInputDialog QLabel, QMessageBox QLabel {{
            color: {theme.text_primary};
        }}
        QInputDialog QLineEdit {{
            background: {theme.bg_input}; color: {theme.text_primary};
            border: 1px solid {theme.border}; border-radius: 4px;
            padding: 5px 10px;
        }}
    """
