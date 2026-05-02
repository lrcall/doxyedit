# DoxyEdit UI Redesign - Evidence, Diagnosis, Plan

> [!note] Status as of v2.5: most items shipped
> Most of the contrast / density / icon-rendering issues catalogued
> below have been fixed in subsequent commits (see CHANGELOG.md
> v2.4-v2.5 for the trail). The 21-theme palette plus
> `themes.is_dark_color` / `themes.fg_on_color` helpers (commit
> 81765c7) address the contrast-discipline gap; tokenization sweeps
> across composer, gantt, identity, dialog sizes, etc. closed most
> of the inline-style smell. Kept in-tree as the canonical record
> of the diagnosis methodology; future redesign work should follow
> the same evidence-first structure.

## Why this document exists

The app works, but pressure tested it has surfaced a cluster of UI issues that point
past "theme polish" into layout, density, and information architecture.
Before any redesign, this document collects the concrete evidence, groups it,
names the root causes, and only then proposes directions. No PIL mockups
will be produced until the diagnosis is agreed on.

## Part 1. Evidence (what is actually broken, with receipts)

### A. Contrast and theme discipline

1. **Studio toolbar icons disappeared on light themes.**
   `_StudioIcons._fg()` was reading `studio_icon_fg` from `DEFAULT_THEME`
   (always 'soot', fixed white), not the active theme. On Candy / Dawn /
   Gold the left sidebar tool icons vanished against the light sidebar
   background. Fixed `6aa9f1c`, but the architecture is still fragile:
   toolbar QActions cache icons rendered once at editor construction and
   never re-render on theme change.

2. **InfoPanel section headers illegible on Slate / Ocean / Moss.**
   `QLabel#info_section_header` resolved to `theme.accent_bright`.
   On the new medium tier, accent_bright luminance was within 2:1 of
   bg_raised. Fixed by routing to `text_primary + bold` in `a7f5630`,
   but the audit was reactive - the rule "semantic token choice must
   clear a contrast ratio" is not enforced anywhere.

3. **text_secondary and text_muted too close to bg_main on all 5
   medium themes.** Placeholder text, property labels, and muted
   captions read as empty rows. Bumped luminance gap in `a7f5630`.

4. **Tag colors on medium / light themes.** The VINIK_COLORS palette
   ships fixed colors calibrated against dark backgrounds. On Wine,
   purple / teal / olive entries fade into the rose backdrop. This is
   not fixable by nudging a theme field - it is a dual-palette problem:
   every named tag color needs a dark-bg variant and a light-bg variant,
   or a dynamic lightness compensator at render time.

5. **setStyleSheet literals with hex colors** still live in spots
   (swatch buttons - fixed `463b875` - and a long tail of overlay
   paint that we documented as exception territory). Every new literal
   that slips in reintroduces class 1-4.

### B. Density and layout

6. **Quick Actions bar stole ~80 px of vertical canvas space** in
   Studio until `3495768` compressed it into a single collapsed row.
   Symptom of a deeper problem: Studio keeps growing toolbar widgets
   because it is the default surface for every new tool the user
   sketches. There is no design budget enforcing how much chrome is
   acceptable.

7. **Info panel can not shrink small enough on narrow screens.**
   The user reported a "forced minimum width on tags tray"; the
   widget-level `setMinimumWidth(0)` is already set, but residual
   child `minimumSizeHint` fights the splitter. QSplitter assumes
   child widgets know their own minimum, but many DoxyEdit panels
   have never been reviewed for minimum-width discipline.

8. **Tray, Tag panel, Info panel are three vertical stripes** that
   all compete for horizontal space on a 1600 px display. Any two
   visible at once and the asset grid gets squeezed to < 800 px,
   which kills the density of the thumbnail view.

9. **Tabs rebuild all panels on switch.** `_rebind_project` runs
   over 14 panels per tab swap. Documented in `plan-g-steady-goblet.md`.
   User-visible: a ~300 ms stall when switching to Studio on a large
   project.

