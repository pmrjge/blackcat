---
name: 3d-ux-design
description: Use for UX of 3D apps and spatial UI — viewport navigation, selection, manipulators, tool and panel layout, XR comfort and targets.
---
# 3D and spatial UX design

Hub: `ui-design-systems` (tokens, 2D panels, states, handoff). Building it: `3d-interface-engineering`. Accessibility criteria: `web-accessibility`. Motion and transitions: `motion-graphics`. Diagrams of flows and state machines: `diagrams-as-code`.

## 1. Decide the interaction model first
- Who and what: creation tool (modeling, layout, animation), configurator or viewer, data visualization in 3D, or a spatial/XR app. Novices need guided, modeless flows; experts need speed, shortcuts and modes. Write the top 5 tasks with a success measure each before drawing screens.
- Selection model: object–action (select, then act; the default for editors) vs action–object (pick a tool, then targets; good for single-purpose tools). State it and keep it everywhere.
- Modes (object, edit, sculpt, paint) cost discoverability but buy dense shortcuts; if you use modes, show the current mode permanently and make mode-specific tools disappear, not grey out.
- Direct manipulation over dialogs: drag in the viewport, type an exact value while dragging (numeric input), confirm or cancel (Enter/Esc, right-click cancels in Blender's convention).
- Undo: every committed drag or command is one undo step with a readable name; camera moves are not undo steps by default (optional setting); non-destructive stacks (modifiers, history, layers) let users revisit decisions.

## 2. Viewport navigation
- Support the conventions users already have, as switchable presets:

| app family | orbit | pan | zoom | frame selection |
|---|---|---|---|---|
| Blender | MMB | Shift+MMB | wheel, Ctrl+MMB | numpad `.` |
| Maya, Unreal-style DCC | Alt+LMB | Alt+MMB | Alt+RMB, wheel | `F` |
| trackpad | two-finger drag | Shift+two-finger | pinch | key or double-tap |

- Turntable orbit (keeps the world up axis) is the default for most users; trackball as an option. Orbit around the selection or the point under the cursor; zoom toward the cursor; never let the camera pass through or lose the model (a "frame all" reset always one key away).
- Navigation gizmo or view cube for discoverability and touch; named views (front, side, top) with orthographic snapping; perspective/orthographic toggle.
- Auto-adjust near and far clip planes to the scene's scale; show the grid and units so users know scale.

## 3. Selection and manipulation
- Click selects, Shift-click adds (or toggles), drag on empty space box-selects; lasso as an option; "select through" vs visible-only stated in the UI. Distinguish **active** (last selected, the pivot or reference) from the rest of the selection.
- Feedback layers: hover pre-highlight, selection outline (not a tint alone), active element in a second color, hidden-but-selected indicated in the outliner.
- Transform gizmo: axes colored X red, Y green, Z blue and labeled (color is not the only cue); plane handles for two-axis moves; constant screen-space size; handles grow on hover; the active axis is the only one shown during a drag.
- Orientation (global, local, view, normal) and pivot (median, active, cursor, individual origins) visible next to the gizmo; snapping (grid, increment, vertex, surface) toggled by a held modifier and shown while active.
- A heads-up readout during drags (delta and absolute values in the scene's units).

## 4. Layout of a 3D application
- Viewport first: it gets most of the screen; panels collapse to edges. Common anatomy: toolbar (tools), outliner (hierarchy), properties (context-sensitive), timeline or asset browser (bottom), status bar (shortcuts for the current mode).
- Command search (Blender's F3, a Ctrl/Cmd+K palette) reaches every command by name and shows its shortcut; menus show shortcuts; keymaps are customizable and exportable.
- Progressive disclosure: defaults that work, advanced settings in collapsed panels; contextual properties for the selection type.
- Empty states and onboarding: a starter scene or template, a short interactive tour of navigation, recoverable mistakes (undo, autosave, version history).
- Performance is UX: interaction at 60 fps or better, input-to-photon latency low; degrade quality while orbiting (LOD, lower samples) and refine when still; long jobs async with progress and cancel.

## 5. Accessibility in 3D
- Every viewport operation has a keyboard path (frame, orbit by steps, select next/previous in hierarchy, transform by typed value).
- A non-visual model of the scene: the outliner as an accessible tree (DOM or platform accessibility API), with names, types and selection state announced.
- Reduced motion: camera transitions cut or shorten; no auto-rotate by default. UI scale adjustable; text over the 3D scene on solid or blurred backplates with checked contrast; colorblind-safe selection and axis colors with labels.

## 6. Spatial and XR interfaces
- Size by **angle**, not pixels: 1° at 1 m ≈ 1.75 cm; about 2.5° ≈ 4.4 cm at 1 m. visionOS: interactive targets need about 60 pt of area (a 44 pt control plus spacing); hover effects show what the eyes target.
- Input: gaze + pinch (indirect) for distant content, direct touch for content within reach; never require precise mid-air holds; give every gesture a visible affordance.
- Placement: primary content in front and slightly below eye level, within a comfortable head rotation; avoid head-locked panels (they cause discomfort) except brief notices; let users reposition windows. visionOS distinguishes windows, volumes and immersive spaces: choose the least immersive one that works.
- Depth sparingly: use it for hierarchy (raised controls, layered panels), keep text on flat, readable planes facing the user.
- Comfort: steady frame rate (90 Hz targets; a dropped frame is felt), no camera motion the user did not cause; locomotion by teleport or snap turn, vignetting during smooth movement; sessions designed for breaks.
- Real-world safety: passthrough or boundaries for room-scale; never block the user's view without their action.

## 7. Validate with users
- Prototype at the fidelity the question needs (paper for layout, a three.js or engine prototype for navigation feel, a headset build for XR comfort); test the top tasks with 5+ representative users; record time, errors and where the camera got lost.
- Instrument the build (anonymous, opt-in) for command use and undo rates; frequent undo after a tool means the tool surprises people.
- Deliver an interaction spec: input map per device, states per tool, feedback per state, shortcuts, accessibility paths, open questions.

## Verify
Top tasks and success measures written · navigation presets and frame/reset reachable · selection, active and hover visually distinct (not by color alone) · numeric entry and snapping on every manipulator · keyboard and screen-reader paths · XR targets sized by angle and placements tested in a headset · usability findings recorded.

Sources (checked 2026-10-05): https://developer.apple.com/design/human-interface-guidelines/spatial-layout · https://developer.apple.com/videos/play/wwdc2023/10073/ · https://developer.apple.com/videos/play/wwdc2023/10076/ · https://developer.apple.com/videos/play/wwdc2025/303/ · https://www.w3.org/TR/WCAG22/ · https://docs.blender.org/manual/en/latest/editors/3dview/navigate/index.html
