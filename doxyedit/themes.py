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
    # Social post status
    post_draft: str = "#888888"
    post_queued: str = "#e8a87c"
    post_posted: str = "#6eaa78"
    post_failed: str = "#cc4444"
    post_partial: str = "#ccaa55"
    # Scrollbar
    scrollbar_track: str = ""              # track background (very low contrast with bg)
    scrollbar_handle: str = ""             # the draggable part (defaults to accent_dim)
    scrollbar_handle_hover: str = ""       # handle on hover (defaults to accent)
    # Gantt
    gantt_grid: str = ""          # defaults to border
    gantt_today: str = ""         # defaults to accent
    gantt_gap: str = ""           # defaults to error
    gantt_stagger: str = ""       # defaults to accent_dim
    # Timeline
    timeline_gap: str = "#664444"
    timeline_day_header: str = ""  # defaults to text_secondary

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
    post_draft="#6f6776",
    post_queued="#c28d75",
    post_posted="#6eaa78",
    post_failed="#9a4f50",
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
    post_draft="#6a6458",
    post_queued="#c0a050",
    post_posted="#6eaa78",
    post_failed="#a04838",
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
    post_draft="#585060",
    post_queued="#9888d0",
    post_posted="#6eaa78",
    post_failed="#9a4f50",
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
    post_draft="#908878",
    post_queued="#c0a050",
    post_posted="#5a8850",
    post_failed="#a04838",
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
    post_draft="#889898",
    post_queued="#3a8888",
    post_posted="#508060",
    post_failed="#a04848",
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
    post_draft="#557064",
    post_queued="#68aca9",
    post_posted="#6eaa78",
    post_failed="#9a4f50",
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
    post_draft="#666666",
    post_queued="#0078d4",
    post_posted="#6eaa78",
    post_failed="#cc4444",
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


# ---------------------------------------------------------------------------
# Neon — high-contrast dark with electric green/magenta (from focus neon)
# ---------------------------------------------------------------------------

NEON = Theme(
    name="Neon",
    bg_deep="#0a0a0a",
    bg_main="#121212",
    bg_raised="#1a1a1a",
    bg_input="#161616",
    bg_hover="#252525",
    accent="#00e676",
    accent_dim="#004d25",
    accent_bright="#ff1744",
    text_primary="#e0e0e0",
    text_secondary="#888888",
    text_muted="#505050",
    text_on_accent="#000000",
    statusbar_bg="#00c853",
    statusbar_text="#000000",
    border="#2a2a2a",
    border_light="#3a3a3a",
    selection_bg="#004d25",
    selection_border="#00e676",
    thumb_bg="#161616",
    success="#00e676",
    warning="#ffea00",
    error="#ff1744",
    star="#ffea00",
    post_draft="#505050",
    post_queued="#00e676",
    post_posted="#00c853",
    post_failed="#ff1744",
)

# ---------------------------------------------------------------------------
# Ember — warm dark amber/orange (from focus ember)
# ---------------------------------------------------------------------------

EMBER = Theme(
    name="Ember",
    bg_deep="#0e0a08",
    bg_main="#1a1210",
    bg_raised="#241a14",
    bg_input="#1e1410",
    bg_hover="#322418",
    accent="#e68a30",
    accent_dim="#5a3818",
    accent_bright="#ffa040",
    text_primary="#d8c8b0",
    text_secondary="#9a8870",
    text_muted="#6a5a48",
    text_on_accent="#0e0a08",
    statusbar_bg="#c87020",
    statusbar_text="#d8c8b0",
    border="#3a2818",
    border_light="#4a3828",
    selection_bg="#5a3818",
    selection_border="#e68a30",
    thumb_bg="#1a1210",
    post_draft="#6a5a48",
    post_queued="#e68a30",
    post_posted="#6eaa78",
    post_failed="#cc4444",
)

# ---------------------------------------------------------------------------
# Midnight — deep blue-black (from focus midnight/navy)
# ---------------------------------------------------------------------------

MIDNIGHT = Theme(
    name="Midnight",
    bg_deep="#080a10",
    bg_main="#0e1220",
    bg_raised="#141a2a",
    bg_input="#101828",
    bg_hover="#1a2438",
    accent="#4488cc",
    accent_dim="#1a3050",
    accent_bright="#66aaee",
    text_primary="#b0c0d8",
    text_secondary="#7088a0",
    text_muted="#405060",
    text_on_accent="#080a10",
    statusbar_bg="#2060a0",
    statusbar_text="#b0c0d8",
    border="#1a2438",
    border_light="#283848",
    selection_bg="#1a3050",
    selection_border="#4488cc",
    thumb_bg="#0e1220",
    post_draft="#405060",
    post_queued="#4488cc",
    post_posted="#6eaa78",
    post_failed="#cc4444",
)

# ---------------------------------------------------------------------------
# Dawn — light warm pink/peach (from focus dawn)
# ---------------------------------------------------------------------------

DAWN = Theme(
    name="Dawn",
    bg_deep="#e8d8d0",
    bg_main="#f4e8e0",
    bg_raised="#f8f0ea",
    bg_input="#fcf4ee",
    bg_hover="#e0d0c4",
    accent="#c06048",
    accent_dim="#d8a898",
    accent_bright="#a04030",
    text_primary="#3a2820",
    text_secondary="#7a5848",
    text_muted="#a08878",
    text_on_accent="#fcf4ee",
    statusbar_bg="#b05040",
    statusbar_text="#f8f0ea",
    border="#d0c0b4",
    border_light="#ddd0c4",
    selection_bg="#d8a898",
    selection_border="#c06048",
    thumb_bg="#f4e8e0",
    success="#608850",
    warning="#b08030",
    error="#b04040",
    star="#c06048",
    post_draft="#a08878",
    post_queued="#c06048",
    post_posted="#608850",
    post_failed="#b04040",
)

