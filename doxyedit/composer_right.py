"""composer_right.py -- Right column of the post composer.

Contains strategy notes, captions, links, schedule, reply templates,
and platform checkboxes.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTextEdit, QPushButton, QCheckBox, QDateTimeEdit, QFrame,
    QScrollArea, QGroupBox, QStackedWidget, QTextBrowser,
    QSizePolicy, QComboBox, QSpinBox, QSplitter, QRadioButton,
    QButtonGroup, QProgressDialog, QApplication, QMessageBox,
    QDialog, QFileDialog, QFormLayout, QDialogButtonBox,
    QTabWidget, QListWidget, QListWidgetItem,
)
from PySide6.QtCore import Qt, QDateTime, Signal, QSettings, QThread, QTimer
from doxyedit.browser import FlowLayout
from doxyedit.models import Project, SocialPost, SUB_PLATFORMS
from doxyedit.themes import THEMES, DEFAULT_THEME
from doxyedit.claude_modal import show_claude_modal


# ─── Chrome profile utilities ─────────────────────────────────────

_chrome_profile_cache: list[tuple[str, str]] | None = None
_chrome_cache_time: float = 0

def list_chrome_profiles() -> list[tuple[str, str]]:
    """Return (dir_name, display_name) for each Chrome profile. Cached for 30s."""
    global _chrome_profile_cache, _chrome_cache_time
    now = time.time()
    if _chrome_profile_cache is not None and (now - _chrome_cache_time) < 30:
        return _chrome_profile_cache

    user_data = os.path.expandvars(r"%LocalAppData%\Google\Chrome\User Data")
    profiles = []
    if os.path.isdir(user_data):
        for name in os.listdir(user_data):
            prefs = os.path.join(user_data, name, "Preferences")
            if os.path.isfile(prefs):
                try:
                    with open(prefs, encoding="utf-8") as f:
                        data = json.load(f)
                    display = data.get("profile", {}).get("name", name)
                    profiles.append((name, display))
                except Exception:
                    profiles.append((name, name))

    _chrome_profile_cache = profiles
    _chrome_cache_time = now
    return profiles


def open_chrome_with_profile(url: str, profile_dir: str = "Default"):
    """Launch Chrome with a specific profile."""
    import subprocess, sys, os
    chrome_paths = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    chrome = None
    for p in chrome_paths:
        if os.path.exists(p):
            chrome = p
            break
    if not chrome:
        import webbrowser
        webbrowser.open(url)
        return
    cmd = [chrome, f"--profile-directory={profile_dir}", url]
    if sys.platform == "win32":
        subprocess.Popen(cmd, creationflags=0x08000000)
    else:
        subprocess.Popen(cmd)


# ─── Content panel ─────────────────────────────────────────────────

class ContentPanel(QWidget):
    """Right column: platforms, strategy, captions, links, schedule, replies."""

    # ── Layout ratios (change here to rescale all composer-right widgets) ──
    EDIT_BUTTON_WIDTH_RATIO = 3.3      # identity "Edit" button
    STEP_LABEL_WIDTH_RATIO = 4.0       # release chain "Step N:" label
    REMOVE_BUTTON_WIDTH_RATIO = 2.0    # release chain "×" remove button
    CAPTION_MAX_HEIGHT_RATIO = 10.0    # default caption box max height
    REPLY_MAX_HEIGHT_RATIO = 6.7       # reply template box max height
    PLATFORM_CAPTION_MAX_HEIGHT_RATIO = 8.3  # per-platform caption max height
    AI_PROGRESS_MIN_WIDTH_RATIO = 26.7  # AI strategy progress dialog min width
    PROFILE_LIST_MAX_HEIGHT_RATIO = 10.0  # chrome profile list max height
    IDENTITY_DIALOG_MIN_WIDTH_RATIO = 41.7   # identity editor dialog
    IDENTITY_DIALOG_MIN_HEIGHT_RATIO = 33.3  # identity editor dialog
    CAPTION_KEY_MAX_WIDTH_RATIO = 8.3  # release chain caption key max width

    platforms_changed = Signal(list)

    def __init__(self, project: Project, project_dir: str = "", parent=None,
                 extra_projects: list | None = None):
        super().__init__(parent)
        self.setObjectName("composer_content_panel")
        self._project = project
        self._project_dir = project_dir
        self._extra_projects: list = extra_projects or []
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _cb = max(14, int(_f * 1.17))

        self._platform_checks: dict[str, QCheckBox] = {}
        self._platform_captions: dict[str, QTextEdit] = {}
        self._local_strategy_cache: str = ""
        self._ai_strategy_cache: str = ""
        self._strategy_view: str = ""  # "local" or "ai"
        self._strategy_raw: str = ""

        self._connected: list[dict] = []
        self._acct_label: str = ""
        self._release_steps: list[dict] = []

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)

        _pad = max(4, _f // 3)
        _pad_lg = max(6, _f // 2)

        root = QVBoxLayout(self)
        root.setSpacing(_pad)
        root.setContentsMargins(0, 0, 0, 0)

        # --- Identity (top of composer — controls category + platform defaults) ---
        identity_row = QHBoxLayout()
        identity_row.setSpacing(_pad)
        id_label = QLabel("Identity:")
        id_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self._identity_combo = QComboBox()
        self._identity_combo.setObjectName("composer_identity_combo")
        self._identity_combo.addItem("(None)", "")
        for name in self._project.identities:
            self._identity_combo.addItem(name, name)
        for xproj in self._extra_projects:
            xname = getattr(xproj, "name", "") or ""
            if xproj.identities:
                self._identity_combo.insertSeparator(self._identity_combo.count())
                for iname in xproj.identities:
                    label = f"{iname}  [{xname}]" if xname else iname
                    # Store as tuple encoded in UserRole: "xproject::<proj_name>::<iname>"
                    self._identity_combo.addItem(label, f"xproject::{xname}::{iname}")
        self._identity_combo.currentIndexChanged.connect(
            lambda _: self._on_identity_changed(self._identity_combo.currentData())
        )
        edit_id_btn = QPushButton("Edit")
        edit_id_btn.setObjectName("composer_edit_identity_btn")
        edit_id_btn.setFixedWidth(int(_f * self.EDIT_BUTTON_WIDTH_RATIO))
        edit_id_btn.clicked.connect(self._edit_identity)
        identity_row.addWidget(id_label)
        identity_row.addWidget(self._identity_combo, 1)
        identity_row.addWidget(edit_id_btn)
        root.addLayout(identity_row)

        # --- Platforms: category dropdown → account checkboxes ---
        from doxyedit.oneup import get_categories, get_connected_platforms, get_active_account_label
        project_dir = self._project_dir or "."
        self._categories = get_categories(project_dir)
        self._connected = get_connected_platforms(project_dir)
        self._acct_label = get_active_account_label(project_dir)

        platforms_box = QGroupBox("Platforms")
        platforms_box.setObjectName("composer_platforms_box")
        platforms_layout = QVBoxLayout(platforms_box)
        platforms_layout.setSpacing(_pad)

        # Category dropdown
        if self._categories:
            cat_row = QHBoxLayout()
            cat_label = QLabel("Category:")
            cat_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            self._category_combo = QComboBox()
            self._category_combo.setObjectName("composer_category_combo")
            for cat in self._categories:
                self._category_combo.addItem(cat["name"], cat["id"])
            self._category_combo.currentIndexChanged.connect(self._on_category_changed)
            cat_row.addWidget(cat_label)
            cat_row.addWidget(self._category_combo, 1)
            platforms_layout.addLayout(cat_row)
        else:
            self._category_combo = None

        # Container widget for account checkboxes (rebuilt on category change)
        self._accounts_container = QWidget()
        self._accounts_container.setObjectName("composer_accounts_container")
        self._accounts_flow = FlowLayout(hspacing=8, vspacing=4)
        self._accounts_container.setLayout(self._accounts_flow)
        platforms_layout.addWidget(self._accounts_container)

        # Populate with first category (or flat connected list)
        self._rebuild_account_checkboxes()

        # --- Subscription platforms (Patreon, Fanbox, etc.) ---
        self._sub_platform_checks: dict[str, QCheckBox] = {}
        sub_flow = FlowLayout(hspacing=8, vspacing=4)
        sub_container = QWidget()
        sub_container.setLayout(sub_flow)

        for sub in SUB_PLATFORMS.values():
            cb = QCheckBox(sub.name)
            cb.setProperty("platform_id", sub.id)
            cb.setObjectName("composer_sub_platform_check")
            cb.setToolTip(f"{sub.monetization_type} — {sub.locale.upper()} — quick-post (clipboard + browser)")
            cb.clicked.connect(self._on_platform_toggled)
            self._sub_platform_checks[sub.id] = cb
            sub_flow.addWidget(cb)

        # Subscription (collapsible)
        sub_toggle = QPushButton("Subscription \u25bc")
        sub_toggle.setObjectName("composer_section_toggle")
        sub_toggle.setCheckable(True)
        sub_toggle.setChecked(False)
        sub_container.setVisible(False)
        sub_toggle.clicked.connect(lambda c: (
            sub_container.setVisible(c),
            sub_toggle.setText("Subscription \u25b2" if c else "Subscription \u25bc"),
        ))
        platforms_layout.addWidget(sub_toggle)
        platforms_layout.addWidget(sub_container)

        # --- Manual social platforms (collapsible) ---
        _MANUAL_PLATFORMS = [
            ("bluesky", "Bluesky"),
            ("pixiv", "Pixiv"),
            ("instagram", "Instagram"),
            ("tiktok", "TikTok"),
            ("tumblr", "Tumblr"),
            ("threads", "Threads"),
            ("mastodon", "Mastodon"),
            ("newgrounds", "Newgrounds"),
        ]
        self._manual_platform_checks: dict[str, QCheckBox] = {}
        manual_flow = FlowLayout(hspacing=8, vspacing=4)
        manual_container = QWidget()
        manual_container.setLayout(manual_flow)

        for pid, name in _MANUAL_PLATFORMS:
            cb = QCheckBox(name)
            cb.setProperty("platform_id", pid)
            cb.setObjectName("composer_manual_platform_check")
            cb.setToolTip(f"Manual posting — track in schedule, post yourself")
            cb.clicked.connect(self._on_platform_toggled)
            self._manual_platform_checks[pid] = cb
            manual_flow.addWidget(cb)

        manual_toggle = QPushButton("Social (manual) \u25bc")
        manual_toggle.setObjectName("composer_section_toggle")
        manual_toggle.setCheckable(True)
        manual_toggle.setChecked(False)
        manual_container.setVisible(False)
        manual_toggle.clicked.connect(lambda c: (
            manual_container.setVisible(c),
            manual_toggle.setText("Social (manual) \u25b2" if c else "Social (manual) \u25bc"),
        ))
        platforms_layout.addWidget(manual_toggle)
        platforms_layout.addWidget(manual_container)

        # Censor mode (collapsible)
        censor_toggle = QPushButton("Censor Mode \u25bc")
        censor_toggle.setObjectName("composer_section_toggle")
        censor_toggle.setCheckable(True)
        censor_toggle.setChecked(False)
        self._censor_container = QWidget()
        censor_lay = QVBoxLayout(self._censor_container)
        censor_lay.setContentsMargins(0, 0, 0, 0)
        censor_lay.setSpacing(max(2, _pad // 2))
        self._censor_container.setVisible(False)
        censor_toggle.clicked.connect(lambda c: (
            self._censor_container.setVisible(c),
            censor_toggle.setText("Censor Mode \u25b2" if c else "Censor Mode \u25bc"),
        ))
        platforms_layout.addWidget(censor_toggle)

        self._censor_group = QButtonGroup(self)
        self._censor_auto = QRadioButton("Auto (platform default)")
        self._censor_uncensored = QRadioButton("Uncensored everywhere")
        self._censor_custom = QRadioButton("Custom per-platform")
        self._censor_auto.setChecked(True)
        self._censor_group.addButton(self._censor_auto, 0)
        self._censor_group.addButton(self._censor_uncensored, 1)
        self._censor_group.addButton(self._censor_custom, 2)
        censor_lay.addWidget(self._censor_auto)
        censor_lay.addWidget(self._censor_uncensored)
        censor_lay.addWidget(self._censor_custom)
        platforms_layout.addWidget(self._censor_container)

        root.addWidget(platforms_box)

        # --- Splitter: strategy (top) / rest (bottom, scrollable) ---
        self._content_split = QSplitter(Qt.Orientation.Vertical)
        self._content_split.setObjectName("content_panel_split")

        # -- Strategy Notes --
        strategy_box = QGroupBox("Strategy Notes")
        strategy_layout = QVBoxLayout(strategy_box)
        strategy_btn_row = QHBoxLayout()
        self._strategy_generate_btn = QPushButton("Generate Strategy")
        self._strategy_generate_btn.setObjectName("strategy_generate_btn")
        self._strategy_generate_btn.setToolTip(
            "Local analysis — tags, posting history, calendar gaps, brand identity")
        self._strategy_generate_btn.clicked.connect(self._generate_local_strategy)
        strategy_btn_row.addWidget(self._strategy_generate_btn)

        self._ai_strategy_btn = QPushButton("AI Strategy")
        self._ai_strategy_btn.setObjectName("strategy_generate_btn")
        self._ai_strategy_btn.setToolTip(
            "Claude analyzes the actual image + full context — real strategic insight")
        self._ai_strategy_btn.clicked.connect(self._generate_ai_strategy)
        strategy_btn_row.addWidget(self._ai_strategy_btn)

        self._apply_strategy_btn = QPushButton("Apply")
        self._apply_strategy_btn.setObjectName("strategy_generate_btn")
        self._apply_strategy_btn.setToolTip(
            "Extract captions, links, schedule, reply templates from strategy into post fields")
        self._apply_strategy_btn.clicked.connect(self._apply_strategy)
        strategy_btn_row.addWidget(self._apply_strategy_btn)

        self._strategy_edit_btn = QPushButton("Preview")
        self._strategy_edit_btn.setObjectName("strategy_generate_btn")
        self._strategy_edit_btn.setCheckable(True)
        self._strategy_edit_btn.setToolTip("Toggle between rendered and raw markdown")
        self._strategy_edit_btn.clicked.connect(self._toggle_strategy_edit)
        strategy_btn_row.addWidget(self._strategy_edit_btn)
        strategy_btn_row.addStretch()
        strategy_layout.addLayout(strategy_btn_row)

        # Stacked: raw edit (default, index 0) / rendered preview (index 1)
        self._strategy_stack = QStackedWidget()

        self._strategy_edit = QTextEdit()
        self._strategy_edit.setPlaceholderText("Strategy notes — raw markdown")
        self._strategy_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._strategy_edit.customContextMenuRequested.connect(self._strategy_context_menu)
        self._strategy_stack.addWidget(self._strategy_edit)  # index 0 = raw edit

        self._strategy_browser = QTextBrowser()
        self._strategy_browser.setObjectName("strategy_browser")
        self._strategy_browser.setOpenExternalLinks(True)
        self._strategy_stack.addWidget(self._strategy_browser)  # index 1 = rendered preview

        strategy_layout.addWidget(self._strategy_stack, 1)
        self._content_split.addWidget(strategy_box)

        # -- Scrollable bottom: caption, links, schedule, replies --
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(_pad_lg + _pad)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll_area.setWidget(container)
        self._content_split.addWidget(scroll_area)

        # Default splitter sizes
        self._content_split.setSizes([250, 350])
        self._content_split.setStretchFactor(0, 1)
        self._content_split.setStretchFactor(1, 1)

        root.addWidget(self._content_split, 1)

        # --- Caption ---
        caption_box = QGroupBox("Caption")
        caption_layout = QVBoxLayout(caption_box)
        self._caption_edit = QTextEdit()
        self._caption_edit.setMaximumHeight(int(_f * self.CAPTION_MAX_HEIGHT_RATIO))
        self._caption_edit.setPlaceholderText("Default caption for all platforms")
        self._caption_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._caption_edit.customContextMenuRequested.connect(
            lambda pos: self._claude_context_menu(self._caption_edit, pos))
        caption_layout.addWidget(self._caption_edit)

        self._per_platform_toggle = QPushButton("Per-platform captions \u25bc")
        self._per_platform_toggle.setCheckable(True)
        self._per_platform_toggle.setChecked(False)
        self._per_platform_toggle.clicked.connect(self._toggle_per_platform)
        caption_layout.addWidget(self._per_platform_toggle)

        self._per_platform_container = QWidget()
        self._pp_layout = QVBoxLayout(self._per_platform_container)
        self._pp_layout.setSpacing(_pad)
        self._pp_layout.setContentsMargins(0, 0, 0, 0)
        self._rebuild_per_platform_captions()

        self._per_platform_container.setVisible(False)
        caption_layout.addWidget(self._per_platform_container)
        layout.addWidget(caption_box)

        # --- Links ---
        links_box = QGroupBox("Links")
        links_layout = QVBoxLayout(links_box)
        self._links_edit = QLineEdit()
        self._links_edit.setPlaceholderText("URL")
        links_layout.addWidget(self._links_edit)
        # Published URLs - populated from post.published_urls via
        # set_post. Read-only rich-text label with openExternalLinks
        # so the per-platform live URLs (captured by the userscript
        # feedback backchannel) are clickable right from the composer.
        self._published_urls_label = QLabel()
        self._published_urls_label.setTextFormat(Qt.TextFormat.RichText)
        self._published_urls_label.setOpenExternalLinks(True)
        self._published_urls_label.setWordWrap(True)
        self._published_urls_label.setVisible(False)
        self._published_urls_label.setObjectName("composer_published_urls")
        links_layout.addWidget(self._published_urls_label)
        layout.addWidget(links_box)

        # Schedule (hidden — left panel is primary, this is the data source)
        self._schedule_edit = QDateTimeEdit()
        self._schedule_edit.setCalendarPopup(True)
        self._schedule_edit.setDisplayFormat("yyyy-MM-dd hh:mm AP")
        tomorrow = datetime.now() + timedelta(days=1)
        self._schedule_edit.setDateTime(
            QDateTime(tomorrow.year, tomorrow.month, tomorrow.day,
                      tomorrow.hour, tomorrow.minute, 0)
        )
        self._schedule_edit.setVisible(False)
        self._tz_label = QLabel()
        self._tz_label.setVisible(False)

        # --- Release Chain ---
        chain_box = QGroupBox("Release Chain")
        chain_box.setObjectName("composer_release_chain_box")
        chain_layout = QVBoxLayout(chain_box)

        chain_btn_row = QHBoxLayout()
        self._chain_template_combo = QComboBox()
        self._chain_template_combo.setObjectName("composer_chain_template_combo")
        self._chain_template_combo.addItem("Load Template...")
        for idx, tmpl in enumerate(self._project.release_templates):
            label = tmpl.get("name", f"Template {idx + 1}")
            self._chain_template_combo.addItem(label, idx)
        self._chain_template_combo.currentIndexChanged.connect(
            lambda i: self._load_release_template(i)
        )
        if not self._project.release_templates:
            self._chain_template_combo.setVisible(False)
        chain_btn_row.addWidget(self._chain_template_combo)

        self._add_step_btn = QPushButton("+ Add Step")
        self._add_step_btn.setObjectName("composer_add_step_btn")
        self._add_step_btn.clicked.connect(self._add_release_step)
        chain_btn_row.addWidget(self._add_step_btn)
        chain_btn_row.addStretch()
        chain_layout.addLayout(chain_btn_row)

        self._chain_steps_container = QWidget()
        self._chain_steps_container.setObjectName("composer_chain_steps")
        self._chain_steps_layout = QVBoxLayout(self._chain_steps_container)
        self._chain_steps_layout.setSpacing(_pad)
        self._chain_steps_layout.setContentsMargins(0, 0, 0, 0)
        chain_layout.addWidget(self._chain_steps_container)

        layout.addWidget(chain_box)

        # --- Reply Templates ---
        reply_box = QGroupBox("Reply Templates")
        reply_layout = QVBoxLayout(reply_box)
        self._reply_edit = QTextEdit()
        self._reply_edit.setMaximumHeight(int(_f * self.REPLY_MAX_HEIGHT_RATIO))
        self._reply_edit.setPlaceholderText("One reply per line")
        self._reply_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._reply_edit.customContextMenuRequested.connect(
            lambda pos: self._claude_context_menu(self._reply_edit, pos))
        reply_layout.addWidget(self._reply_edit)
        layout.addWidget(reply_box)

        layout.addStretch()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_post(self, post: SocialPost, connected_platforms: list[dict] | None = None) -> None:
        """Pre-fill all fields from an existing post."""
        if post is None:
            return

        # Restore category dropdown (rebuilds checkboxes for that category)
        if post.category_id and self._category_combo is not None:
            for i in range(self._category_combo.count()):
                if str(self._category_combo.itemData(i)) == str(post.category_id):
                    self._category_combo.setCurrentIndex(i)
                    break

        # Platforms (OneUp accounts)
        for plat, cb in self._platform_checks.items():
            cb.setChecked(plat in post.platforms)
        # Subscription platforms
        for plat, cb in self._sub_platform_checks.items():
            cb.setChecked(plat in post.platforms)
        # Manual social platforms
        if hasattr(self, '_manual_platform_checks'):
            for plat, cb in self._manual_platform_checks.items():
                cb.setChecked(plat in post.platforms)

        # Captions
        self._caption_edit.setPlainText(post.caption_default)
        # Cache the post's per-platform captions so the toggle
        # label can count overrides even while the section is
        # collapsed and _platform_captions is empty.
        self._pp_caption_cache = {
            k: v for k, v in (post.captions or {}).items() if v}
        has_per_platform = bool(post.captions)
        if has_per_platform:
            self._per_platform_toggle.setChecked(True)
            self._per_platform_container.setVisible(True)
        for plat, te in self._platform_captions.items():
            te.setPlainText(post.captions.get(plat, ""))
        self._refresh_pp_toggle_label()

        # Links
        if post.links:
            self._links_edit.setText(post.links[0])

        # Published URLs (populated by the backchannel when a
        # post lands on a platform). Show them as clickable anchors
        # grouped by platform so the user can verify the live post
        # from the composer without hunting through the timeline.
        urls = getattr(post, "published_urls", {}) or {}
        if urls:
            theme_id = QSettings("DoxyEdit", "DoxyEdit").value("theme", DEFAULT_THEME)
            warning_color = THEMES.get(theme_id, THEMES[DEFAULT_THEME]).warning
            lines = []
            for plat, url in sorted(urls.items()):
                if not url:
                    continue
                status = (getattr(post, "platform_status", {}) or {}).get(plat, "")
                mark = (f' <b style="color:{warning_color};">[UNVERIFIED]</b>'
                        if status == "posted_unverified" else "")
                lines.append(f'<b>{plat}</b>: <a href="{url}">{url}</a>{mark}')
            if lines:
                self._published_urls_label.setText("<br>".join(lines))
                self._published_urls_label.setVisible(True)
            else:
                self._published_urls_label.setVisible(False)
        else:
            self._published_urls_label.setVisible(False)
            self._published_urls_label.clear()

        # Schedule
        if post.scheduled_time:
            try:
                dt = datetime.fromisoformat(post.scheduled_time)
                self._schedule_edit.setDateTime(
                    QDateTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, 0)
                )
            except (ValueError, TypeError):
                pass

        # Reply templates
        if post.reply_templates:
            self._reply_edit.setPlainText("\n".join(post.reply_templates))

        # Identity
        if post.collection:
            idx = self._identity_combo.findData(post.collection)
            if idx >= 0:
                self._identity_combo.setCurrentIndex(idx)

        # Release chain
        if post.release_chain:
            self._release_steps = [s.to_dict() for s in post.release_chain]
            self._rebuild_chain_ui()

        # Strategy notes
        if post.strategy_notes:
            self._set_strategy_text(post.strategy_notes)
            self._ai_strategy_cache = post.strategy_notes
            self._strategy_view = "ai"
            self._update_strategy_btn_labels()

        # Censor mode
        if hasattr(post, 'censor_mode') and hasattr(self, '_censor_auto'):
            if post.censor_mode == "uncensored":
                self._censor_uncensored.setChecked(True)
            elif post.censor_mode == "custom":
                self._censor_custom.setChecked(True)
            else:
                self._censor_auto.setChecked(True)

    def set_default_platforms(self, defaults: list[str]) -> None:
        """Check the default platforms (used for new posts)."""
        for plat, cb in self._platform_checks.items():
            cb.setChecked(plat in defaults)
        for plat, cb in self._sub_platform_checks.items():
            cb.setChecked(plat in defaults)
        if hasattr(self, '_manual_platform_checks'):
            for plat, cb in self._manual_platform_checks.items():
                cb.setChecked(plat in defaults)

    def get_post_data(self) -> dict:
        """Return all field values as a dict for building a SocialPost."""
        platforms = [p for p, cb in self._platform_checks.items() if cb.isChecked()]
        platforms += [p for p, cb in self._sub_platform_checks.items() if cb.isChecked()]
        if hasattr(self, '_manual_platform_checks'):
            platforms += [p for p, cb in self._manual_platform_checks.items() if cb.isChecked()]
        caption_default = self._caption_edit.toPlainText()
        captions = {
            plat: te.toPlainText()
            for plat, te in self._platform_captions.items()
            if te.toPlainText()
        }
        link = self._links_edit.text().strip()
        links = [link] if link else []

        qt_dt = self._schedule_edit.dateTime()
        py_dt = qt_dt.toPython()
        scheduled_time = py_dt.isoformat() if py_dt else ""

        reply_text = self._reply_edit.toPlainText()
        reply_templates = [line for line in reply_text.splitlines() if line.strip()]
        strategy_notes = self._get_strategy_text()

        # Release chain
        release_chain = list(self._release_steps)

        # Identity / collection
        collection = self._identity_combo.currentData() or ""

        # Selected category
        category_id = ""
        if self._category_combo is not None:
            category_id = str(self._category_combo.currentData() or "")

        censor_mode = "auto"
        if hasattr(self, '_censor_uncensored') and self._censor_uncensored.isChecked():
            censor_mode = "uncensored"
        elif hasattr(self, '_censor_custom') and self._censor_custom.isChecked():
            censor_mode = "custom"

        return {
            "platforms": platforms,
            "caption_default": caption_default,
            "captions": captions,
            "links": links,
            "scheduled_time": scheduled_time,
            "reply_templates": reply_templates,
            "strategy_notes": strategy_notes,
            "release_chain": release_chain,
            "collection": collection,
            "category_id": category_id,
            "censor_mode": censor_mode,
        }

    def get_splitter_sizes(self) -> list[int]:
        """Return current content splitter sizes for persistence."""
        return self._content_split.sizes()

    def set_splitter_sizes(self, sizes: list[int]) -> None:
        """Restore content splitter sizes."""
        self._content_split.setSizes(sizes)

    # ------------------------------------------------------------------
    # Platform toggling
    # ------------------------------------------------------------------

    def _on_platform_toggled(self) -> None:
        platforms = [p for p, cb in self._platform_checks.items() if cb.isChecked()]
        if hasattr(self, '_sub_platform_checks'):
            platforms += [p for p, cb in self._sub_platform_checks.items() if cb.isChecked()]
        if hasattr(self, '_manual_platform_checks'):
            platforms += [p for p, cb in self._manual_platform_checks.items() if cb.isChecked()]
        self.platforms_changed.emit(platforms)
        # Rebuild per-platform captions if the toggle is expanded
        if hasattr(self, '_per_platform_toggle') and self._per_platform_toggle.isChecked():
            self._rebuild_per_platform_captions()

    def _on_category_changed(self, _index: int) -> None:
        """Rebuild account checkboxes, captions, and chain when category changes."""
        self._rebuild_account_checkboxes()
        self._rebuild_per_platform_captions()
        if self._release_steps:
            self._rebuild_chain_ui()

    def _rebuild_account_checkboxes(self) -> None:
        """Clear and rebuild the account checkboxes for the selected category."""
        # Remember which accounts were checked
        previously_checked = {
            pid for pid, cb in self._platform_checks.items() if cb.isChecked()
        }

        # Clear existing checkboxes
        while self._accounts_flow.count():
            item = self._accounts_flow.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._platform_checks.clear()

        # Determine which accounts to show
        accounts = self._connected  # fallback: flat list
        if self._categories and self._category_combo is not None:
            cat_id = self._category_combo.currentData()
            for cat in self._categories:
                if cat["id"] == cat_id:
                    accounts = cat.get("accounts", [])
                    break

        for acct in accounts:
            pid = acct["id"]
            name = acct.get("name", pid)
            platform = acct.get("platform", "")
            label = f"{name}  [{platform}]" if platform else name
            cb = QCheckBox(label)
            cb.setProperty("platform_id", pid)
            cb.clicked.connect(self._on_platform_toggled)
            if pid in previously_checked:
                cb.setChecked(True)
            self._platform_checks[pid] = cb
            self._accounts_flow.addWidget(cb)

        # Emit updated platform list
        self._on_platform_toggled()

    def _rebuild_per_platform_captions(self) -> None:
        """Rebuild per-platform caption fields for CHECKED platforms only."""
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        # Save existing caption text
        saved_captions = {
            pid: te.toPlainText() for pid, te in self._platform_captions.items()
        }

        # Clear existing widgets
        while self._pp_layout.count():
            item = self._pp_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._platform_captions.clear()

        # Only show captions for checked OneUp accounts
        for pid, cb in self._platform_checks.items():
            if not cb.isChecked():
                continue
            name = cb.text()
            lbl = QLabel(name)
            lbl.setObjectName("composer_platform_label")
            te = QTextEdit()
            te.setMaximumHeight(int(_f * self.PLATFORM_CAPTION_MAX_HEIGHT_RATIO))
            te.setPlaceholderText(f"Caption for {name} (leave blank to use default)")
            te.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            te.customContextMenuRequested.connect(
                lambda pos, _te=te: self._claude_context_menu(_te, pos))
            if pid in saved_captions and saved_captions[pid]:
                te.setPlainText(saved_captions[pid])
            self._platform_captions[pid] = te
            self._pp_layout.addWidget(lbl)
            self._pp_layout.addWidget(te)

        # Also show captions for checked subscription + manual platforms
        for checks in (
            getattr(self, '_sub_platform_checks', {}),
            getattr(self, '_manual_platform_checks', {}),
        ):
            for pid, cb in checks.items():
                if not cb.isChecked():
                    continue
                name = cb.text()
                lbl = QLabel(name)
                lbl.setObjectName("composer_platform_label")
                te = QTextEdit()
                te.setMaximumHeight(int(_f * self.PLATFORM_CAPTION_MAX_HEIGHT_RATIO))
                te.setPlaceholderText(f"Caption for {name} (leave blank to use default)")
                if pid in saved_captions and saved_captions[pid]:
                    te.setPlainText(saved_captions[pid])
                self._platform_captions[pid] = te
                self._pp_layout.addWidget(lbl)
                self._pp_layout.addWidget(te)

        # Live-count override updates as the user types in any
        # per-platform caption textedit.
        for te in self._platform_captions.values():
            te.textChanged.connect(self._refresh_pp_toggle_label)
        self._refresh_pp_toggle_label()

    # ------------------------------------------------------------------
    # Timezone display
    # ------------------------------------------------------------------

    def _update_tz_display(self):
        """Show the scheduled time in key timezones — horizontal layout."""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            self._tz_label.setText("")
            return
        qt_dt = self._schedule_edit.dateTime()
        py_dt = qt_dt.toPython()
        local_tz = datetime.now().astimezone().tzinfo
        aware = py_dt.replace(tzinfo=local_tz)
        parts = []
        for tz_name, label in [("US/Eastern", "EST"), ("US/Pacific", "PST"), ("Asia/Tokyo", "JST")]:
            try:
                converted = aware.astimezone(ZoneInfo(tz_name))
                parts.append(f"{label} {converted.strftime('%I:%M%p').lstrip('0')}")
            except Exception:
                pass
        self._tz_label.setText("  |  ".join(parts))

    # ------------------------------------------------------------------
    # Toggle per-platform captions
    # ------------------------------------------------------------------

    def _toggle_per_platform(self, checked: bool) -> None:
        if checked:
            self._rebuild_per_platform_captions()
        self._per_platform_container.setVisible(checked)
        self._refresh_pp_toggle_label()

    def _refresh_pp_toggle_label(self) -> None:
        """Update the per-platform toggle text with arrow +
        override count. Reads from live widgets when the
        section is expanded, otherwise from _pp_caption_cache
        captured at set_post time. Non-zero count renders as
        " (N set)" so the user sees overrides exist without
        expanding the section."""
        if self._platform_captions:
            count = sum(
                1 for te in self._platform_captions.values()
                if te.toPlainText().strip())
        else:
            count = len(getattr(self, "_pp_caption_cache", {}) or {})
        arrow = "\u25b2" if self._per_platform_toggle.isChecked() else "\u25bc"
        suffix = f" ({count} set)" if count else ""
        self._per_platform_toggle.setText(
            f"Per-platform captions {arrow}{suffix}")

    # ------------------------------------------------------------------
    # Strategy generation
    # ------------------------------------------------------------------

    def _set_strategy_text(self, text: str) -> None:
        """Set strategy content — renders as HTML in browser, caches raw."""
        self._strategy_raw = text
        self._strategy_edit.setPlainText(text)
        if text:
            import markdown
            html = markdown.markdown(text, extensions=["tables", "fenced_code"])
            self._strategy_browser.setHtml(self._wrap_html(html))
        else:
            self._strategy_browser.setHtml("")
        # Show raw edit view (default)
        self._strategy_stack.setCurrentIndex(0)
        self._strategy_edit_btn.setChecked(False)

    def _wrap_html(self, body: str) -> str:
        """Wrap rendered markdown with theme-aware CSS for compact display."""
        theme_id = QSettings("DoxyEdit", "DoxyEdit").value("theme", DEFAULT_THEME)
        theme = THEMES.get(theme_id)
        if not theme:
            theme = THEMES[DEFAULT_THEME]

        return f"""<style>
