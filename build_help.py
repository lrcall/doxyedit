"""Build dist/DoxyEdit Help.html — standalone help file from wiki markdown pages."""
import re
from pathlib import Path
import markdown as md_lib

WIKI = Path(__file__).parent / "wiki"
DIST = Path(__file__).parent / "dist"
OUT  = DIST / "DoxyEdit Help.html"

# Page order
PAGES = [
    "Home",
    "Getting Started",
    "Interface Overview",
    "Tagging System",
    "Preview Window",
    "Thumbnail Cache",
    "Platform Publishing",
    "Health & Stats",
    "Import & Export",
    "Keyboard Shortcuts",
    "Themes & Appearance",
    "Project File Format",
    "CLI Reference",
    "Changelog",
    "Roadmap",
    "Eagle Contrast",
    "Eagle Integration",
    "UI Direction — Eagle Layout",
]

# Vinik24 faithful palette
C = {
    "bg":           "#0d0d0d",
    "sidebar":      "#111118",
    "surface":      "#1a1428",
    "surface2":     "#1e1c2a",
    "accent":       "#666092",
    "accent_br":    "#7ca1c0",
    "text":         "#c5ccb8",
    "text_sub":     "#9a9a97",
    "text_muted":   "#6f6776",
    "teal":         "#387080",
    "border":       "#2a2535",
    "border2":      "#332c50",
    "code_bg":      "#151520",
    "green":        "#4d8a6a",
    "gold":         "#c5a84a",
    "orange":       "#c87a45",
    "red":          "#b05050",
    "blue":         "#5a7ac0",
    "cyan":         "#6db5c8",
    "bold_color":   "#c5b880",
    "italic_color": "#9a9aaf",
}

CALLOUT_COLORS = {
    "note":    (C["cyan"],   C["cyan"]),
    "tip":     (C["green"],  "#93a167"),
    "warning": (C["orange"], C["orange"]),
    "danger":  (C["red"],    C["red"]),
    "info":    (C["blue"],   C["blue"]),
}


def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].lstrip("\n")
    return text


def resolve_wikilinks(text: str) -> str:
    """Convert [[Page Name]] to anchor links."""
    def replace(m):
        page = m.group(1)
        return f'<a href="#{page_id(page)}">{page}</a>'
    return re.sub(r'\[\[([^\]]+)\]\]', replace, text)


def render_callouts(html: str) -> str:
    """Convert Obsidian blockquote callouts to styled divs.
    The markdown lib renders > [!type] Title as a blockquote containing a paragraph
    starting with [!type] Title.
    """
    def replace_callout(m):
        inner = m.group(1)
        cm = re.match(r'<p>\[!(\w+)\](.*?)</p>(.*)', inner, re.DOTALL | re.IGNORECASE)
        if not cm:
            return m.group(0)
        ctype = cm.group(1).lower()
        title_rest = cm.group(2).strip()
        body = cm.group(3).strip()
        bc, tc = CALLOUT_COLORS.get(ctype, (C["accent"], C["accent_br"]))
        label = ctype.title() if not title_rest else title_rest
        return (
            f'<div class="callout callout-{ctype}" style="border-left-color:{bc}">'
            f'<div class="callout-title" style="color:{tc}">{label}</div>'
            f'<div class="callout-body">{body}</div>'
            f'</div>'
        )
    return re.sub(r'<blockquote>(.*?)</blockquote>', replace_callout, html, flags=re.DOTALL)


def page_id(name: str) -> str:
    return name.lower().replace(" ", "-").replace("&", "").replace("--", "-")


def render_page(name: str) -> str:
    path = WIKI / f"{name}.md"
    raw = path.read_text(encoding="utf-8")
    raw = strip_frontmatter(raw)
    raw = resolve_wikilinks(raw)
    html = md_lib.markdown(
        raw,
        extensions=["tables", "fenced_code", "sane_lists"],
    )
    html = render_callouts(html)
    return html


