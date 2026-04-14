"""composer_right.py -- Right column of the post composer.

Contains strategy notes, captions, links, schedule, reply templates,
and platform checkboxes.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTextEdit, QPushButton, QCheckBox, QDateTimeEdit, QFrame,
    QScrollArea, QGroupBox, QLayout, QStackedWidget, QTextBrowser,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QDateTime, QRect, QSize, Signal
from PySide6.QtGui import QPixmap

from doxyedit.models import Project, SocialPost, SocialPostStatus


# ─── Flow layout ───────────────────────────────────────────────────

class _FlowLayout(QLayout):
    """Simple flow layout that wraps widgets like text."""

    def __init__(self, parent=None, hspacing=6, vspacing=4):
        super().__init__(parent)
        self._hspacing = hspacing
        self._vspacing = vspacing
        self._items: list = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize(0, 0)
        for item in self._items:
            s = s.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        s += QSize(m.left() + m.right(), m.top() + m.bottom())
        return s

    def _do_layout(self, rect, test_only=False):
        from PySide6.QtCore import QRect as _QRect
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        row_height = 0

        for item in self._items:
            sz = item.sizeHint()
            next_x = x + sz.width() + self._hspacing
            if next_x - self._hspacing > effective.right() and row_height > 0:
                x = effective.x()
                y += row_height + self._vspacing
                next_x = x + sz.width() + self._hspacing
                row_height = 0
            if not test_only:
                item.setGeometry(_QRect(x, y, sz.width(), sz.height()))
            x = next_x
            row_height = max(row_height, sz.height())

        return y + row_height - rect.y() + m.bottom()


# ─── Content panel ─────────────────────────────────────────────────

class ContentPanel(QWidget):
    """Right column: platforms, strategy, captions, links, schedule, replies."""

    platforms_changed = Signal(list)

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setObjectName("composer_content_panel")
        self._project = project

        self._platform_checks: dict[str, QCheckBox] = {}
        self._platform_captions: dict[str, QTextEdit] = {}
        self._local_strategy_cache: str = ""
        self._ai_strategy_cache: str = ""
        self._strategy_view: str = ""  # "local" or "ai"
        self._strategy_raw: str = ""

        self._connected: list[dict] = []
        self._acct_label: str = ""

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        from PySide6.QtWidgets import QSplitter

        root = QVBoxLayout(self)
        root.setSpacing(4)
        root.setContentsMargins(0, 0, 0, 0)

        # --- Platforms (from OneUp connected accounts) ---
        from doxyedit.oneup import get_connected_platforms, get_active_account_label
        project_dir = "."
        for a in self._project.assets:
            if a.source_path:
                project_dir = str(Path(a.source_path).parent)
                break
        self._connected = get_connected_platforms(project_dir)
        self._acct_label = get_active_account_label(project_dir)

        platforms_title = f"Platforms ({self._acct_label})" if self._acct_label else "Platforms"
        platforms_box = QGroupBox(platforms_title)
        platforms_flow = _FlowLayout(platforms_box, hspacing=8, vspacing=4)
        for plat_info in self._connected:
            pid = plat_info["id"]
            name = plat_info.get("name", pid)
            cb = QCheckBox(name)
            cb.setProperty("platform_id", pid)
            cb.clicked.connect(self._on_platform_toggled)
            self._platform_checks[pid] = cb
            platforms_flow.addWidget(cb)
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

        self._strategy_edit_btn = QPushButton("Edit")
        self._strategy_edit_btn.setObjectName("strategy_generate_btn")
        self._strategy_edit_btn.setCheckable(True)
        self._strategy_edit_btn.setToolTip("Toggle between rendered and raw markdown")
        self._strategy_edit_btn.clicked.connect(self._toggle_strategy_edit)
        strategy_btn_row.addWidget(self._strategy_edit_btn)
        strategy_btn_row.addStretch()
        strategy_layout.addLayout(strategy_btn_row)

        # Stacked: rendered HTML view (default) / raw text edit
        self._strategy_stack = QStackedWidget()

        self._strategy_browser = QTextBrowser()
        self._strategy_browser.setObjectName("strategy_browser")
        self._strategy_browser.setOpenExternalLinks(True)
        self._strategy_browser.setPlaceholderText(
            "Click 'Generate Strategy' or 'AI Strategy' to analyze this post")
        self._strategy_stack.addWidget(self._strategy_browser)  # index 0 = rendered

        self._strategy_edit = QTextEdit()
        self._strategy_edit.setPlaceholderText("Raw markdown — edit here, click Edit again to render")
        self._strategy_stack.addWidget(self._strategy_edit)  # index 1 = raw edit

        strategy_layout.addWidget(self._strategy_stack, 1)
        self._content_split.addWidget(strategy_box)

        # -- Scrollable bottom: caption, links, schedule, replies --
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(10)
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
        self._caption_edit.setMaximumHeight(120)
        self._caption_edit.setPlaceholderText("Default caption for all platforms")
        caption_layout.addWidget(self._caption_edit)

        self._per_platform_toggle = QPushButton("Per-platform captions \u25bc")
        self._per_platform_toggle.setCheckable(True)
        self._per_platform_toggle.setChecked(False)
        self._per_platform_toggle.clicked.connect(self._toggle_per_platform)
        caption_layout.addWidget(self._per_platform_toggle)

        self._per_platform_container = QWidget()
        pp_layout = QVBoxLayout(self._per_platform_container)
        pp_layout.setSpacing(4)
        pp_layout.setContentsMargins(0, 0, 0, 0)
        for plat_info in self._connected:
            plat = plat_info["id"]
            lbl = QLabel(plat_info.get("name", plat))
            lbl.setObjectName("composer_platform_label")
            te = QTextEdit()
            te.setMaximumHeight(100)
            te.setPlaceholderText(f"Caption for {plat} (leave blank to use default)")
            self._platform_captions[plat] = te
            pp_layout.addWidget(lbl)
            pp_layout.addWidget(te)

        self._per_platform_container.setVisible(False)
        caption_layout.addWidget(self._per_platform_container)
        layout.addWidget(caption_box)

        # --- Links ---
        links_box = QGroupBox("Links")
        links_layout = QVBoxLayout(links_box)
        self._links_edit = QLineEdit()
        self._links_edit.setPlaceholderText("URL")
        links_layout.addWidget(self._links_edit)
        layout.addWidget(links_box)

        # --- Schedule ---
        schedule_box = QGroupBox("Schedule")
        schedule_layout = QVBoxLayout(schedule_box)
        sched_row = QHBoxLayout()
        self._schedule_edit = QDateTimeEdit()
        self._schedule_edit.setCalendarPopup(True)
        self._schedule_edit.setDisplayFormat("yyyy-MM-dd hh:mm AP")
        tomorrow = datetime.now() + timedelta(days=1)
        self._schedule_edit.setDateTime(
            QDateTime(tomorrow.year, tomorrow.month, tomorrow.day,
                      tomorrow.hour, tomorrow.minute, 0)
        )
        sched_row.addWidget(self._schedule_edit, 1)
        # World clock
        self._tz_label = QLabel()
        self._tz_label.setObjectName("timeline_caption")
        self._update_tz_display()
        self._schedule_edit.dateTimeChanged.connect(lambda _: self._update_tz_display())
        sched_row.addWidget(self._tz_label)
        schedule_layout.addLayout(sched_row)
        layout.addWidget(schedule_box)

        # --- Reply Templates ---
        reply_box = QGroupBox("Reply Templates")
        reply_layout = QVBoxLayout(reply_box)
        self._reply_edit = QTextEdit()
        self._reply_edit.setMaximumHeight(80)
        self._reply_edit.setPlaceholderText("One reply per line")
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

        # Platforms
        for plat, cb in self._platform_checks.items():
            cb.setChecked(plat in post.platforms)

        # Captions
        self._caption_edit.setPlainText(post.caption_default)
        has_per_platform = bool(post.captions)
        if has_per_platform:
            self._per_platform_toggle.setChecked(True)
            self._per_platform_container.setVisible(True)
            self._per_platform_toggle.setText("Per-platform captions \u25b2")
        for plat, te in self._platform_captions.items():
            te.setPlainText(post.captions.get(plat, ""))

        # Links
        if post.links:
            self._links_edit.setText(post.links[0])

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

        # Strategy notes
        if post.strategy_notes:
            self._set_strategy_text(post.strategy_notes)
            self._ai_strategy_cache = post.strategy_notes
            self._strategy_view = "ai"
            self._update_strategy_btn_labels()

    def set_default_platforms(self, defaults: list[str]) -> None:
        """Check the default platforms (used for new posts)."""
        for plat, cb in self._platform_checks.items():
            cb.setChecked(plat in defaults)

    def get_post_data(self) -> dict:
        """Return all field values as a dict for building a SocialPost."""
        platforms = [p for p, cb in self._platform_checks.items() if cb.isChecked()]
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

        return {
            "platforms": platforms,
            "caption_default": caption_default,
            "captions": captions,
            "links": links,
            "scheduled_time": scheduled_time,
            "reply_templates": reply_templates,
            "strategy_notes": strategy_notes,
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
        self.platforms_changed.emit(platforms)

    # ------------------------------------------------------------------
    # Timezone display
    # ------------------------------------------------------------------

    def _update_tz_display(self):
        """Show the scheduled time in key Western timezones."""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            self._tz_label.setText("")
            return
        qt_dt = self._schedule_edit.dateTime()
        py_dt = qt_dt.toPython()
        local_tz = datetime.now().astimezone().tzinfo
        aware = py_dt.replace(tzinfo=local_tz)
        lines = []
        for tz_name, label in [("US/Eastern", "EST"), ("US/Pacific", "PST"), ("Europe/London", "GMT")]:
            try:
                converted = aware.astimezone(ZoneInfo(tz_name))
                lines.append(f"{label}: {converted.strftime('%I:%M%p %a').lstrip('0')}")
            except Exception:
                pass
        self._tz_label.setText("\n".join(lines))

    # ------------------------------------------------------------------
    # Toggle per-platform captions
    # ------------------------------------------------------------------

    def _toggle_per_platform(self, checked: bool) -> None:
        self._per_platform_container.setVisible(checked)
        self._per_platform_toggle.setText(
            "Per-platform captions \u25b2" if checked else "Per-platform captions \u25bc"
        )

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
            self._strategy_browser.setHtml(html)
        else:
            self._strategy_browser.setHtml("")
        # Show rendered view
        self._strategy_stack.setCurrentIndex(0)
        self._strategy_edit_btn.setChecked(False)

    def _get_strategy_text(self) -> str:
        """Get the current strategy text (raw markdown)."""
        if self._strategy_stack.currentIndex() == 1:
            self._strategy_raw = self._strategy_edit.toPlainText()
        return self._strategy_raw or self._ai_strategy_cache or self._local_strategy_cache

    def _toggle_strategy_edit(self, checked: bool) -> None:
        """Toggle between rendered HTML and raw markdown edit."""
        if checked:
            self._strategy_edit.setPlainText(self._strategy_raw)
            self._strategy_stack.setCurrentIndex(1)
            self._strategy_edit_btn.setText("Done")
        else:
            self._strategy_raw = self._strategy_edit.toPlainText()
            if self._strategy_raw:
                import markdown
                html = markdown.markdown(self._strategy_raw, extensions=["tables", "fenced_code"])
                self._strategy_browser.setHtml(html)
            else:
                self._strategy_browser.setHtml("")
            self._strategy_stack.setCurrentIndex(0)
            self._strategy_edit_btn.setText("Edit")

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
        from PySide6.QtCore import QThread, Signal as _Signal

        current = self._get_strategy_text()
        if current and not self._local_strategy_cache:
            self._local_strategy_cache = current

        asset_ids = self._get_asset_ids_from_parent()
        temp_post = SocialPost(
            asset_ids=asset_ids,
            platforms=[p for p, cb in self._platform_checks.items() if cb.isChecked()],
            scheduled_time=self.get_post_data()["scheduled_time"],
        )

        existing = self._ai_strategy_cache
        if existing:
            self._set_strategy_text(existing + "\n\n---\n\n*Generating follow-up...*")
        else:
            self._set_strategy_text("*Analyzing with Claude... 30-60 seconds.*")
        self._ai_strategy_btn.setEnabled(False)
        self._ai_strategy_btn.setText("Generating...")

        class _Worker(QThread):
            finished = _Signal(str)

            def __init__(self, project, post):
                super().__init__()
                self._project = project
                self._post = post

            def run(self):
                result = generate_ai_strategy(self._project, self._post)
                self.finished.emit(result)

        self._strategy_worker = _Worker(self._project, temp_post)
        self._strategy_worker.finished.connect(self._on_ai_strategy_done)
        self._strategy_worker.start()

    def _on_ai_strategy_done(self, result: str) -> None:
        """Handle completed AI strategy generation."""
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

        from PySide6.QtCore import QThread, Signal as _Signal

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

        class _Worker(QThread):
            finished = _Signal(str)
            def __init__(self, p):
                super().__init__()
                self._prompt = p
            def run(self):
                import subprocess, sys
                try:
                    print("[Apply Strategy] Calling Claude to extract fields...", file=sys.stderr, flush=True)
                    result = subprocess.run(
                        ["claude", "-p", self._prompt],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=60,
                    )
                    self.finished.emit(result.stdout.strip() if result.returncode == 0 else "")
                except Exception as e:
                    print(f"[Apply Strategy] Error: {e}", file=sys.stderr, flush=True)
                    self.finished.emit("")

        self._apply_worker = _Worker(prompt)
        self._apply_worker.finished.connect(self._on_apply_done)
        self._apply_worker.start()

    def _on_apply_done(self, raw: str) -> None:
        """Parse extracted JSON and fill post fields."""
        import sys
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
            import json
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
                from datetime import datetime
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