# ---------------------------------------------------------------------------
# Citrus — light green/yellow (from focus citrus)
# ---------------------------------------------------------------------------

CITRUS = Theme(
    name="Citrus",
    bg_deep="#d8dcc8",
    bg_main="#e8ecd8",
    bg_raised="#f0f4e4",
    bg_input="#f4f8ea",
    bg_hover="#ccd4b8",
    accent="#5a8828",
    accent_dim="#b0c890",
    accent_bright="#408018",
    text_primary="#283020",
    text_secondary="#586848",
    text_muted="#8a9878",
    text_on_accent="#f0f4e4",
    statusbar_bg="#4a7820",
    statusbar_text="#f0f4e4",
    border="#b8c4a0",
    border_light="#c8d4b0",
    selection_bg="#b0c890",
    selection_border="#5a8828",
    thumb_bg="#e8ecd8",
    success="#5a8828",
    warning="#a09020",
    error="#a04838",
    star="#a09020",
    post_draft="#8a9878",
    post_queued="#5a8828",
    post_posted="#408018",
    post_failed="#a04838",
)

# ---------------------------------------------------------------------------
# Candy — light pink/magenta (from focus candy)
# ---------------------------------------------------------------------------

CANDY = Theme(
    name="Candy",
    bg_deep="#e4d0dc",
    bg_main="#f0e0ea",
    bg_raised="#f6eaf0",
    bg_input="#faf0f4",
    bg_hover="#dcc4d0",
    accent="#c04888",
    accent_dim="#d8a0c0",
    accent_bright="#a83870",
    text_primary="#3a2030",
    text_secondary="#785068",
    text_muted="#a08090",
    text_on_accent="#f6eaf0",
    statusbar_bg="#a83870",
    statusbar_text="#f6eaf0",
    border="#ccb4c4",
    border_light="#d8c4d0",
    selection_bg="#d8a0c0",
    selection_border="#c04888",
    thumb_bg="#f0e0ea",
    success="#58884a",
    warning="#a08030",
    error="#b83848",
    star="#c04888",
    post_draft="#a07888",
    post_queued="#c87898",
    post_posted="#58884a",
    post_failed="#b83848",
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
    "neon": NEON,
    "ember": EMBER,
    "midnight": MIDNIGHT,
    "dawn": DAWN,
    "citrus": CITRUS,
    "candy": CANDY,
}