### C. Affordance and discovery

10. **Most features live behind right-click context menus.** Studio
    alone has 40+ right-click actions spread across canvas, layer panel,
    status-bar labels, sliders, ruler, tab strip. Users who do not
    right-click by reflex never discover them.

11. **Keyboard shortcuts are not surfaced.** Help > Shortcuts cheatsheet
    (`30d04a2`) lists them, but a first-time user has no way to
    know that S jumps to Studio or that F2 now renames. Discovery
    is behind a menu that most users never open.

12. **No command palette.** Nearly every action is menu-driven.
    When the user asked to "queue this post to Patreon only", the
    actual path is: switch to Social tab -> find the queue dropdown
    -> pick platform -> click Queue. A command palette would collapse
    this into two keystrokes.

13. **Modal dialogs stacked duplicates** until `d07683a`. The
    underlying symptom - dialog-as-singleton is not a first-class
    pattern - means any new dialog I write needs the same guard
    added by hand. Nothing enforces it.

### D. Workflow fragmentation

14. **Four places compose a social post:** Composer, Quick Post,
    Direct Post, and the Studio Queue dialog. They do not share a
    single data path. Platforms duplicate export logic (see
    `plan-g-steady-goblet.md` G2 "unified export cache").

15. **"Tray" is a named-tray system under a single widget.** The
    multi-tray feature (already in `tray.py`) is not surfaced visually.
    A user with 4 trays has no spatial cue that they exist, which
    turns the tray into a junk drawer.

16. **Campaigns, gantt, calendar, checklist, stats, health** each
    live on separate tabs. They are *facets of the same project*.
    Today, checking "what is on track for the Kickstarter deadline"
    requires visiting 3 tabs and cross-referencing.

17. **Notes tab is on the main tab bar** alongside Assets / Studio /
    Social - but Notes is a write-while-you-work facility, not a
    destination. Having to leave Assets to jot a note breaks flow.

### E. Visual hierarchy

18. **No single thing is "primary" on the screen.** Assets tab has
    a browser, a tag panel, an info panel, a tray, a status bar -
    all competing with equal visual weight. The user has to hunt.

19. **Tab bar is low contrast.** Only the active tab underline
    (studio.py commit `543f985`, cross-project pane) reliably signals
    focus. Users who switch projects via the tab bar get lost.

20. **Studio's canvas is the only place with a real viewport metaphor.**
    The rest of the app is rows-of-boxes. There is no visual identity
    that says "this is DoxyEdit" versus any other PySide6 CRUD tool.

## Part 2. Root causes

The evidence clusters into four underlying problems. Every redesign
direction must address at least two of them to be worth exploring.

### RC1. Tabs over workflows

The information architecture is "pick a tab, see its widget." This
worked when the app had 3 tabs. With 6 tabs plus a studio editor
plus tray plus panels, tabs became a partitioning device rather than
a navigation device. Users jump tabs to cross-reference; the data is
fragmented across them.

### RC2. Chrome grows unchecked

There is no design budget. Every new feature adds a button, dropdown,
or panel to the nearest toolbar. Studio.py hit 15 k lines partly
because its toolbar became the dumping ground for every new tool.
`_OVERLAY_ITEM_TYPES` refactor (`0408534`) was a symptom: 20+ places
had grown the same tuple by hand.

### RC3. Theme discipline is reactive

We fix contrast bugs as users report them. There is no
programmatic enforcement of "this widget, under every theme, has
>= 4.5 : 1 text-to-bg contrast." `tokenize` covers literals but does
not catch semantic mismatches like `accent_bright` rendering dim
on new medium themes. Every new theme risks breaking an un-audited
widget.

### RC4. Discovery relies on reading menus

The app has more keyboard shortcuts, right-click menus, and context
submenus than any single user can memorize. We keep adding them
because each one individually is useful. Collectively they form a
wall of hidden commands that new users will never find.

## Part 3. Five redesign directions, argued from the evidence