CSS = f"""
* {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 14px;
  background: {C["bg"]};
  color: {C["text"]};
  display: flex;
  height: 100vh;
  overflow: hidden;
}}

/* ── Sidebar ── */
#sidebar {{
  width: 220px;
  min-width: 220px;
  background: {C["sidebar"]};
  border-right: 1px solid {C["border"]};
  display: flex;
  flex-direction: column;
  overflow: hidden;
}}

#sidebar-header {{
  padding: 16px 14px 12px;
  border-bottom: 1px solid {C["border"]};
}}

#sidebar-header .logo {{
  font-size: 13px;
  font-weight: 700;
  color: {C["accent_br"]};
  letter-spacing: 0.06em;
  text-transform: uppercase;
}}

#sidebar-header .version {{
  font-size: 11px;
  color: {C["text_muted"]};
  margin-top: 2px;
}}

#search-box {{
  margin: 10px 10px 8px;
  padding: 6px 10px;
  background: {C["surface"]};
  border: 1px solid {C["border2"]};
  border-radius: 5px;
  color: {C["text"]};
  font-size: 12px;
  outline: none;
  width: calc(100% - 20px);
}}

#search-box:focus {{
  border-color: {C["accent"]};
}}

#search-box::placeholder {{
  color: {C["text_muted"]};
}}

#nav {{
  flex: 1;
  overflow-y: auto;
  padding: 4px 6px 16px;
}}

#nav a {{
  display: block;
  padding: 6px 10px;
  color: {C["text_sub"]};
  text-decoration: none;
  border-radius: 5px;
  font-size: 12.5px;
  line-height: 1.4;
  transition: background 0.1s, color 0.1s;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}

#nav a:hover {{
  background: {C["surface2"]};
  color: {C["text"]};
}}

#nav a.active {{
  background: {C["accent"]};
  color: {C["text"]};
  font-weight: 600;
}}

/* ── Main Content ── */
#main {{
  flex: 1;
  overflow-y: auto;
  padding: 36px 44px;
  max-width: 900px;
}}

/* ── Typography ── */
h1 {{
  color: {C["accent_br"]};
  font-size: 1.9em;
  font-weight: 700;
  border-bottom: 1px solid {C["border2"]};
  padding-bottom: 8px;
  margin-bottom: 22px;
}}

h2 {{
  color: {C["teal"]};
  font-size: 1.25em;
  font-weight: 600;
  border-left: 3px solid {C["accent"]};
  padding-left: 10px;
  margin: 32px 0 14px;
}}

h3 {{
  color: {C["text_sub"]};
  font-size: 1.05em;
  font-weight: 600;
  margin: 24px 0 10px;
}}

h4 {{
  color: {C["text_muted"]};
  font-size: 0.88em;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  margin: 18px 0 8px;
}}

p, li {{
  color: {C["text"]};
  line-height: 1.8;
  margin-bottom: 10px;
}}

ul, ol {{
  padding-left: 22px;
  margin-bottom: 14px;
}}

li {{
  margin-bottom: 4px;
}}

a {{
  color: {C["cyan"]};
  text-decoration: none;
}}

a:hover {{
  color: {C["accent_br"]};
  text-decoration: underline;
}}

strong {{
  color: {C["bold_color"]};
  font-weight: 700;
}}

em {{
  color: {C["italic_color"]};
  font-style: italic;
}}

hr {{
  border: none;
  border-top: 1px solid {C["border"]};
  margin: 24px 0;
}}

/* ── Code ── */
code {{
  background: {C["code_bg"]};
  color: {C["accent_br"]};
  border: 1px solid {C["border"]};
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 0.875em;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
}}

pre {{
  background: {C["code_bg"]} !important;
  border: 1px solid {C["border"]};
  border-left: 3px solid {C["teal"]};
  border-radius: 6px;
  padding: 14px 18px;
  overflow-x: auto;
  margin-bottom: 16px;
}}

pre code {{
  background: transparent !important;
  border: none !important;
  color: {C["text"]} !important;
  padding: 0;
  font-size: 0.9em;
}}

/* ── Tables ── */
table {{
  border-collapse: collapse;
  width: 100%;
  margin-bottom: 18px;
}}

th {{
  background: {C["surface"]};
  color: {C["accent_br"]};
  font-weight: 700;
  padding: 8px 14px;
  border: 1px solid {C["border"]};
  text-align: left;
  font-size: 0.88em;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}}

td {{
  color: {C["text"]};
  padding: 6px 14px;
  border: 1px solid {C["border"]};
  background: {C["surface"]};
  font-size: 0.9em;
}}

tr:nth-child(even) td {{
  background: {C["surface2"]};
}}

tr:hover td {{
  background: {C["border2"]};
}}

/* ── Blockquotes ── */
blockquote {{
  border-left: 3px solid {C["accent"]};
  background: {C["surface"]};
  color: {C["text_sub"]};
  padding: 10px 18px;
  margin: 14px 0;
  border-radius: 0 6px 6px 0;
}}

/* ── Callouts ── */
.callout {{
  border-left: 4px solid {C["accent"]};
  background: {C["surface"]};
  border-radius: 6px;
  padding: 10px 16px;
  margin: 14px 0;
}}

.callout-title {{
  font-weight: 600;
  font-size: 0.9em;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}}

.callout-body p:last-child {{
  margin-bottom: 0;
}}

/* ── Scrollbars ── */
::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: {C["bg"]}; }}
::-webkit-scrollbar-thumb {{ background: {C["accent"]}; border-radius: 4px; }}
::-webkit-scrollbar-thumb:hover {{ background: {C["accent_br"]}; }}

/* ── Search highlight ── */
.search-hit {{ background: rgba(124,161,192,0.22); border-radius: 2px; }}

/* ── Page sections ── */
.page-section {{ display: none; }}
.page-section.visible {{ display: block; }}

/* ── Responsive ── */
@media (max-width: 680px) {{
  #sidebar {{ display: none; }}
  #main {{ padding: 24px 20px; }}
}}
"""