DEFAULT_THEME = "soot"


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
    # Scrollbar tokens
    _sb_track = theme.scrollbar_track or theme.bg_hover
    _sb_handle = theme.scrollbar_handle or theme.accent_dim
    _sb_hover = theme.scrollbar_handle_hover or theme.accent

    return f"""
        * {{ font-family: "{ff}"; font-size: {f}px; }}

        QMainWindow {{ background: {theme.bg_deep}; }}

        QSplitter {{ background: {theme.bg_deep}; }}
        QSplitter::handle {{ background: {theme.border}; }}
        QSplitter::handle:vertical {{ height: 9px; }}
        QSplitter::handle:horizontal {{ width: 8px; }}
        QSplitter::handle:hover {{ background: {theme.accent_dim}; }}

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
            border: 1px solid {theme.border}; border-radius: {rad}px;
            padding: {pad}px 0; font-size: {f}px;
        }}
        QMenu::item {{
            padding: {pad}px {pad_lg * 3}px; font-size: {f}px;
        }}
        QMenu::item:selected, QMenu::item:hover {{
            background: {theme.accent_dim}; color: {theme.text_on_accent};
        }}
        QMenu::item:disabled {{
            color: {theme.text_muted};
        }}
        QMenu::separator {{
            background: {theme.border}; height: 1px;
            margin: {pad}px {pad_lg}px;
        }}


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
            background: {_sb_track}; width: 14px; border: none;
        }}
        QScrollBar::handle:vertical {{
            background: {_sb_handle}; border-radius: 4px; min-height: 30px; margin: 2px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {_sb_hover}; }}
        QScrollBar:horizontal {{
            background: {_sb_track}; height: 14px; border: none;
        }}
        QScrollBar::handle:horizontal {{
            background: {_sb_handle}; border-radius: 4px; min-width: 30px; margin: 2px;
        }}
        QScrollBar::handle:horizontal:hover {{ background: {_sb_hover}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

        QLineEdit {{
            background: {theme.bg_input}; color: {theme.text_primary};
            border: 1px solid {theme.border}; border-radius: {rad}px;
            padding: {pad}px {pad_lg}px; font-size: {f}px;
            selection-background-color: {theme.selection_bg};
        }}
        QLineEdit:focus {{ border-color: {theme.accent_bright}; }}
        QLineEdit QToolButton {{
            border: none; padding: 0px; margin: 2px;
            background: transparent;
            min-width: 16px; min-height: 16px;
        }}

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
        QWidget#platform_panel QSplitter,
        QWidget#platform_panel QStackedWidget {{
            background: {theme.bg_deep};
        }}
        QTextBrowser#project_info_panel {{
            background: {theme.bg_deep};
            border: none;
        }}
        QTextBrowser#project_notes_preview {{
            background: {theme.bg_deep};
            border: none;
        }}
        QPlainTextEdit#project_notes_tab {{
            background: {theme.bg_deep};
            color: {theme.text_primary};
            selection-background-color: {theme.selection_bg};
            selection-color: {theme.text_primary};
            border: none;
            font-family: Consolas, monospace;
            font-size: {f}px;
            padding-left: 100px;
            padding-top: 16px;
        }}
        QWidget#notes_editor_wrapper {{
            background: {theme.bg_deep};
        }}
        QWidget#health_toolbar {{
            background: {theme.bg_raised};
        }}
        QToolBar#tab_toolbar {{
            background: {theme.bg_raised};
            border: none;
            padding: 0px 2px;
            spacing: 0px;
        }}
        QWidget#tab_toolbar_spacer {{
            background: transparent;
        }}
        QPushButton#menubar_tab_btn {{
            background: transparent;
            color: {theme.text_secondary};
            border: none;
            border-bottom: 2px solid transparent;
            padding: 3px 10px;
            font-size: {f}px;
        }}
        QPushButton#menubar_tab_btn:hover {{
            color: {theme.text_primary};
            background: {theme.accent_dim};
        }}
        QPushButton#menubar_tab_btn:checked {{
            color: {theme.text_primary};
            border-bottom: 2px solid {theme.accent_bright};
        }}
        QWidget#folder_section, QWidget#folder_container,
        QScrollArea#folder_scroll, QScrollArea#folder_scroll > QWidget,
        QScrollArea#folder_scroll QWidget {{
            background: {theme.bg_deep};
        }}
        QPushButton#root_folder_header {{
            background: {theme.bg_main};
            color: {theme.accent_bright};
            text-align: left;
            padding: 5px 8px;
            font-size: {f}px;
            font-weight: bold;
            border: none;
            border-bottom: 1px solid {theme.border};
        }}
        QPushButton#root_folder_header:hover {{
            background: {theme.accent_dim};
            color: {theme.text_primary};
        }}
        QPushButton#folder_section_header {{
            background: {theme.bg_raised};
            color: {theme.text_secondary};
            text-align: left;
            padding: 3px 8px;
            font-weight: bold;
            font-size: {f}px;
            border: none;
            border-bottom: 1px solid {theme.border};
        }}
        QPushButton#folder_section_header:hover {{
            background: {theme.accent_dim};
            color: {theme.text_primary};
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
        QLabel#stats_section_label {{
            padding-top: 4px;
        }}
        QProgressBar#stats_bar {{
            background: rgba(255,255,255,0.06);
            border: none;
            border-radius: 4px;
        }}

        /* Image hive */
        QWidget#hive_container,
        QWidget#hive_container QWidget {{
            background: {theme.bg_main};
        }}
        QWidget#hive_container {{
            border-top: 1px solid {theme.border};
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
        QDateEdit {{
            background: {theme.bg_input}; color: {theme.text_primary};
            border: 1px solid {theme.border}; border-radius: 4px;
            padding: 3px 8px;
        }}
        QCalendarWidget {{
            background: {theme.bg_main};
            color: {theme.text_primary};
        }}
        QCalendarWidget QWidget {{
            background: {theme.bg_main};
            color: {theme.text_primary};
        }}
        QCalendarWidget QWidget#qt_calendar_navigationbar {{
            background: {theme.bg_raised};
        }}
        QCalendarWidget QAbstractItemView {{
            background: {theme.bg_deep}; color: {theme.text_primary};
            selection-background-color: {theme.selection_bg};
            selection-color: {theme.text_on_accent};
            alternate-background-color: {theme.bg_main};
            gridline-color: {theme.border};
        }}
        QCalendarWidget QAbstractItemView:enabled {{
            color: {theme.text_primary};
        }}
        QCalendarWidget QAbstractItemView:disabled {{
            color: {theme.text_muted};
        }}
        QCalendarWidget QToolButton {{
            color: {theme.text_primary}; background: {theme.bg_raised};
            border: none; padding: 4px 8px;
            icon-size: 16px;
        }}
        QCalendarWidget QToolButton:hover {{
            background: {theme.bg_hover};
        }}
        QCalendarWidget QToolButton#qt_calendar_prevmonth,
        QCalendarWidget QToolButton#qt_calendar_nextmonth {{
            color: {theme.text_primary};
            background: {theme.bg_raised};
            qproperty-icon: none;
            border: 1px solid {theme.border};
            border-radius: {rad}px;
            min-width: 24px;
        }}
        QCalendarWidget QToolButton#qt_calendar_prevmonth {{
            qproperty-text: "<";
        }}
        QCalendarWidget QToolButton#qt_calendar_nextmonth {{
            qproperty-text: ">";
        }}
        QCalendarWidget QMenu {{
            background: {theme.bg_raised}; color: {theme.text_primary};
        }}
        QCalendarWidget QSpinBox {{
            background: {theme.bg_input}; color: {theme.text_primary};
            border: 1px solid {theme.border};
        }}

        /* ── New panels (v2.2) ─────────────────────────────────────────── */
        QWidget#kanban_panel {{
            background: {theme.bg_deep};
        }}
        QWidget#kanban_panel QLabel {{
            color: {theme.text_primary};
            font-size: {f}px;
        }}
        QFrame[objectName="kanban_card"] {{
            background: {theme.bg_raised};
            border: 1px solid {theme.border};
            border-radius: 4px;
        }}
        QFrame[objectName="kanban_card"]:hover {{
            background: {theme.bg_hover};
        }}
        QWidget[objectName="kanban_column"] {{
            background: {theme.bg_deep};
            border-radius: 6px;
        }}
        QWidget[objectName="kanban_column"] QScrollArea {{
            background: transparent;
            border: none;
        }}

        QWidget#info_panel {{
            background: {theme.bg_main};
        }}
        QWidget#info_panel QLabel {{
            color: {theme.text_primary};
        }}
        QWidget#info_panel QPushButton {{
            background: {theme.bg_input};
            color: {theme.text_primary};
            border: 1px solid {theme.border};
            border-radius: 3px;
            padding: 1px 6px;
            font-size: {fs}px;
        }}
        QWidget#info_panel QPushButton:hover {{
            background: {theme.bg_hover};
        }}
        QWidget#info_panel QTextEdit {{
            background: {theme.bg_input};
            color: {theme.text_primary};
            border: 1px solid {theme.border};
            border-radius: 3px;
            padding: 4px;
            font-size: {f}px;
        }}
        QWidget#info_panel QLineEdit {{
            background: {theme.bg_input};
            color: {theme.text_primary};
            border: 1px solid {theme.border};
            border-radius: 3px;
            padding: 1px 4px;
            font-size: {fs}px;
        }}
        QWidget#info_panel QScrollArea,
        QWidget#info_panel QScrollArea > QWidget,
        QWidget#info_panel QScrollArea QWidget {{
            background: {theme.bg_main};
            border: none;
        }}
        QWidget#info_panel QFrame {{
            color: {theme.border_light};
        }}

        QWidget#file_browser_panel {{
            background: {theme.bg_main};
            font-size: {f}px;
        }}
        QWidget#file_browser_panel QTreeView {{
            background: {theme.bg_deep};
            color: {theme.text_primary};
            border: none;
            font-size: {f}px;
        }}
        QWidget#file_browser_panel QTreeView::item {{
            padding: 2px 0;
        }}
        QWidget#file_browser_panel QTreeView::item:selected {{
            background: {theme.selection_bg};
        }}
        QWidget#file_browser_panel QTreeView::item:hover {{
            background: {theme.bg_hover};
        }}
        QWidget#file_browser_panel QPushButton {{
            background: {theme.bg_raised};
            color: {theme.text_primary};
            border: 1px solid {theme.border};
            padding: 2px 8px;
            font-size: {fs}px;
        }}
        QWidget#file_browser_panel QPushButton:hover {{
            background: {theme.bg_hover};
        }}

        QWidget#preview_pane {{
            background: {theme.bg_deep};
        }}
        QWidget#preview_pane QLabel {{
            color: {theme.text_secondary};
        }}
        QWidget#preview_pane QGraphicsView {{
            background: {theme.bg_deep};
            border: none;
        }}
        QLabel#preview_info {{
            color: {theme.text_secondary};
        }}

        /* ── Health panel ──────────────────────────────────────────────── */
        QPushButton#health_action_btn {{
            padding: {pad}px {pad_lg * 2}px;
        }}
        QLabel#health_warning {{
            background: rgba(255,165,0,0.15);
            color: {theme.warning};
            padding: {pad_lg * 2}px;
            border: 1px solid rgba(255,165,0,0.3);
            border-radius: 6px;
        }}
        QLabel#health_ok {{
            color: {theme.success};
            padding: {pad_lg * 2}px;
            font-weight: bold;
        }}
        QLabel#health_section_header {{
            font-weight: bold;
        }}
        QLabel#health_section_header[severity="error"] {{ color: {theme.error}; }}
        QLabel#health_section_header[severity="warning"] {{ color: {theme.warning}; }}
        QLabel#health_section_header[severity="info"] {{ color: {theme.accent_bright}; }}
        QWidget#health_row {{
            border-radius: {rad}px; padding: 1px;
        }}
        QWidget#health_row:hover {{
            background: {theme.bg_hover};
        }}
        QLabel#health_dot[severity="error"] {{ color: {theme.error}; }}
        QLabel#health_dot[severity="warning"] {{ color: {theme.warning}; }}
        QLabel#health_dot[severity="info"] {{ color: {theme.accent_bright}; }}
        QLabel#health_hint {{
            color: {theme.accent_bright};
            font-style: italic;
        }}
        QLabel[severity="success"] {{ color: {theme.success}; }}
        QLabel[severity="error"] {{ color: {theme.error}; }}
        QLabel[severity="warning"] {{ color: {theme.warning}; }}

        /* ── Checklist panel ───────────────────────────────────────────── */
        QPushButton#checklist_action_btn {{
            padding: {pad}px {pad_lg * 2}px;
        }}
        QProgressBar#checklist_progress {{
            background: {theme.bg_hover};
            border: none;
            border-radius: {rad}px;
        }}
        QProgressBar#checklist_progress::chunk {{
            background: {theme.success};
            border-radius: {rad}px;
        }}
        QPushButton#checklist_del_btn {{
            background: transparent;
            border: none;
            color: rgba(180,100,100,0.5);
        }}
        QPushButton#checklist_del_btn:hover {{
            color: rgba(220,80,80,0.9);
        }}
        QCheckBox[checked_state="done"] {{
            color: {theme.text_muted};
            text-decoration: line-through;
        }}

        /* ── Platform panel ────────────────────────────────────────────── */
        QLabel#platform_dots {{
            color: {theme.text_muted};
            letter-spacing: 1px;
        }}
        QLabel#platform_count {{
            color: {theme.text_muted};
            margin-left: 6px;
        }}
        QLabel#slot_empty_required {{
            color: {theme.error};
            font-style: italic;
        }}
        QLabel#slot_empty {{
            color: {theme.text_muted};
            font-style: italic;
        }}
        QPushButton#status_btn {{
            background: transparent;
            border: 1px solid {theme.text_muted};
            border-radius: {rad}px;
            padding: 0 {pad}px;
        }}
        QPushButton#status_btn:hover {{
            background: {theme.bg_hover};
        }}
        QPushButton#status_btn:disabled {{
            color: {theme.text_muted};
            border-color: {theme.text_muted};
        }}
        QPushButton#status_btn[status="pending"] {{
            color: {theme.text_muted};
            border-color: {theme.text_muted};
        }}
        QPushButton#status_btn[status="ready"] {{
            color: {theme.warning};
            border-color: {theme.warning};
        }}
        QPushButton#status_btn[status="posted"] {{
            color: {theme.success};
            border-color: {theme.success};
        }}
        QPushButton#status_btn[status="skip"] {{
            color: {theme.text_muted};
            border-color: {theme.text_muted};
        }}
        QLabel#hive_status_dot[status="pending"] {{ color: {theme.text_muted}; }}
        QLabel#hive_status_dot[status="ready"] {{ color: {theme.warning}; }}
        QLabel#hive_status_dot[status="posted"] {{ color: {theme.success}; }}
        QLabel#hive_status_dot[status="skip"] {{ color: {theme.text_muted}; }}

        /* Dashboard */
        QProgressBar#dash_progress {{
            background: {theme.bg_hover};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
            text-align: center;
            color: {theme.text_secondary};
            font-size: {fxs}px;
        }}
        QProgressBar#dash_progress::chunk {{
            background: {theme.success};
            border-radius: {max(1, rad - 1)}px;
        }}
        QLabel#dash_thumb {{
            background: {theme.bg_input};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
        }}
        QLabel#dash_thumb[empty="true"] {{
            color: {theme.text_muted};
        }}
        QLabel#dash_slot_label {{
            font-size: {fxs}px;
            color: {theme.text_secondary};
        }}
        QLabel#dash_multi {{
            font-size: {fxs}px;
            color: {theme.text_muted};
        }}

        /* ── Hover preview (tooltip popup) ─────────────────────────────── */
        QWidget#hover_preview {{
            background: {theme.bg_deep};
            border: 2px solid {theme.border_light};
            border-radius: 6px;
            padding: {pad}px;
        }}
        QLabel#hover_preview_info {{
            color: {theme.text_secondary};
            font-size: {fs}px;
        }}

        /* ── Preview dialog ────────────────────────────────────────────── */
        QDialog#preview_dialog {{
            background: {theme.bg_deep};
        }}
        QDialog#preview_dialog QGraphicsView {{
            border: none;
        }}
        QLabel#preview_hint {{
            color: {theme.text_muted};
        }}

        /* ── Tag panel ─────────────────────────────────────────────────── */
        QPushButton#tag_eye_btn {{
            background: transparent;
            border: none;
            font-size: {fl + 3}px;
            padding: 0;
            color: {theme.success};
        }}
        QPushButton#tag_eye_btn:!checked {{
            color: {theme.text_muted};
        }}
        QLabel#tag_hint {{
            color: {theme.text_muted};
        }}
        QLabel#tag_count {{
            color: {theme.text_muted};
            min-width: 24px;
        }}
        QLabel#tagpanel_header {{
            color: {theme.text_muted};
            padding-bottom: {pad}px;
        }}
        QLabel#tagpanel_hint {{
            color: {theme.text_muted};
            font-style: italic;
        }}
        QLabel#tagpanel_dim {{
            color: {theme.text_secondary};
        }}
        QPushButton#tagpanel_action_btn {{
            padding: {pad}px {pad_lg}px;
        }}
        QPushButton#tag_section_btn {{
            color: {theme.text_secondary};
            padding: 2px {pad}px;
            background: rgba(128,128,128,0.07);
            border: none;
            border-radius: {rad}px;
            text-align: left;
            font-weight: bold;
        }}
        QPushButton#tag_section_btn:hover {{
            color: {theme.text_primary};
            background: rgba(128,128,128,0.15);
        }}
        QWidget#tag_row {{
            background: transparent;
        }}
        QScrollArea#tag_scroll, QScrollArea#tag_scroll > QWidget > QWidget {{
            border: none;
            background: transparent;
        }}
        QFrame#tag_separator {{
            color: {theme.border_light};
        }}
        QLabel#tagpanel_header[state="empty"] {{
            color: {theme.text_muted};
            padding-bottom: {pad}px;
        }}
        QLabel#tagpanel_header[state="active"] {{
            padding-bottom: {pad}px;
        }}

        /* ── Work tray ─────────────────────────────────────────────────── */
        QPushButton#tray_handle {{
            background: rgba(128,128,128,0.15);
            border: none;
            border-radius: 0;
            color: {theme.text_muted};
        }}
        QPushButton#tray_handle:hover {{
            background: rgba(128,128,128,0.3);
        }}
        QPushButton#tray_small_btn {{
            padding: 2px;
        }}
        QPushButton#tray_action_btn {{
            padding: 2px {pad_lg}px;
        }}
        QTabBar#tray_tab_bar::tab {{
            padding: 3px 10px;
            margin-right: 2px;
        }}
        QTabBar#tray_tab_bar::tab:selected {{
            font-weight: bold;
        }}
        QLabel#tray_count {{
            color: {theme.text_muted};
        }}
        QListWidget#tray_list {{
            border: none;
        }}
        QListWidget[drag_over="true"] {{
            border: 2px solid {theme.accent};
        }}

        /* ── Browser tag bar ───────────────────────────────────────────── */
        QWidget#tag_bar_frame {{
            border-bottom: 1px solid {theme.border_light};
        }}
        QPushButton#add_tag_btn {{
            background: transparent;
            color: {theme.text_muted};
            border: 1px dashed {theme.text_muted};
            border-radius: 50%;
            font-weight: bold;
        }}
        QPushButton#add_tag_btn:hover {{
            color: {theme.text_primary};
            border-color: {theme.text_primary};
        }}

        /* ── Timeline stream ──────────────────────────────────────────── */
        QWidget#timeline_stream {{
            background: {theme.bg_deep};
            color: {theme.text_primary};
        }}
        QWidget#timeline_stream QLabel {{
            color: {theme.text_primary};
        }}
        QWidget#timeline_stream QScrollArea,
        QWidget#timeline_stream QScrollArea > QWidget,
        QWidget#timeline_stream QScrollArea QWidget {{
            background: {theme.bg_deep};
            color: {theme.text_primary};
        }}
        QLabel#timeline_summary {{
            color: {theme.text_secondary};
            padding: 2px {pad}px;
        }}
        QLabel#timeline_caption {{
            color: {theme.text_muted};
        }}
        QLabel#timeline_links {{
            color: {theme.text_muted};
            font-size: {fs}px;
        }}
        QLabel#timeline_day_header {{
            color: {theme.timeline_day_header or theme.text_secondary};
            font-size: {fl}px;
            font-weight: bold;
            padding: {pad}px 0;
        }}
        QFrame#timeline_post_card {{
            background: {theme.bg_raised};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
            padding: {pad}px;
        }}
        QFrame#timeline_post_card:hover {{
            border-color: {theme.accent_dim};
        }}
        QLabel#post_badge_draft,
        QLabel#post_badge_queued,
        QLabel#post_badge_posted,
        QLabel#post_badge_failed,
        QLabel#post_badge_partial {{
            border-radius: {rad}px;
            padding: 2px {pad}px;
            font-size: {fs}px;
            font-weight: bold;
        }}
        QLabel#post_badge_draft {{
            background: {theme.bg_input};
            border: 1px solid {theme.border};
            color: {theme.text_secondary};
        }}
        QLabel#post_badge_queued {{
            background: {theme.post_queued}40;
            color: {theme.post_queued};
            border: 1px solid {theme.post_queued}60;
        }}
        QLabel#post_badge_posted {{
            background: {theme.post_posted}40;
            color: {theme.post_posted};
            border: 1px solid {theme.post_posted}60;
        }}
        QLabel#post_badge_failed {{
            background: {theme.post_failed}40;
            color: {theme.post_failed};
            border: 1px solid {theme.post_failed}60;
        }}
        QLabel#post_badge_partial {{
            background: {theme.post_partial}40;
            color: {theme.post_partial};
            border: 1px solid {theme.post_partial}60;
        }}
        QFrame#timeline_gap {{
            border: 1px dashed {theme.timeline_gap};
            border-radius: {rad}px;
            padding: {pad}px;
            background: {theme.timeline_gap}15;
        }}
        QLabel#timeline_thumb_placeholder {{
            background: {theme.bg_input};
            border: 1px dashed {theme.border};
            border-radius: {rad}px;
            color: {theme.text_muted};
        }}
        QLabel#platform_badge {{
            background: {theme.accent_dim};
            color: {theme.text_on_accent};
            border-radius: {max(rad - 1, 2)}px;
            padding: 1px {pad}px;
            font-size: {fxs}px;
        }}

        /* ── Engagement panel ─────────────────────────────────────── */
        QFrame#engagement_panel {{
            background: {theme.bg_raised};
            border: 1px solid {theme.accent_dim};
            border-radius: {rad}px;
            padding: {pad}px;
        }}
        QFrame#engagement_panel QLabel {{
            color: {theme.text_primary};
        }}
        QFrame#engagement_row {{
            background: {theme.bg_main};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
        }}
        QPushButton#engagement_open_btn {{
            background: {theme.accent_dim};
            color: {theme.text_on_accent};
            border: none;
            border-radius: {rad}px;
            padding: {pad}px {pad_lg}px;
        }}
        QPushButton#engagement_open_btn:hover {{
            background: {theme.accent};
        }}
        QPushButton#engagement_done_btn {{
            background: {theme.bg_input};
            color: {theme.post_posted};
            border: 1px solid {theme.post_posted};
            border-radius: {rad}px;
            padding: {pad}px {pad_lg}px;
        }}
        QPushButton#engagement_done_btn:hover {{
            background: {theme.post_posted};
            color: {theme.text_on_accent};
        }}
        QPushButton#engagement_snooze_btn {{
            background: {theme.bg_input};
            color: {theme.warning};
            border: 1px solid {theme.warning};
            border-radius: {rad}px;
            padding: {pad}px {pad_lg}px;
        }}
        QPushButton#engagement_snooze_btn:hover {{
            background: {theme.warning};
            color: {theme.text_on_accent};
        }}

        /* ── Post composer (dialog + docked) ──────────────────────────── */
        QDialog#post_composer,
        QDialog#post_composer QWidget,
        QDialog#post_composer QScrollArea,
        QDialog#post_composer QScrollArea > QWidget,
        QWidget#post_composer_widget,
        QWidget#post_composer_widget QWidget,
        QWidget#post_composer_widget QScrollArea,
        QWidget#post_composer_widget QScrollArea > QWidget,
        QWidget#composer_dock {{
            background: {theme.bg_main};
            color: {theme.text_primary};
        }}
        QDialog#post_composer QGroupBox,
        QWidget#post_composer_widget QGroupBox {{
            color: {theme.text_primary};
            background: {theme.bg_main};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
            margin-top: {f}px;
            padding-top: {f}px;
        }}
        QDialog#post_composer QGroupBox::title,
        QWidget#post_composer_widget QGroupBox::title {{
            color: {theme.text_secondary};
            subcontrol-origin: margin;
            padding: 0 {pad}px;
        }}
        QDialog#post_composer QLineEdit,
        QWidget#post_composer_widget QLineEdit {{
            background: {theme.bg_input};
            color: {theme.text_primary};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
            padding: {pad}px;
        }}
        QDialog#post_composer QTextEdit,
        QWidget#post_composer_widget QTextEdit {{
            background: {theme.bg_input};
            color: {theme.text_primary};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
            padding: {pad}px;
        }}
        QDialog#post_composer QDateTimeEdit,
        QWidget#post_composer_widget QDateTimeEdit {{
            background: {theme.bg_input};
            color: {theme.text_primary};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
            padding: {pad}px;
        }}
        QDialog#post_composer QCheckBox,
        QWidget#post_composer_widget QCheckBox {{
            color: {theme.text_primary};
            spacing: {pad}px;
        }}
        QDialog#post_composer QLabel,
        QWidget#post_composer_widget QLabel {{
            color: {theme.text_primary};
        }}
        QLabel#composer_prep_header {{
            font-weight: bold;
        }}
        QDialog#post_composer QPushButton,
        QWidget#post_composer_widget QPushButton {{
            background: {theme.bg_raised};
            color: {theme.text_primary};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
            padding: {pad}px {pad_lg}px;
        }}
        QDialog#post_composer QPushButton:hover,
        QWidget#post_composer_widget QPushButton:hover {{
            background: {theme.bg_hover};
            border-color: {theme.accent_dim};
        }}

        /* ── Calendar pane ───────────────────────────────────────────── */
        QWidget#calendar_pane {{
            background: {theme.bg_main};
        }}
        QLabel#calendar_header {{
            color: {theme.text_primary};
            font-size: {fl}px;
            font-weight: bold;
        }}
        QPushButton#calendar_nav_btn {{
            background: {theme.bg_raised};
            color: {theme.text_primary};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
        }}
        QPushButton#calendar_nav_btn:hover {{
            background: {theme.bg_hover};
            border-color: {theme.accent_dim};
        }}
        QPushButton#calendar_today_btn {{
            background: {theme.bg_raised};
            color: {theme.text_primary};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
            padding: 2px {pad}px;
            font-size: {fs}px;
        }}
        QPushButton#calendar_today_btn:hover {{
            background: {theme.bg_hover};
            border-color: {theme.accent_dim};
        }}
        QLabel#calendar_jst_clock {{
            color: {theme.text_secondary};
            font-size: {fxs}px;
            padding: 2px 0;
        }}
        QLabel#calendar_dow_header {{
            color: {theme.text_muted};
            font-size: {fxs}px;
            font-weight: bold;
        }}
        QFrame#calendar_day_normal {{
            background: {theme.bg_raised};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
        }}
        QFrame#calendar_day_normal:hover {{
            border-color: {theme.accent_dim};
        }}
        QFrame#calendar_day_today {{
            background: {theme.bg_raised};
            border: 2px solid {theme.accent};
            border-radius: {rad}px;
        }}
        QFrame#calendar_day_selected {{
            background: {theme.accent_dim};
            border: 2px solid {theme.accent_bright};
            border-radius: {rad}px;
        }}
        QFrame#calendar_day_past {{
            background: {theme.bg_deep};
            border: 1px solid {theme.border_light};
            border-radius: {rad}px;
        }}
        QFrame#calendar_day_past:hover {{
            border-color: {theme.accent_dim};
        }}
        QFrame#calendar_day_past QLabel#calendar_day_number {{
            color: {theme.text_muted};
        }}
        QFrame#calendar_day_other_month {{
            background: {theme.bg_deep};
            border: 1px solid transparent;
            border-radius: {rad}px;
        }}
        QLabel#calendar_day_number {{
            color: {theme.text_primary};
            font-size: {fs}px;
        }}
        QFrame#calendar_day_other_month QLabel#calendar_day_number {{
            color: {theme.text_muted};
        }}
        QLabel#calendar_day_count {{
            color: {theme.text_muted};
            font-size: {fxs}px;
        }}
        QLabel#calendar_dot {{
            border-radius: 3px;
            border: none;
        }}
        QLabel#calendar_dot[dot_status="posted"] {{
            background: {theme.post_posted};
        }}
        QLabel#calendar_dot[dot_status="queued"] {{
            background: {theme.post_queued};
        }}
        QLabel#calendar_dot[dot_status="draft"] {{
            background: {theme.post_draft};
        }}
        QLabel#calendar_dot[dot_status="gap"] {{
            background: {theme.error};
        }}
        QLabel#calendar_dot[dot_status="xproject"] {{
            background: {theme.text_muted};
        }}

        /* ── Studio editor ─────────────────────────────────────────── */
        QWidget#studio_props_row QPushButton {{
            padding: 2px 4px; min-width: 24px;
        }}

        /* ── Gantt panel ────────────────────────────────────────────── */
        QWidget#gantt_panel {{
            background: {theme.bg_deep};
        }}
        QWidget#gantt_toolbar {{
            background: {theme.bg_raised};
            color: {theme.text_primary};
        }}
        QWidget#gantt_toolbar QLabel {{
            color: {theme.text_secondary};
        }}
        QWidget#gantt_toolbar QDateEdit {{
            background: {theme.bg_input};
            color: {theme.text_primary};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
            padding: {pad}px;
        }}
        QWidget#gantt_toolbar QSlider::groove:horizontal {{
            background: {theme.bg_input};
            height: 4px;
            border-radius: 2px;
        }}
        QWidget#gantt_toolbar QSlider::handle:horizontal {{
            background: {theme.accent};
            width: 12px;
            height: 12px;
            margin: -4px 0;
            border-radius: 6px;
        }}
        QGraphicsView#gantt_view {{
            background: {theme.bg_deep};
            border: none;
        }}
        QScrollArea#gantt_label_area {{
            background: {theme.bg_main};
            border: none;
        }}
        QScrollArea#gantt_label_area > QWidget,
        QWidget#gantt_label_container {{
            background: {theme.bg_main};
        }}
        QLabel#gantt_row_label {{
            background: {theme.bg_main};
            color: {theme.text_secondary};
            font-size: {fs}px;
            padding-right: {pad}px;
        }}
        QPushButton#gantt_today_btn {{
            background: {theme.accent_dim};
            color: {theme.text_on_accent};
            border: 1px solid {theme.accent};
            border-radius: {rad}px;
            padding: {pad}px {pad_lg}px;
        }}
        QPushButton#gantt_today_btn:hover {{
            background: {theme.accent};
        }}

        /* ── Composer release chain ─────────────────────────────────── */
        QWidget#composer_chain_step_row {{
            background: {theme.bg_raised};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
            padding: 2px;
        }}
        QLabel#composer_chain_step_label {{
            color: {theme.text_secondary};
            font-weight: bold;
            font-size: {fs}px;
        }}
        QLabel#composer_chain_anchor_label {{
            color: {theme.text_muted};
            font-size: {fxs}px;
            font-style: italic;
        }}
        QPushButton#composer_add_step_btn {{
            background: {theme.bg_input};
            color: {theme.text_primary};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
            padding: {pad}px {pad_lg}px;
        }}
        QPushButton#composer_add_step_btn:hover {{
            background: {theme.bg_hover};
            border-color: {theme.accent_dim};
        }}
        QPushButton#composer_chain_remove_btn {{
            background: transparent;
            border: none;
            color: {theme.text_muted};
        }}
        QPushButton#composer_chain_remove_btn:hover {{
            color: {theme.error};
        }}

        /* ── Timeline asset name ─────────────────────────────────────── */
        QLabel#timeline_asset_name {{
            font-weight: bold;
        }}

        /* ── Composer platform label ────────────────────────────────── */
        QLabel#composer_platform_label {{
            font-weight: bold;
        }}

        /* ── Composer timezone clock ─────────────────────────────────── */
        QLabel#composer_tz_clock {{
            color: {theme.text_secondary};
            padding: 2px 0;
        }}

        /* ── Claude progress dialog ──────────────────────────────────── */
        QProgressDialog#claude_progress {{
            background: {theme.bg_main};
            color: {theme.text_primary};
        }}
        QProgressDialog#claude_progress QLabel {{
            color: {theme.text_primary};
            padding: {pad}px;
        }}
        QProgressDialog#claude_progress QProgressBar {{
            background: {theme.bg_input};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
            height: 8px;
        }}
        QProgressDialog#claude_progress QProgressBar::chunk {{
            background: {theme.accent};
            border-radius: {rad}px;
        }}

        /* ── Composer disabled platform ──────────────────────────────── */
        QCheckBox#composer_platform_disabled {{
            color: {theme.text_muted};
        }}
        QLabel#composer_sub_platform_label {{
            color: {theme.text_secondary};
            font-size: {fs}px;
            font-weight: bold;
            padding-top: {pad}px;
        }}
        QCheckBox#composer_sub_platform_check {{
            color: {theme.text_primary};
        }}

        /* ── Composer left panel ─────────────────────────────────────── */
        QWidget#composer_preview_panel {{
            background: {theme.bg_main};
        }}
        QLabel#composer_main_preview {{
            background: {theme.bg_deep};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
        }}
        QLabel#composer_section_header {{
            color: {theme.text_primary};
            font-weight: bold;
            font-size: {fs}px;
        }}
        QPushButton#composer_preview_mode_btn {{
            background: {theme.bg_input};
            color: {theme.text_secondary};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
            padding: 1px {pad}px;
            font-size: {fxs}px;
        }}
        QPushButton#composer_preview_mode_btn:checked {{
            background: {theme.accent_dim};
            color: {theme.text_on_accent};
            border-color: {theme.accent};
        }}
        QFrame#composer_nsfw_frame,
        QFrame#composer_crop_frame {{
            background: {theme.bg_raised};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
        }}
        QPushButton#composer_nsfw_toggle {{
            background: {theme.bg_input};
            color: {theme.text_primary};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
            padding: {pad}px {pad_lg}px;
        }}
        QPushButton#composer_nsfw_toggle:checked {{
            background: {theme.warning};
            color: {theme.text_on_accent};
            border-color: {theme.warning};
        }}
        QLabel#composer_censor_info {{
            color: {theme.text_secondary};
            font-size: {fs}px;
        }}
        QLabel#composer_crop_icon {{
            font-size: {fl}px;
        }}
        QLabel#composer_crop_label {{
            color: {theme.text_secondary};
            font-size: {fs}px;
        }}
        QLabel#composer_order_thumb {{
            background: {theme.bg_input};
            border: 1px solid {theme.border};
            border-radius: {rad}px;
        }}

        /* ── Composer thumb cells ────────────────────────────────────── */
        QFrame#composer_thumb_cell {{
            background: transparent;
            border: none;
        }}
        QLabel#composer_thumb_order {{
            color: {theme.text_secondary};
            font-size: {fxs}px;
            font-weight: bold;
        }}

        /* ── Strategy generate button ────────────────────────────────── */
        QPushButton#strategy_generate_btn {{
            background: {theme.accent_dim};
            color: {theme.text_on_accent};
            border: 1px solid {theme.accent};
            border-radius: {rad}px;
            padding: {pad}px {pad_lg}px;
            font-weight: bold;
        }}
        QPushButton#strategy_generate_btn:hover {{
            background: {theme.accent};
        }}
    """