Each direction names which evidence items it addresses, which root
causes, and which it does not. Followed by a trade-off table.

### Direction 1. Dashboard First

**Thesis.** The default landing screen is not the asset grid. It
is a synthesis view: scheduled posts today, queued exports, alerts
for broken platform auth, starred this-week, campaign progress bars.
The file grid is one of the widgets on the dashboard plus a
dedicated tab for deep browsing.

**Addresses.** RC1 (tabs over workflows), evidence 16-17 (campaigns
scattered across tabs), 14-15 (workflow fragmentation), 18-19
(no primary surface).

**Does not address.** RC2 chrome budget - may make it worse by adding
a whole new widget class. RC3 contrast. RC4 discovery is slightly
better because alerts surface things on the dashboard, but the core
"hidden commands" problem remains.

**Implementation shape.** New `DashboardPanel` widget with a grid
layout of `DashboardWidget` base class. Each existing feature
(scheduled posts, alerts, campaigns, stats) becomes a widget. Landing
behavior changes in `window.py`: default tab is Dashboard; Assets is
reachable but demoted.

**Risk.** Users who open DoxyEdit to "find a file" now have an extra
step. Fixable with a large search box at the top of the dashboard.

**Cost estimate.** 1200-1800 lines new code, 200-400 lines touched
in `window.py`. 2-3 week effort.

### Direction 2. Gallery-Centric

**Thesis.** The asset grid fills the viewport. Tag panel, info panel,
tray, and Studio all become floating / summonable panes that overlay
the gallery. Tabs are eliminated in favor of "chapters" (project
switcher) plus a top bar of summons.

**Addresses.** RC1 (kills tabs), evidence 7-8 (panels squeezing grid),
18 (no primary surface - grid IS the primary), 20 (gives the app
a visual identity - the wall of art).

**Does not address.** Campaigns 16-17 lose a home (they become a
summon). Multi-panel workflows like "tag while previewing" become
a juggling exercise.

**Implementation shape.** Rewrite `MainWindow` layout so tabs are
replaced by a single viewport widget. Panels become `QDockWidget`s
with snap-in/snap-out positions. Studio opens as a full-viewport
overlay.

**Risk.** Big. The multi-tab architecture is load-bearing for
cross-project navigation. Losing it means rebuilding the project-slot
system.

**Cost estimate.** 3-4 weeks. High. This is the direction closest to
"throw it out and start over."

### Direction 3. Command Palette + Minimal Chrome

**Thesis.** Every action becomes a palette entry. Ctrl+Shift+P opens
a fuzzy-search surface that lists every command, asset, tag, post,
platform, and view. Toolbar chrome shrinks to a thin strip; power
users drive the app from the keyboard.

**Addresses.** RC4 (discovery becomes global search instead of
menu-hunting), RC2 (chrome shrinks by design), evidence 10-12
(the right-click wall and the no-discovery problem), 14 (composing
a post becomes "palette > queue kickstarter > enter").

**Does not address.** RC1 (tabs stay). RC3 (contrast).

**Implementation shape.** New `CommandPalette` QDialog with a fuzzy
filter. Register every QAction in a central dispatcher. Each panel
stays where it is; chrome is optionally collapsed.

**Risk.** Bad onboarding for mouse-first users unless palette is
discoverable. Solvable with a persistent "what's new" hint below
the title bar.

**Cost estimate.** 800-1200 lines new code. 1-2 weeks. Non-invasive
because it adds a parallel interaction model.

### Direction 4. Three-Column Pro (Lightroom-shape)

**Thesis.** Fixed three-pane layout: left rail (filters, folders,
collections), center viewport (grid or detail), right inspector
(stacked collapsible panels replacing tabs). All current tab contents
become inspector panels you show or hide.

**Addresses.** RC1 (tabs become stackable panels - information hier
is explicit), evidence 8 (panels no longer compete horizontally,
they stack vertically in one column), 18 (inspector is clearly
secondary, viewport is primary).

**Does not address.** RC2 (chrome may grow in the right column).
RC4 (discovery is still menu-driven).

