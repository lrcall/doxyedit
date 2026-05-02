---
tags: [platforms, export, publishing, kickstarter, steam, patreon]
description: Platform slot management, asset assignment, status tracking, and export workflow.
---

# Platform Publishing

DoxyEdit tracks which images are assigned to which platform slots and exports resized copies automatically.

---

## Built-in Platforms

| Platform | Notes |
|----------|-------|
| Kickstarter | Campaign image slots (hero, banner, etc.) |
| Kickstarter (Japan) | Japan-market variant — can include censored assets |
| Steam | Store page images |
| Patreon | Post images |
| Twitter / X | Social media images |
| Reddit | Post images |
| Instagram | Square/portrait post images |

---

## Platform Slots

Each platform defines one or more **slots** — named positions with a required size. Examples from Kickstarter:

| Slot | Target Size |
|------|------------|
| Hero | 1024 × 576 |
| Banner | 1600 × 400 |
| Cover | (varies) |
| Tier Card | (varies) |
| Stretch Goal | (varies) |
| Interior | (varies) |

Each slot displays:
- The slot name
- The target dimensions
- The assigned asset thumbnail (or empty if unassigned)
- Status badge

---

## Slot Status Values

| Status | Meaning |
|--------|---------|
| pending | No asset assigned yet |
| ready | Asset assigned, ready to export |
| posted | Already published to the platform |
| skip | Intentionally left empty for this campaign |

Right-click a thumbnail → **Update Status** submenu to change status quickly without opening the Platforms tab.

---

## Assigning Assets to Slots

### From the Assets Tab

- Right-click selected thumbnails → **Assign to Platform** → choose platform and slot
- Multi-select is supported: select multiple assets then batch-assign

### From the Platforms Tab

- The Platforms tab shows the full slot grid
- Click a slot to assign the currently selected asset

---

## Fitness Indicator

In the Tag Panel, Platform/Size tags show colored fitness dots for the selected image:

| Color | Meaning |
|-------|---------|
| Green | Image meets the size requirement |
| Yellow | Large enough but wrong aspect ratio — crop needed |
| Red | Image is too small |

This helps you quickly find which images are suitable for each platform slot without exporting.

---

## Export

**Ctrl+E** — exports all platforms at once.

- Each slot is exported as a resized copy (auto-scaled to target dimensions)
- Original files are never modified
- Export creates copies with platform-appropriate filenames

> [!warning] Smart Export Gap Detection
> DoxyEdit warns when a required platform slot has no asset assigned before proceeding with export. Check the status bar for warnings.

---

## Studio Censor Integration

Non-destructive censors are drawn in the **Studio** tab (X key)
and applied at export time for platforms that require them (e.g.,
Kickstarter Japan, Fantia, Ci-en). See [[Import & Export]] for the
export workflow and [[Interface Overview]] for Studio's tool surface.
(Pre-v2.0 docs called this the "Censor tab" — that tab was merged
into Studio.)

The **Needs Censor** filter button shows assets assigned to censor-
required platforms that have no censor regions drawn yet.

---

## Platform Status in Tag Panel

The Tag Panel's Platform/Size section shows each platform target as a tag. This is where fitness dots appear. These tags also appear on thumbnails as colored dots, giving you at-a-glance status in the grid view.

---

## Campaign Timeline / Posting Checklist

A per-project checklist can be maintained as a markdown-editable document linked to asset readiness. This is accessible from the project notes panel (**View** menu).

---

## Related

- [[Interface Overview]] — Platforms tab + Studio tab (which now owns censor)
- [[Import & Export]] — export workflow details
- [[Tagging System]] — platform tags and fitness dots
- [[Health & Stats]] — platform assignment summary via CLI