body {{ color: {theme.text_primary}; background: {theme.bg_input}; line-height: 1.3; }}
h1, h2, h3, h4 {{ color: {theme.text_primary}; margin: 8px 0 4px 0; padding: 0; }}
h2 {{ font-size: 1.1em; }}
h3 {{ font-size: 1.0em; }}
p {{ margin: 4px 0; }}
ul, ol {{ margin: 4px 0 4px 16px; padding: 0; }}
li {{ margin: 1px 0; padding: 0; line-height: 1.25; }}
hr {{ border: none; height: 2px; background: linear-gradient(to right, transparent, {theme.accent}40, transparent); margin: 10px 0; }}
code {{ background: {theme.bg_raised}; padding: 1px 4px; border-radius: 3px; }}
pre {{ background: {theme.bg_raised}; padding: 6px 8px; border-radius: 4px; margin: 4px 0; }}
table {{ border-collapse: collapse; margin: 4px 0; }}
td, th {{ border: 1px solid {theme.border}; padding: 3px 8px; }}
strong {{ font-weight: 600; color: {theme.text_primary}; }}
a {{ color: {theme.accent}; }}
</style>
{body}"""

    def _get_strategy_text(self) -> str:
        """Get the current strategy text (raw markdown)."""
        if self._strategy_stack.currentIndex() == 0:
            # Raw edit is showing — grab latest from editor
            self._strategy_raw = self._strategy_edit.toPlainText()
        return self._strategy_raw or self._ai_strategy_cache or self._local_strategy_cache

    def _strategy_context_menu(self, pos) -> None:
        """Custom right-click menu for strategy notes — Claude actions + strategy helpers."""
        self._claude_context_menu(self._strategy_edit, pos, extra_actions=[
            ("Generate Local Strategy", self._generate_local_strategy),
            ("AI Strategy (Claude)", self._generate_ai_strategy),
            ("Apply Strategy to Fields", self._apply_strategy),
        ])

    # ------------------------------------------------------------------
    # Claude right-click context menu (shared by all text editors)
    # ------------------------------------------------------------------

    def _claude_context_menu(self, editor: QTextEdit, pos, *,
                             extra_actions: list | None = None) -> None:
        """Show a themed right-click menu with Claude actions on any QTextEdit.

        Parameters
        ----------
        editor : QTextEdit
            The editor widget that was right-clicked.
        pos : QPoint
            Local position from customContextMenuRequested.
        extra_actions : list[tuple[str, callable]] | None
            Additional actions appended after the standard items but before
            Claude actions (e.g. strategy-specific buttons).
        """

        menu = editor.createStandardContextMenu()

        # Theme the popup (top-level menus don't inherit QSS on Windows)
        theme_id = QSettings("DoxyEdit", "DoxyEdit").value("theme", DEFAULT_THEME)
        t = THEMES.get(theme_id, THEMES[DEFAULT_THEME])
        rad = max(3, t.font_size // 4)
        pad = max(4, t.font_size // 3)
        pad_lg = max(6, t.font_size // 2)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {t.bg_raised}; color: {t.text_primary};
                border: 1px solid {t.border}; border-radius: {rad}px;
                padding: {pad}px 0;
            }}
            QMenu::icon {{ padding-left: {pad}px; }}
            QMenu::item {{ padding: {pad}px {pad_lg * 3}px; color: {t.text_primary}; }}
            QMenu::item:selected {{ background: {t.accent_dim}; color: {t.text_on_accent}; }}
            QMenu::item:disabled {{ color: {t.text_muted}; }}
            QMenu::separator {{ background: {t.border}; height: 1px; margin: {pad}px {pad_lg}px; }}
            QMenu::separator {{ background: {t.border}; height: 1px; margin: {pad}px {pad_lg}px; }}
        """)

        # Extra actions (strategy helpers, etc.)
        if extra_actions:
            menu.addSeparator()
            for label, slot in extra_actions:
                menu.addAction(label, slot)

        # Claude actions when text is selected
        selected = editor.textCursor().selectedText()
        if selected.strip():
            menu.addSeparator()

            # Bracketed instruction shortcut  [do something]
            bracket_match = re.search(r'\[(.+?)\]', selected)
            if bracket_match:
                instruction = bracket_match.group(1)
                act = menu.addAction(f"Claude: {instruction[:40]}")
                act.triggered.connect(
                    lambda _=False, e=editor, s=selected: self._refine_with_claude(e, s, "instruct"))
                menu.addSeparator()

            for label, mode in [
                ("Refine with Claude",   "refine"),
                ("Expand with Claude",   "expand"),
                ("Research with Claude",  "research"),
                ("Simplify with Claude",  "simplify"),
            ]:
                act = menu.addAction(label)
                act.triggered.connect(
                    lambda _=False, e=editor, s=selected, m=mode: self._refine_with_claude(e, s, m))

        menu.exec(editor.mapToGlobal(pos))

    def _refine_with_claude(self, editor: QTextEdit, selected: str, mode: str) -> None:
        """Send selected text to Claude for refinement, replace in editor."""
        full_text = editor.toPlainText()

        if mode == "instruct":
            bracket_match = re.search(r'\[(.+?)\]', selected)
            instruction = bracket_match.group(1) if bracket_match else selected
            mode_desc = f"Follow this instruction: {instruction}"
        else:
            mode_desc = {
                "refine": "Improve this text. Fix any issues, clarify wording, make it more actionable. Keep the same length and format.",
                "expand": "Expand this into more detail. Add examples, edge cases, or specifics. Keep the same style.",
                "research": "Research this topic using web search. Find current, accurate, actionable information. Replace the selected text with your findings formatted as concise bullet points. Cite no URLs, just the facts.",
                "simplify": "Make this shorter and more direct. Remove fluff. Keep only what matters.",
            }[mode]

        prompt = f"""You are editing a document for a social media art posting pipeline.

The user selected this text and wants you to act on it:

SELECTED TEXT:
{selected}

FULL DOCUMENT CONTEXT (for reference, don't rewrite the whole thing):
{full_text[:2000]}

INSTRUCTION: {mode_desc}

Return ONLY the replacement text. No explanation, no markdown fences, no preamble. Just the improved text that will replace the selection."""

        self._refine_progress, self._refine_worker = show_claude_modal(
            self, f"Claude: {mode}...", prompt,
            lambda result, _ed=editor, _sel=selected: self._on_refine_done(_ed, _sel, result),
        )

    def _on_refine_done(self, editor: QTextEdit, original: str, replacement: str) -> None:
        """Replace selected text with Claude's refinement."""
        if not replacement:
            return

        cursor = editor.textCursor()
        if cursor.hasSelection():
            cursor.insertText(replacement)
        else:
            current = editor.toPlainText()
            original_normalized = original.replace("\u2029", "\n")
            start = current.find(original_normalized)
            if start >= 0:
                cursor.setPosition(start)
                cursor.setPosition(start + len(original_normalized),
                                   cursor.MoveMode.KeepAnchor)
                cursor.insertText(replacement)
            else:
                cursor.movePosition(cursor.MoveOperation.End)
                cursor.insertText("\n" + replacement)

    def _toggle_strategy_edit(self, checked: bool) -> None:
        """Toggle between raw markdown (default) and rendered preview."""
        if checked:
            # Show rendered preview
            self._strategy_raw = self._strategy_edit.toPlainText()
            if self._strategy_raw:
                import markdown
                html = markdown.markdown(self._strategy_raw, extensions=["tables", "fenced_code"])
                self._strategy_browser.setHtml(self._wrap_html(html))
            else:
                self._strategy_browser.setHtml("")
            self._strategy_stack.setCurrentIndex(1)
            self._strategy_edit_btn.setText("Edit")
        else:
            # Back to raw edit
            self._strategy_stack.setCurrentIndex(0)
            self._strategy_edit_btn.setText("Preview")

    def _build_temp_post(self) -> SocialPost:
        """Build a temporary SocialPost from current form state."""
        data = self.get_post_data()
        return SocialPost(
            platforms=data["platforms"],
            scheduled_time=data["scheduled_time"],
        )

    def _build_temp_post_with_assets(self, asset_ids: list[str]) -> SocialPost:
        """Build a temporary SocialPost including asset IDs (set by parent)."""
        data = self.get_post_data()
        return SocialPost(
            asset_ids=asset_ids,
            platforms=data["platforms"],
            scheduled_time=data["scheduled_time"],
        )

    def _generate_local_strategy(self) -> None:
        """Local data analysis — show cached or generate fresh."""
        if self._strategy_view == "ai" and self._local_strategy_cache:
            self._set_strategy_text(self._local_strategy_cache)
            self._strategy_view = "local"
            self._update_strategy_btn_labels()
            return

        from doxyedit.strategy import generate_strategy_briefing
        # Get asset IDs from parent dialog
        asset_ids = self._get_asset_ids_from_parent()
        temp_post = SocialPost(
            asset_ids=asset_ids,
            platforms=[p for p, cb in self._platform_checks.items() if cb.isChecked()],
            scheduled_time=self.get_post_data()["scheduled_time"],
        )
        briefing = generate_strategy_briefing(self._project, temp_post)
        self._local_strategy_cache = briefing
        self._set_strategy_text(briefing)
        self._strategy_view = "local"
        self._update_strategy_btn_labels()

    def _generate_ai_strategy(self) -> None:
        """Show cached AI strategy or generate new one."""
        if self._strategy_view != "ai" and self._ai_strategy_cache:
            self._set_strategy_text(self._ai_strategy_cache)
            self._strategy_view = "ai"
            self._update_strategy_btn_labels()
            return

        from doxyedit.strategy import generate_ai_strategy

        current = self._get_strategy_text()
        if current and not self._local_strategy_cache:
            self._local_strategy_cache = current

        asset_ids = self._get_asset_ids_from_parent()
        temp_post = SocialPost(
            asset_ids=asset_ids,
            platforms=[p for p, cb in self._platform_checks.items() if cb.isChecked()],
            scheduled_time=self.get_post_data()["scheduled_time"],
        )

        self._ai_strategy_btn.setEnabled(False)
        self._ai_strategy_btn.setText("Generating...")

        # Show themed modal
        self._ai_progress = QProgressDialog("Claude: generating strategy...", None, 0, 0, self)
        self._ai_progress.setObjectName("claude_progress")
        self._ai_progress.setWindowTitle("Claude")
        self._ai_progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._ai_progress.setCancelButton(None)
        self._ai_progress.setMinimumDuration(0)
        _f_ai = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        self._ai_progress.setMinimumWidth(int(_f_ai * self.AI_PROGRESS_MIN_WIDTH_RATIO))
        self._ai_progress.show()

        class _StrategyWorker(QThread):
            finished = Signal(str)
            def __init__(self, project, post):
                super().__init__()
                self._project = project
                self._post = post
            def run(self):
                result = generate_ai_strategy(self._project, self._post)
                self.finished.emit(result)

        self._strategy_worker = _StrategyWorker(self._project, temp_post)
        self._strategy_worker.finished.connect(self._on_ai_strategy_done)
        self._strategy_worker.start()

    def _on_ai_strategy_done(self, result: str) -> None:
        """Handle completed AI strategy generation."""
        if hasattr(self, '_ai_progress'):
            self._ai_progress.close()
        if self._ai_strategy_cache:
            self._ai_strategy_cache += f"\n\n---\n\n**Follow-up:**\n\n{result}"
        else:
            self._ai_strategy_cache = result
        self._set_strategy_text(self._ai_strategy_cache)
        self._strategy_view = "ai"
        self._ai_strategy_btn.setEnabled(True)
        self._update_strategy_btn_labels()

    def _update_strategy_btn_labels(self) -> None:
        """Update button text to show which view is active."""
        if self._strategy_view == "local":
            self._strategy_generate_btn.setText("Local Strategy \u25cf")
            self._ai_strategy_btn.setText(
                "View AI Strategy" if self._ai_strategy_cache else "AI Strategy"
            )
        elif self._strategy_view == "ai":
            self._strategy_generate_btn.setText(
                "View Local Strategy" if self._local_strategy_cache else "Generate Strategy"
            )
            self._ai_strategy_btn.setText("AI Strategy \u25cf")
        else:
            self._strategy_generate_btn.setText("Generate Strategy")
            self._ai_strategy_btn.setText("AI Strategy")

    # ------------------------------------------------------------------
    # Apply strategy suggestions to post fields
    # ------------------------------------------------------------------

    def _apply_strategy(self) -> None:
        """Extract actionable fields from strategy and apply to post."""
        strategy = self._get_strategy_text()
        if not strategy or strategy.startswith("*Analyzing"):
            return


        platforms = [p for p, cb in self._platform_checks.items() if cb.isChecked()]

        prompt = f"""Extract actionable post data from this strategy briefing. Return ONLY valid JSON, no markdown fences, no explanation.

Strategy text:
{strategy}

Current platforms selected: {', '.join(platforms) if platforms else 'none'}

Return this exact JSON structure. Only include fields that the strategy explicitly suggests. Omit fields with no clear suggestion:

{{
  "caption_default": "the best general caption from the strategy, ready to copy-paste",
  "captions": {{
    "twitter": "twitter-specific caption if suggested",
    "instagram": "instagram-specific caption if suggested"
  }},
  "links": ["any URLs mentioned"],
  "schedule_suggestion": "YYYY-MM-DD HH:MM if a different time was recommended, or empty",
  "reply_templates": ["suggested replies or CTAs, one per line"],
  "platforms_add": ["platforms the strategy recommends adding"],
  "platforms_remove": ["platforms the strategy recommends removing"]
}}

RULES:
- Only extract what's actually in the strategy. Don't invent.
- Captions must be exact copy-paste ready text, not summaries.
- If the strategy says the current schedule is fine, leave schedule_suggestion empty.
- No em dashes in any text."""

        self._apply_strategy_btn.setEnabled(False)
        self._apply_strategy_btn.setText("Applying...")

        self._apply_progress, self._apply_worker = show_claude_modal(
            self, "Claude: extracting post data...", prompt, self._on_apply_done,
        )

    def _on_apply_done(self, raw: str) -> None:
        """Parse extracted JSON and fill post fields."""
        self._apply_strategy_btn.setEnabled(True)
        self._apply_strategy_btn.setText("Apply")

        if not raw:
            print("[Apply Strategy] No response from Claude", file=sys.stderr, flush=True)
            return

        # Strip markdown fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            data = json.loads(text)
        except Exception as e:
            print(f"[Apply Strategy] JSON parse error: {e}", file=sys.stderr, flush=True)
            print(f"[Apply Strategy] Raw: {text[:200]}", file=sys.stderr, flush=True)
            return

        print(f"[Apply Strategy] Extracted: {list(data.keys())}", file=sys.stderr, flush=True)

        # Apply caption
        cap = data.get("caption_default", "")
        if cap and not self._caption_edit.toPlainText().strip():
            self._caption_edit.setPlainText(cap)
        elif cap:
            existing = self._caption_edit.toPlainText()
            self._caption_edit.setPlainText(existing + "\n\n--- AI suggestion ---\n" + cap)

        # Apply per-platform captions
        captions = data.get("captions", {})
        for plat, text in captions.items():
            if plat in self._platform_captions and text:
                te = self._platform_captions[plat]
                if not te.toPlainText().strip():
                    te.setPlainText(text)
                if not self._per_platform_toggle.isChecked():
                    self._per_platform_toggle.setChecked(True)
                    self._toggle_per_platform(True)

        # Apply links
        links = data.get("links", [])
        if links and not self._links_edit.text().strip():
            self._links_edit.setText(links[0])

        # Apply schedule suggestion
        sched = data.get("schedule_suggestion", "")
        if sched:
            try:
                dt = datetime.fromisoformat(sched)
                self._schedule_edit.setDateTime(
                    QDateTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, 0)
                )
            except Exception:
                pass

        # Apply reply templates
        replies = data.get("reply_templates", [])
        if replies:
            existing = self._reply_edit.toPlainText()
            new_replies = "\n".join(replies)
            if existing.strip():
                self._reply_edit.setPlainText(existing + "\n" + new_replies)
            else:
                self._reply_edit.setPlainText(new_replies)

        # Apply platform changes
        for plat in data.get("platforms_add", []):
            if plat in self._platform_checks:
                self._platform_checks[plat].setChecked(True)
        for plat in data.get("platforms_remove", []):
            if plat in self._platform_checks:
                self._platform_checks[plat].setChecked(False)

    # ------------------------------------------------------------------
    # Patreon quick-post
    # ------------------------------------------------------------------

    def patreon_quick_post(self, post: "SocialPost", project: "Project", project_dir: str = "."):
        """Copy caption, export image, open Patreon in browser."""
        import webbrowser

        # Get caption for Patreon (per-platform or default)
        caption = post.captions.get("patreon", post.caption_default)

        # Copy to clipboard
        clipboard = QApplication.clipboard()
        clipboard.setText(caption)

        # Export image with overlays
        exported_path = ""
        if post.asset_ids:
            asset = project.get_asset(post.asset_ids[0])
            if asset and asset.source_path:
                try:
                    from PIL import Image
                    from doxyedit.exporter import apply_censors, apply_overlays
                    from pathlib import Path
                    import tempfile

                    src = Path(asset.source_path)
                    if src.exists():
                        ext = src.suffix.lower()
                        if ext in (".psd", ".psb"):
                            from doxyedit.imaging import load_psd
                            img, _, _ = load_psd(str(src))
                        else:
                            img = Image.open(str(src)).convert("RGBA")

                        if asset.censors:
                            img = apply_censors(img, asset.censors)
                        if asset.overlays:
                            img = apply_overlays(img, asset.overlays, project_dir)

                        tmp = Path(tempfile.gettempdir()) / f"doxyedit_patreon_{asset.id}.png"
                        img.save(str(tmp), "PNG")
                        exported_path = str(tmp)
                except Exception:
                    pass

        # Open Patreon post page
        identity = project.get_identity()
        patreon_url = identity.patreon_url if identity else ""
        if patreon_url and "/posts" not in patreon_url:
            post_url = patreon_url.rstrip("/") + "/posts/new"
        else:
            post_url = "https://www.patreon.com/posts/new"
        webbrowser.open(post_url)

        return caption, exported_path

    # ------------------------------------------------------------------
    # Release chain
    # ------------------------------------------------------------------

    def _add_release_step(self) -> None:
        """Add a new step to the release chain."""
        # Default platform: first connected platform not already used
        used = {s["platform"] for s in self._release_steps}
        default_plat = ""
        for p in self._connected:
            if p["id"] not in used:
                default_plat = p["id"]
                break
        if not default_plat and self._connected:
            default_plat = self._connected[0]["id"]

        # First step is anchor with delay=0
        is_anchor = len(self._release_steps) == 0
        step = {
            "platform": default_plat,
            "delay_hours": 0 if is_anchor else 24,
            "account_id": "",
            "caption_key": "",
        }
        self._release_steps.append(step)
        self._rebuild_chain_ui()

    def _remove_release_step(self, index: int) -> None:
        """Remove a step from the release chain (step 0 / anchor is not removable)."""
        if index <= 0 or index >= len(self._release_steps):
            return
        self._release_steps.pop(index)
        self._rebuild_chain_ui()

    def _load_release_template(self, combo_index: int) -> None:
        """Populate release chain from a project template."""
        if combo_index <= 0:
            return  # "Load Template..." placeholder
        tmpl_index = self._chain_template_combo.itemData(combo_index)
        if tmpl_index is None or tmpl_index >= len(self._project.release_templates):
            return
        tmpl = self._project.release_templates[tmpl_index]
        steps = tmpl.get("steps", [])
        if not steps:
            return
        self._release_steps = [
            {
                "platform": s.get("platform", ""),
                "delay_hours": s.get("delay_hours", 0),
                "account_id": s.get("account_id", ""),
                "caption_key": s.get("caption_key", ""),
            }
            for s in steps
        ]
        self._rebuild_chain_ui()
        # Reset combo to placeholder
        self._chain_template_combo.setCurrentIndex(0)

    def _edit_identity(self) -> None:
        """Open a tabbed dialog to create or edit the current identity."""
        _QCB = QComboBox
        current = self._identity_combo.currentData() or ""
        identity = dict(self._project.identities.get(current, {})) if current else {}

        _settings = QSettings("DoxyEdit", "DoxyEdit")

        dlg = QDialog(self)
        dlg.setObjectName("identity_editor")
        dlg.setWindowTitle(f"Edit Identity: {current}" if current else "New Identity")
        _f_dlg = _settings.value("font_size", 12, type=int)
        dlg.setMinimumSize(int(_f_dlg * self.IDENTITY_DIALOG_MIN_WIDTH_RATIO),
                           int(_f_dlg * self.IDENTITY_DIALOG_MIN_HEIGHT_RATIO))

        # Restore saved geometry
        geo = _settings.value("identity_editor_geometry")
        if geo:
            dlg.restoreGeometry(geo)
        else:
            dlg.resize(int(_f_dlg * self.IDENTITY_DIALOG_MIN_WIDTH_RATIO),
                      int(_f_dlg * self.IDENTITY_DIALOG_MIN_HEIGHT_RATIO))

        layout = QVBoxLayout(dlg)

        # Name field (above tabs)
        name_edit = QLineEdit(current)
        name_edit.setPlaceholderText("Identity name (e.g. Doxy, Onta)")
        if current:
            name_edit.setReadOnly(True)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        name_row.addWidget(name_edit)
        layout.addLayout(name_row)

        tabs = QTabWidget()
        tabs.setObjectName("identity_tabs")
        layout.addWidget(tabs)

        edits: dict[str, QLineEdit] = {}

        # ── Tab 1: Profile ──
        profile_tab = QWidget()
        profile_tab.setObjectName("identity_tab_profile")
        profile_form = QFormLayout(profile_tab)
        profile_fields = [
            ("voice", "Brand Voice", "e.g. Playful, energetic, slightly irreverent"),
            ("bio_blurb", "Bio / Blurb", "Short artist bio"),
        ]
        for key, label, placeholder in profile_fields:
            e = QLineEdit(identity.get(key, ""))
            e.setPlaceholderText(placeholder)
            profile_form.addRow(f"{label}:", e)
            edits[key] = e

        # OneUp Category on Profile tab
        cat_combo = _QCB()
        cat_combo.addItem("(None)", "")
        if self._categories:
            for cat in self._categories:
                cat_combo.addItem(cat["name"], str(cat["id"]))
        cat_idx = cat_combo.findData(str(identity.get("category_id", "")))
        if cat_idx >= 0:
            cat_combo.setCurrentIndex(cat_idx)
        profile_form.addRow("OneUp Category:", cat_combo)
        tabs.addTab(profile_tab, "Profile")

        # ── Tab 2: Platforms ──
        platforms_tab = QWidget()
        platforms_tab.setObjectName("identity_tab_platforms")
        platforms_form = QFormLayout(platforms_tab)
        url_fields = [
            ("patreon_url", "Patreon URL", "https://www.patreon.com/yourpage"),
            ("fanbox_url", "Fanbox URL", "https://yourname.fanbox.cc"),
            ("fantia_url", "Fantia URL", "https://fantia.jp/fanclubs/12345"),
            ("cien_url", "Ci-en URL", "https://ci-en.dlsite.com/creator/12345"),
            ("gumroad_url", "Gumroad URL", "https://yourname.gumroad.com"),
            ("kofi_url", "Ko-fi URL", "https://ko-fi.com/yourname"),
            ("subscribestar_url", "SubscribeStar URL", "https://subscribestar.adult/yourname"),
            ("kickstarter_url", "Kickstarter URL", ""),
            ("indiegogo_url", "Indiegogo URL", ""),
        ]
        for key, label, placeholder in url_fields:
            e = QLineEdit(identity.get(key, ""))
            e.setPlaceholderText(placeholder)
            platforms_form.addRow(f"{label}:", e)
            edits[key] = e
        tabs.addTab(platforms_tab, "Platforms")

        # ── Tab 3: Credentials ──
        creds_tab = QWidget()
        creds_tab.setObjectName("identity_tab_credentials")
        creds_form = QFormLayout(creds_tab)
        api_fields = [
            ("bluesky_handle", "Bluesky Handle", "yourname.bsky.social"),
            ("bluesky_app_password", "Bluesky App Password", "Settings > App Passwords"),
            ("telegram_bot_token", "Telegram Bot Token", "From @BotFather"),
            ("telegram_chat_id", "Telegram Chat ID", "-1001234567890 (channel/group ID)"),
            ("discord_webhook_url", "Discord Webhook URL", "Server Settings > Integrations > Webhooks"),
        ]
        for key, label, placeholder in api_fields:
            e = QLineEdit(identity.get(key, ""))
            e.setPlaceholderText(placeholder)
            if "password" in key or "token" in key:
                e.setEchoMode(QLineEdit.EchoMode.Password)
            creds_form.addRow(f"{label}:", e)
            edits[key] = e
        tabs.addTab(creds_tab, "Credentials")

        # ── Tab 4: Chrome Profiles ──
        chrome_tab = QWidget()
        chrome_tab.setObjectName("identity_tab_chrome")
        chrome_scroll = QScrollArea()
        chrome_scroll.setWidgetResizable(True)
        chrome_scroll_inner = QWidget()
        chrome_layout = QVBoxLayout(chrome_scroll_inner)
        chrome_form = QFormLayout()
        chrome_form.setVerticalSpacing(max(6, _f_dlg // 2))
        chrome_layout.addLayout(chrome_form)
        chrome_scroll.setWidget(chrome_scroll_inner)

        existing_profiles = identity.get("chrome_profiles", {})
        chrome_edits: dict[str, QLineEdit] = {}

        # Gather all account IDs: OneUp accounts + subscription platforms
        account_entries: list[tuple[str, str]] = []  # (account_id, display_name)
        if self._connected:
            for acct in self._connected:
                aid = acct.get("id", "")
                aname = acct.get("name", aid)
                if aid:
                    account_entries.append((str(aid), aname))
        for sub_id, sub in SUB_PLATFORMS.items():
            account_entries.append((sub_id, sub.name))

        for acct_id, acct_name in account_entries:
            e = QLineEdit(existing_profiles.get(acct_id, ""))
            e.setPlaceholderText("e.g. Profile 1, Default")
            chrome_form.addRow(f"{acct_name}:", e)
            chrome_edits[acct_id] = e

        # Detect Profiles button
        profile_list = QListWidget()
        _f_prof = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        profile_list.setMaximumHeight(int(_f_prof * self.PROFILE_LIST_MAX_HEIGHT_RATIO))
        profile_list.hide()

        def _detect_profiles():
            profile_list.clear()
            profiles = list_chrome_profiles()
            if profiles:
                profile_list.show()
                for dir_name, display_name in profiles:
                    item = QListWidgetItem(f"{display_name}  ({dir_name})")
                    item.setData(Qt.ItemDataRole.UserRole, dir_name)
                    profile_list.addItem(item)
            else:
                profile_list.show()
                profile_list.addItem("No Chrome profiles found")

        btn_row = QHBoxLayout()
        detect_btn = QPushButton("Detect Profiles")
        detect_btn.clicked.connect(_detect_profiles)
        btn_row.addWidget(detect_btn)

        test_btn = QPushButton("Test")
        def _test_chrome():
            # Find the first non-empty profile and open Chrome with it
            for _aid, e in chrome_edits.items():
                prof = e.text().strip()
                if prof:
                    open_chrome_with_profile("about:blank", prof)
                    return
            open_chrome_with_profile("about:blank", "Default")
        test_btn.clicked.connect(_test_chrome)
        btn_row.addWidget(test_btn)
        btn_row.addStretch()

        chrome_layout.addLayout(btn_row)
        chrome_layout.addWidget(profile_list)
        chrome_layout.addStretch()
        tabs.addTab(chrome_scroll, "Chrome")

        # ── Tab 5: Posting ──
        posting_tab = QWidget()
        posting_tab.setObjectName("identity_tab_posting")
        posting_form = QFormLayout(posting_tab)

        hashtags_edit = QLineEdit(", ".join(identity.get("hashtags", [])))
        hashtags_edit.setPlaceholderText("#art #illustration #commission")
        posting_form.addRow("Hashtags:", hashtags_edit)

        hashtags_ja_edit = QLineEdit(", ".join(identity.get("hashtags_ja", [])))
        hashtags_ja_edit.setPlaceholderText("#イラスト #アート")
        posting_form.addRow("Hashtags (JP):", hashtags_ja_edit)

        voice_ja_edit = QLineEdit(identity.get("voice_ja", ""))
        voice_ja_edit.setPlaceholderText("Japanese brand voice")
        posting_form.addRow("Voice (JP):", voice_ja_edit)
        edits["voice_ja"] = voice_ja_edit

        # Default platforms checkboxes
        default_platforms = identity.get("default_platforms", [])
        platform_checks: dict[str, QCheckBox] = {}
        plat_widget = QWidget()
        plat_layout = FlowLayout(plat_widget, hspacing=8, vspacing=4)
        all_platform_ids = list(self._platform_checks.keys())
        all_platform_ids += list(getattr(self, '_sub_platform_checks', {}).keys())
        for pid in all_platform_ids:
            cb = QCheckBox(pid)
            cb.setChecked(pid in default_platforms)
            plat_layout.addWidget(cb)
            platform_checks[pid] = cb
        posting_form.addRow("Default Platforms:", plat_widget)

        tabs.addTab(posting_tab, "Posting")

        # ── Import/Export + Buttons ──
        btn_row = QHBoxLayout()
        import_btn = QPushButton("Import...")
        import_btn.setObjectName("identity_import_btn")
        def _import_identity():
            path, _ = QFileDialog.getOpenFileName(dlg, "Import Identity", "", "JSON (*.json)")
            if not path:
                return
            with open(path, "r", encoding="utf-8") as fh:
                imported = json.load(fh)
            # Fill fields from imported data
            for key, e in edits.items():
                e.setText(imported.get(key, ""))
            if "hashtags" in imported:
                hashtags_edit.setText(", ".join(imported["hashtags"]))
            if "hashtags_ja" in imported:
                hashtags_ja_edit.setText(", ".join(imported["hashtags_ja"]))
            if not current:
                name_edit.setText(imported.get("name", ""))
            if "oneup_category" in imported and hasattr(dlg, '_cat_combo'):
                for i in range(dlg._cat_combo.count()):
                    if str(dlg._cat_combo.itemData(i)) == str(imported["oneup_category"]):
                        dlg._cat_combo.setCurrentIndex(i)
                        break
        import_btn.clicked.connect(_import_identity)
        btn_row.addWidget(import_btn)

        export_btn = QPushButton("Export...")
        export_btn.setObjectName("identity_export_btn")
        def _export_identity():
            export_name = name_edit.text().strip() or "identity"
            path, _ = QFileDialog.getSaveFileName(dlg, "Export Identity", f"{export_name}.json", "JSON (*.json)")
            if not path:
                return
            data = dict(identity)
            data["name"] = export_name
            for key, e in edits.items():
                val = e.text().strip()
                if val:
                    data[key] = val
            ht = [t.strip() for t in hashtags_edit.text().split(",") if t.strip()]
            if ht:
                data["hashtags"] = ht
            ht_ja = [t.strip() for t in hashtags_ja_edit.text().split(",") if t.strip()]
            if ht_ja:
                data["hashtags_ja"] = ht_ja
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        export_btn.clicked.connect(_export_identity)
        btn_row.addWidget(export_btn)
        btn_row.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        if current:
            del_btn = buttons.addButton("Delete", QDialogButtonBox.ButtonRole.DestructiveRole)
            del_btn.clicked.connect(lambda: self._delete_identity(current, dlg))
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        btn_row.addWidget(buttons)
        layout.addLayout(btn_row)

        result = dlg.exec()
        _settings.setValue("identity_editor_geometry", dlg.saveGeometry())
        _settings.sync()
        if result == QDialog.DialogCode.Accepted:
            name = name_edit.text().strip()
            if not name:
                return
            data = dict(identity)
            for key, e in edits.items():
                val = e.text().strip()
                if val:
                    data[key] = val
                elif key in data:
                    del data[key]
            # Hashtags (English)
            ht = [t.strip() for t in hashtags_edit.text().split(",") if t.strip()]
            if ht:
                data["hashtags"] = ht
            elif "hashtags" in data:
                del data["hashtags"]
            # Hashtags (Japanese)
            ht_ja = [t.strip() for t in hashtags_ja_edit.text().split(",") if t.strip()]
            if ht_ja:
                data["hashtags_ja"] = ht_ja
            elif "hashtags_ja" in data:
                del data["hashtags_ja"]
            # Category
            cat_val = cat_combo.currentData()
            if cat_val:
                data["category_id"] = cat_val
            elif "category_id" in data:
                del data["category_id"]
            # Chrome profiles
            chrome_data = {}
            for acct_id, e in chrome_edits.items():
                val = e.text().strip()
                if val:
                    chrome_data[acct_id] = val
            if chrome_data:
                data["chrome_profiles"] = chrome_data
            elif "chrome_profiles" in data:
                del data["chrome_profiles"]
            # Default platforms
            sel_plats = [p for p, cb in platform_checks.items() if cb.isChecked()]
            if sel_plats:
                data["default_platforms"] = sel_plats
            elif "default_platforms" in data:
                del data["default_platforms"]

            self._project.identities[name] = data
            # Refresh combo
            idx = self._identity_combo.findData(name)
            if idx < 0:
                self._identity_combo.addItem(name, name)
                idx = self._identity_combo.count() - 1
            self._identity_combo.setCurrentIndex(idx)

    def _delete_identity(self, name: str, dlg) -> None:
        """Remove an identity from the project."""
        if name in self._project.identities:
            del self._project.identities[name]
        idx = self._identity_combo.findData(name)
        if idx >= 0:
            self._identity_combo.removeItem(idx)
        self._identity_combo.setCurrentIndex(0)
        dlg.reject()

    def _on_identity_changed(self, name: str) -> None:
        """Auto-fill defaults from the selected identity config."""
        if not name:
            return
        # Cross-project identity: "xproject::<proj_name>::<iname>"
        if name.startswith("xproject::"):
            _, proj_name, iname = name.split("::", 2)
            identity = {}
            for xp in self._extra_projects:
                if (getattr(xp, "name", "") or "") == proj_name:
                    identity = xp.identities.get(iname, {})
                    break
        else:
            identity = self._project.identities.get(name, {})
        if not identity:
            return
        # Auto-switch OneUp category if identity specifies one
        cat_id = identity.get("category_id", "")
        if cat_id and self._category_combo is not None:
            for i in range(self._category_combo.count()):
                if str(self._category_combo.itemData(i)) == str(cat_id):
                    self._category_combo.setCurrentIndex(i)
                    break
        # Auto-check default platforms from identity
        default_platforms = identity.get("default_platforms", [])
        if default_platforms:
            for plat, cb in self._platform_checks.items():
                cb.setChecked(plat in default_platforms)
            self._on_platform_toggled()
        # Auto-fill default release chain if present and chain is empty
        default_chain = identity.get("release_chain", [])
        if default_chain and not self._release_steps:
            self._release_steps = [
                {
                    "platform": s.get("platform", ""),
                    "delay_hours": s.get("delay_hours", 0),
                    "account_id": s.get("account_id", ""),
                    "caption_key": s.get("caption_key", ""),
                }
                for s in default_chain
            ]
            self._rebuild_chain_ui()

    def _get_chain_platforms(self) -> list[dict]:
        """Return platforms available for release chain steps —
        current category accounts + checked subscription platforms."""
        # Category accounts
        accounts = self._connected
        if self._categories and self._category_combo is not None:
            cat_id = self._category_combo.currentData()
            for cat in self._categories:
                if cat["id"] == cat_id:
                    accounts = cat.get("accounts", [])
                    break

        # Add subscription platforms
        result = list(accounts)
        for sub_id, cb in self._sub_platform_checks.items():
            sub = SUB_PLATFORMS.get(sub_id)
            if sub:
                result.append({"id": sub.id, "name": sub.name, "platform": "Sub"})
        return result

    def _rebuild_chain_ui(self) -> None:
        """Clear and rebuild the step rows from self._release_steps."""
        # Clear existing widgets
        while self._chain_steps_layout.count():
            item = self._chain_steps_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        chain_platforms = self._get_chain_platforms()

        _f2 = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)

        for idx, step in enumerate(self._release_steps):
            row = QWidget()
            row.setObjectName("composer_chain_step_row")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(max(4, _f2 // 3))

            # Step label
            step_label = QLabel(f"Step {idx + 1}:")
            step_label.setObjectName("composer_chain_step_label")
            step_label.setFixedWidth(int(_f2 * self.STEP_LABEL_WIDTH_RATIO))
            row_layout.addWidget(step_label)

            # Platform combo
            plat_combo = QComboBox()
            plat_combo.setObjectName("composer_chain_platform")
            for p in chain_platforms:
                plat_combo.addItem(p.get("name", p["id"]), p["id"])
            # Set current
            plat_idx = plat_combo.findData(step["platform"])
            if plat_idx >= 0:
                plat_combo.setCurrentIndex(plat_idx)
            _idx = idx  # capture for closure
            plat_combo.currentIndexChanged.connect(
                lambda _, i=_idx, c=plat_combo: self._update_step_field(i, "platform", c.currentData())
            )
            row_layout.addWidget(plat_combo)

            # Delay spinner
            delay_spin = QSpinBox()
            delay_spin.setObjectName("composer_chain_delay")
            delay_spin.setRange(0, 720)
            delay_spin.setSuffix("h")
            delay_spin.setValue(step["delay_hours"])
            if idx == 0:
                delay_spin.setValue(0)
                delay_spin.setEnabled(False)
            delay_spin.valueChanged.connect(
                lambda v, i=_idx: self._update_step_field(i, "delay_hours", v)
            )
            row_layout.addWidget(delay_spin)

            # Anchor label for step 0
            if idx == 0:
                anchor_lbl = QLabel("(anchor)")
                anchor_lbl.setObjectName("composer_chain_anchor_label")
                row_layout.addWidget(anchor_lbl)

            # Caption key
            cap_key = QLineEdit()
            cap_key.setObjectName("composer_chain_caption_key")
            cap_key.setPlaceholderText("caption key")
            cap_key.setMaximumWidth(int(_f2 * self.CAPTION_KEY_MAX_WIDTH_RATIO))
            cap_key.setText(step.get("caption_key", ""))
            cap_key.textChanged.connect(
                lambda t, i=_idx: self._update_step_field(i, "caption_key", t)
            )
            row_layout.addWidget(cap_key)

            # Remove button (not for anchor)
            if idx > 0:
                remove_btn = QPushButton("\u00d7")
                remove_btn.setObjectName("composer_chain_remove_btn")
                remove_btn.setFixedWidth(int(_f2 * self.REMOVE_BUTTON_WIDTH_RATIO))
                remove_btn.setToolTip("Remove this step")
                remove_btn.clicked.connect(
                    lambda _, i=_idx: self._remove_release_step(i)
                )
                row_layout.addWidget(remove_btn)

            self._chain_steps_layout.addWidget(row)

    def _update_step_field(self, index: int, field: str, value) -> None:
        """Update a single field in a release step."""
        if 0 <= index < len(self._release_steps):
            self._release_steps[index][field] = value

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_asset_ids_from_parent(self) -> list[str]:
        """Get asset IDs from the parent PostComposer's images field."""
        parent = self.parent()
        # Walk up to find PostComposer
        while parent:
            if hasattr(parent, '_images_edit'):
                return [s.strip() for s in parent._images_edit.text().split(",") if s.strip()]
            parent = parent.parent()
        return []

    def disconnect_workers(self) -> None:
        """Disconnect background workers to prevent crash on deleted dialog."""
        for attr in ('_strategy_worker', '_apply_worker'):
            worker = getattr(self, attr, None)
            if worker and worker.isRunning():
                try:
                    worker.finished.disconnect()
                except RuntimeError:
                    pass
