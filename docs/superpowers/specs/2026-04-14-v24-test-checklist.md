# DoxyEdit v2.4 Test Checklist

## Pipeline Core
- [ ] `prepare_for_platform()` exports Twitter image at 1200x675
- [ ] `prepare_for_platform()` exports Instagram image at 1080x1080
- [ ] Auto-crop centers correctly (wide image → crops sides, tall → crops top/bottom)
- [ ] Censor coordinates transform correctly when image is cropped
- [ ] Overlay positions transform correctly when image is cropped
- [ ] Regions entirely outside crop are skipped (no crash)
- [ ] `censor_override=False` skips censors even on `needs_censor` platforms
- [ ] Exports cache to `_exports/{asset_id}/` directory

## Readiness
- [ ] `check_readiness()` returns red for missing source file
- [ ] Returns red when platform needs censor but asset has none
- [ ] Returns yellow when no explicit crop (auto-fit)
- [ ] Returns green when crop + censor + overlay all present
- [ ] Readiness dots appear on asset grid thumbnails (green/yellow/red)

## Composer
- [ ] Prep strip appears when assets + platforms are selected
- [ ] Prep strip updates when platform checkboxes change
- [ ] Each platform row shows colored dot + "Ready" or issue text
- [ ] Queue button shows advisory warning for red platforms
- [ ] "Post anyway?" allows bypass — queue proceeds
- [ ] Save Draft always works regardless of readiness
- [ ] Censor mode radio buttons visible (Auto / Uncensored / Custom)
- [ ] Censor mode persists on save/reload post

## Entry Points
- [ ] Right-click asset → "Prepare for Posting..." opens composer with asset
- [ ] Studio → "Queue This" button opens composer with current asset
- [ ] Right-click asset → "Send to Studio" loads in Studio + switches tab

## OneUp Integration
- [ ] Category dropdown shows Doxy/Onta/L3rk/0rng
- [ ] Switching identity auto-switches category
- [ ] Sync: fetches OneUp state before pushing (no duplicates)
- [ ] Sync: posts already on OneUp marked as "synced" (not re-pushed)
- [ ] Sync: posts gone from OneUp reverted to draft
- [ ] Duplicate warning dialog if OneUp has dupes
- [ ] Export-on-queue: platform images generated before push

## Direct Posting
- [ ] Bluesky posts with image via AT Protocol (set handle + app password in Identity)
- [ ] Discord webhook posts with image embed
- [ ] Telegram bot posts photo with caption
- [ ] Per-identity credentials (Bluesky/Discord/Telegram) override global config
- [ ] Already-posted platforms skipped on re-sync

## Browser Automation
- [ ] Launch Debug Chrome from Tools > Browser Posting
- [ ] Auto-Post to Subscriptions fills forms for checked sub-platforms
- [ ] Falls back to clipboard+browser if Chrome not running

## Studio
- [ ] Delete key removes selected items
- [ ] Ctrl+D duplicates selected overlay (20px offset)
- [ ] Arrow keys nudge 1px, Shift+Arrow nudges 10px
- [ ] Q/W/E/R switch tools (Select/Censor/Watermark/Text)
- [ ] F fits view to image
- [ ] H toggles overlay visibility
- [ ] Right-click censor: Change to Black/Blur/Pixelate, Delete
- [ ] Right-click overlay: Duplicate, Bring Forward/Backward, Delete
- [ ] Line height slider works on text overlays
- [ ] Text effects (outline + shadow) render on export
- [ ] Studio badge ("S") appears on grid for assets with censors/overlays
- [ ] "Studio" filter checkbox in browser filter bar

## Identity
- [ ] Edit Identity dialog opens from composer
- [ ] All platform URL fields present (Patreon through Indiegogo)
- [ ] API Credentials section with Bluesky/Telegram/Discord fields
- [ ] Password fields use echo mode (masked)
- [ ] Identity saves to project JSON
- [ ] Dialog size persists across opens

## Social Tab Layout
- [ ] Gantt spans full width at bottom
- [ ] Composer docks beside timeline (not over Gantt)
- [ ] Dock width persists after save/close/reopen
- [ ] Calendar/checklist splitter sizes persist
- [ ] Engagement toggle on post cards (collapsible)
- [ ] Done/Snooze buttons work on engagement checks
- [ ] Engagement toolbar button shows count badge
- [ ] Past days dimmed in calendar

## Themes
- [ ] Per-project theme saves with project file
- [ ] Theme switches when changing project tabs
- [ ] All 13 themes have post status badge colors
- [ ] Gantt scene background matches theme
- [ ] Docked composer themed
- [ ] Notes live preview themed

## Transport/Package
- [ ] Package Project dialog with compact option
- [ ] Compact folders collapses single-child chains
- [ ] Expand folders reverses compaction
- [ ] Unpackage restores original paths
- [ ] Merge project imports assets/tags/posts

## Notes
- [ ] Side-by-side editor + live preview
- [ ] Left padding via setViewportMargins (scrollbar at right edge)
- [ ] Claude right-click actions on all composer text editors
- [ ] [Bracketed instructions] detected and offered as Claude action
