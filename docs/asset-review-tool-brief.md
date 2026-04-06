# Asset Review Tool — Design Brief

## The Problem We're Solving

An artist (Doxy/Onta) has hundreds of finished art files scattered across multiple drives and folders (Dropbox, Desktop, external drives). They need to sort through these images and tag them for specific uses in a Kickstarter campaign. The process needs to be:

1. **Visual** — they need to SEE each image to make a decision
2. **Low friction** — clicking checkboxes, not typing
3. **Categorized** — each image gets tagged for one or more uses (hero image, banner, tier card, merch source, etc.)
4. **Resolution-aware** — they need to know if an image is big enough for its intended use (e.g. a 840x1000 image won't work as a 1600x400 banner)
5. **Persistent** — decisions are saved and can be resumed across sessions
6. **Exportable** — the final tagged set becomes a handoff manifest for graphic designers

## What We're Doing Now (The Hacky Version)

We're generating Obsidian markdown files that embed images using `file:///` paths and put a checklist under each one. The artist scrolls through in Obsidian, clicks checkboxes, and tells Claude to compile the results.

### Current workflow:
1. Claude scans a folder for viewable images (JPG/PNG/GIF)
2. Claude reads each image's dimensions using Python PIL
3. Claude generates a `.md` file with:
   - Embedded image (`![](file:///absolute/path/to/image.jpg)`)
   - Filename + resolution + aspect ratio
   - A checklist of use-case tags
4. Artist opens in Obsidian, scrolls, clicks checkboxes
5. Claude reads the markdown back, compiles which images were tagged for what
6. Claude builds a handoff manifest

### The checklist categories:
- **Hero** — main KS project thumbnail (1024x576, 16:9)
- **Banner** — top of KS page (1600x400, 4:1)
- **Cover(F)** — book front cover
- **Cover(B)** — book back cover
- **Interior** — sample pages showing book quality
- **Promo** — social media posts (1200x675 or 1080x1080)
- **Tier** — reward tier card image (680x382)
- **Stretch** — stretch goal graphic (680x variable)
- **Merch** — source art for stickers/shirts/etc
- **CharRef** — character reference (not for campaign, for internal use)
- **Sketch/Digital** — supplemental art for a digital extras pack
- **Ignore** — skip this image entirely

### Pain points with the current approach:
- **Obsidian can't render `file:///` paths from different drives reliably**
- **No multi-column checkbox layout** — each image has 12 checkboxes in a vertical list, wastes screen space
- **No thumbnail grid** — you see one image at a time, can't compare
- **No resolution warnings** — we show the number but don't flag "this is too small for Banner"
- **No batch operations** — can't select 10 images and tag them all as "Ignore" at once
- **PSDs not viewable** — most source art is in PSD/SAI2 format, we can only show exported JPG/PNG
- **Manual chunk generation** — Claude has to build each markdown file by hand, capped at ~25 images per file
- **No drag/drop sorting** — can't reorder or group visually

## What The Standalone Tool Should Do

### Core Features
1. **Folder scanner** — point it at a folder (or multiple folders), it finds all images recursively. Support JPG, PNG, GIF, WebP. Bonus: PSD thumbnail extraction.
2. **Thumbnail grid view** — show images in a scrollable grid, not one at a time. Each thumbnail shows filename, resolution, and ratio.
3. **Tag panel** — click an image, a panel shows the checklist. Click multiple images, tag them all at once.
4. **Resolution fitness indicator** — for each tag, show green/yellow/red based on whether the image resolution meets the target size:
   - Green: image is large enough, ratio matches or is croppable
   - Yellow: image is large enough but ratio is very different (would need significant cropping)
   - Red: image is too small for this use
5. **Persistent state** — save all tagging decisions to a JSON or SQLite file alongside the images. Resumable.
6. **Export manifest** — generate a handoff document (markdown or PDF) grouped by use case, with file paths, dimensions, and thumbnails.
7. **Filter/sort** — filter by tagged/untagged, by tag, by resolution, by folder source.

### Target Sizes (built-in presets for Kickstarter)
```json
{
  "hero": { "width": 1024, "height": 576, "ratio": "16:9" },
  "banner": { "width": 1600, "height": 400, "ratio": "4:1" },
  "tier": { "width": 680, "height": 382, "ratio": "16:9" },
  "stretch": { "width": 680, "height": null, "ratio": "flexible" },
  "social_twitter": { "width": 1200, "height": 675, "ratio": "16:9" },
  "social_square": { "width": 1080, "height": 1080, "ratio": "1:1" },
  "cover_front": { "width": 1800, "height": 2700, "ratio": "2:3" },
  "cover_back": { "width": 1800, "height": 2700, "ratio": "2:3" }
}
```

### Tech Stack Suggestion
- **Python** — the artist uses Windows, has Python + PIL already installed
- **PyQt6** — for the GUI (native look, good image handling, grid views)
- **Pillow** — image loading, thumbnail generation, dimension reading
- **PyInstaller** — package as single `.exe` for double-click launch
- **JSON** — for saving tag state (simple, human-readable, diffable)

### Nice-to-Haves (Phase 2)
- PSD thumbnail extraction (psd-tools library)
- Drag images between tag groups
- Side-by-side comparison mode
- Auto-suggest tags based on filename patterns (e.g. "cover" in name → suggest Cover tag)
- Integration with the Obsidian vault (write results back to markdown)
- Batch crop/resize to target dimensions
- Direct upload to Kickstarter (browser automation)

### User Context
- The artist has ADHD — the tool must be zero-friction, visually clear, and not overwhelming
- They work across multiple drives (C:, E:, G: Dropbox)
- They have hundreds of images per project, many with nonsense filenames (asdasd.psd, dddd_1.jpg)
- They need to make decisions fast and move on — the tool should make "ignore" and "skip" as easy as possible
- Sessions may be interrupted — state must save automatically, not on explicit "save"

### File Locations for Testing
- Marty Book assets: `G:\B.D. INC Dropbox\Team Vernardo\Marty Print Source\`
- Marty webcomic: `C:\Users\dikud\Desktop\art\marty\`
- Judy Book: `G:\B.D. INC Dropbox\Team Yacky\PROJECTS\Funders\Doxy\Judy Book\`
- Shadowdark Cards: `G:\B.D. INC Dropbox\Team Yacky\PROJECTS\Funders\Orblord\Shadow Dark\SHADOW DARK CARDS\`
- Completed art archive: `G:\B.D. INC Dropbox\Team TODO\-- COMPLETED --\` (~462 files)
