# Platforms Tab Rebuild

## Problem
The current Platforms tab is a mess: drag-drop only works on dashboard (not cards), assigned art hive shows nothing, right-click assign gives no feedback, campaign bar takes too much space, and the layout is disjointed.

## Design

### Layout
```
┌─ Campaign Strip (compact, one row) ─────────────────────┐
│ Campaign: [Kickstarter v2 ▼] Status: preparing  +New    │
├─────────────────────────────────────────────────────────┤
│ Summary: 8/15 filled · 3 posted · 7 empty               │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌─ Kickstarter ──────── ● 3/5 ─┐                       │
│  │ Header     [thumb 16:9] ready │  ← drag here          │
│  │ Gallery 1  [thumb 16:9] ---   │                       │
│  │ Gallery 2  empty — drop image │                       │
│  │ Avatar     [thumb 1:1]  ready │                       │
│  └───────────────────────────────┘                       │
│                                                          │
│  ┌─ Steam ──────────── ◑ 6/11 ──┐                       │
│  │ ...                           │                       │
│  └───────────────────────────────┘                       │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### Key Changes
1. **Campaign bar → compact strip** (one row, not a full panel)
2. **Cards view gets drag-drop** on every slot row (not just dashboard)
3. **Remove hive/assigned art section** (broken, nobody uses it)
4. **Slot rows show thumbnails** at the slot's aspect ratio
5. **Empty slots say "drop image"** instead of "right-click to assign"
6. **Readiness badge** on each card header (● 5/5 green, ◑ 3/5 yellow)
7. **Campaign filter actually works** — hides non-matching platforms completely
8. **Assignment feedback** — slot row flashes green briefly on successful drop