JS = """
const pages = document.querySelectorAll('.page-section');
const navLinks = document.querySelectorAll('#nav a');
const searchBox = document.getElementById('search-box');

function showPage(id) {
  pages.forEach(p => p.classList.remove('visible'));
  navLinks.forEach(a => a.classList.remove('active'));
  const page = document.getElementById(id);
  if (page) page.classList.add('visible');
  const link = document.querySelector('#nav a[href="#' + id + '"]');
  if (link) link.classList.add('active');
  document.getElementById('main').scrollTop = 0;
}

// Handle nav clicks
navLinks.forEach(a => {
  a.addEventListener('click', e => {
    e.preventDefault();
    const id = a.getAttribute('href').slice(1);
    history.replaceState(null, '', '#' + id);
    showPage(id);
  });
});

// Handle in-content links
document.getElementById('main').addEventListener('click', e => {
  const a = e.target.closest('a');
  if (!a) return;
  const href = a.getAttribute('href');
  if (href && href.startsWith('#')) {
    e.preventDefault();
    const id = href.slice(1);
    history.replaceState(null, '', href);
    showPage(id);
  }
});

// Search
searchBox.addEventListener('input', () => {
  const q = searchBox.value.trim().toLowerCase();
  if (!q) {
    navLinks.forEach(a => a.style.display = '');
    return;
  }
  navLinks.forEach(a => {
    const match = a.textContent.toLowerCase().includes(q);
    a.style.display = match ? '' : 'none';
  });
});

// Initial page from hash or default
const hash = location.hash.slice(1) || 'home';
showPage(hash);
"""


def build():
    DIST.mkdir(exist_ok=True)

    nav_items = "\n".join(
        f'<a href="#{page_id(p)}">{p}</a>' for p in PAGES
    )

    sections = []
    for name in PAGES:
        pid = page_id(name)
        content = render_page(name)
        sections.append(f'<div class="page-section" id="{pid}">{content}</div>')

    sections_html = "\n".join(sections)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DoxyEdit v1.9 — Help</title>
<style>
{CSS}
</style>
</head>
<body>

<div id="sidebar">
  <div id="sidebar-header">
    <div class="logo">DoxyEdit</div>
    <div class="version">v1.9 Help</div>
  </div>
  <input id="search-box" type="search" placeholder="Search pages…" autocomplete="off">
  <nav id="nav">
    {nav_items}
  </nav>
</div>

<div id="main">
{sections_html}
</div>

<script>
{JS}
</script>
</body>
</html>
"""

    OUT.write_text(html, encoding="utf-8")
    size = OUT.stat().st_size
    print(f"Built: {OUT}  ({size:,} bytes)")


if __name__ == "__main__":
    build()