**Implementation shape.** Convert each tab into a `QDockWidget` or
inspector-panel class. Drop the `QTabWidget` and replace with a
fixed 3-column `QSplitter` + a tabbed dock on the right.

**Risk.** Right inspector will get overloaded. Need a discipline
that each panel collapses by default.

**Cost estimate.** 2 weeks. Touches `window.py` heavily but leaves
individual panel widgets intact.

### Direction 5. Timeline First

**Thesis.** Every asset exists at a point in a campaign schedule. The
master timeline spans the middle of the window; campaigns are
threads; assets are beads; posts are stops. Scrubbing the timeline
is the primary navigation; the inspector under it shows what you
scrubbed to.

**Addresses.** Evidence 16 (campaigns become first-class),
14 (unified export + scheduling because everything hangs off time),
17 (notes attach to timeline beads, not a separate tab), 20 (gives
the app a unique identity - no other asset tool does this).

**Does not address.** Assets without a scheduled use feel orphaned.
Ad-hoc browsing gets harder. RC3, RC4 unchanged.

**Implementation shape.** New `TimelineView` widget as the primary
content. Existing gantt.py becomes its backbone. Assets get a
scheduled_at field or inherit one from their campaign assignment.

**Risk.** High - requires a data model change (or at least a
derived/computed "when does this asset matter" field). Users
with lots of tag-and-forget workflows will resist.

**Cost estimate.** 3 weeks. Data-model touching is the risk, not the UI.

## Part 4. Comparison matrix

| Direction | RC1 tabs | RC2 chrome | RC3 contrast | RC4 discovery | Risk | Effort |
|---|---|---|---|---|---|---|
| 1. Dashboard First | strong | weak | none | medium | medium | 2-3 wk |
| 2. Gallery-Centric | strong | medium | none | weak | high | 3-4 wk |
| 3. Command Palette | weak | strong | none | strong | low | 1-2 wk |
| 4. Three-Column Pro | strong | medium | none | weak | medium | 2 wk |
| 5. Timeline First | strong | weak | none | medium | high | 3 wk |

Contrast (RC3) is not addressed by any redesign because it is a
theme-system problem, not a layout problem. It needs its own
workstream (dual palette for VINIK_COLORS, programmatic contrast
linting in `themes.generate_stylesheet`). Fold that into whichever
direction is chosen.

## Part 5. Recommendation

Split the work.

**First.** Ship Direction 3 (Command Palette) as an additive feature.
It is the lowest-risk high-reward move: RC4 discovery is the root
cause hurting the most users; palette addresses it without changing
the existing layout. 1-2 weeks. We keep the current tabs, current
panels, current muscle memory. Users get a new superpower on top.

**Second.** Pick between Direction 4 (Three-Column Pro) and Direction 1
(Dashboard First) as the medium-term direction. Three-Column Pro
has lower risk and aligns with pro-tool expectations. Dashboard First
is riskier but solves the scattered-campaign problem more directly.

**Third.** Run the contrast workstream in parallel regardless. Add
`contrast_lint.py` to `tools/`; extend `tokenize` to flag semantic
mismatches; ship dual-palette VINIK_COLORS (dark-bg + light-bg
variants, pick at render time from theme tier).

**Do not.** Pursue Direction 2 (Gallery-Centric) or 5 (Timeline First)
without a bigger re-architecture commitment. Both are compelling but
each is effectively a ground-up rebuild of the main window.

## Part 6. What I need from you before any code lands

1. Rank the evidence items: which ones hurt most in your daily use?
   That re-weights the trade-off matrix.
2. Confirm the root-cause framing (RC1-RC4) resonates or push back
   with an RC5 I missed.
3. Pick an appetite: 2 weeks, 1 month, or 3 months of UI work.
4. Say yes/no to the "ship palette first, debate long-term after"
   split.

Once the above is settled, I will produce rendered mockups of the
chosen direction (not five guesses) and a week-by-week implementation
plan.
