---
name: 3d-animation
description: Use for 3D character and object animation — keyframes, actions and slots, NLA, mocap retargeting, cycles, animation export.
---
# 3D animation (hub)

## Scope
Keyframe and motion-capture animation of rigged characters and objects, mostly in Blender (5.2 LTS, released 2026-07-14), with export to engines. Rigs in `character-rigging`*; bpy and headless runs in `blender-3d`; engine import in `game-engines`*; 2D motion design in `motion-graphics`; Houdini KineFX and crowds in `houdini-fx`.

## Modules
| module | load when |
|---|---|
| `character-rigging`* | skeletons, deform vs control bones, IK/FK, constraints, skin weights, shape keys, facial rigs, rig scripting, engine-ready skeletons |

`*` = not in the skill listing: Read `__CLAUDE_DIR__/skills/<name>/SKILL.md` (the Skill tool won't load it).

## Craft rules
- Block in stepped keys on the golden poses (contact, down, passing, up for walks; anticipation, action, follow-through elsewhere), check timing at full speed, then spline and polish. Arcs, spacing and overlap are judged in the Graph Editor and with motion paths, not by eye in one view.
- Timing is in frames at a fixed rate stated up front (24 film, 30 or 60 games and UI); never retime by changing the scene frame rate after keying.
- Cycles (walks, idles, loops) start and end on the same pose with matching tangents: Cycles F-curve modifier while keying, then bake. Root motion is a deliberate choice: in place for engines that drive locomotion, on the root bone for engines that extract it.
- Animate controls, never deform bones; keep the rig's rest pose untouched so retargeting and export stay valid.
- Mocap: clean the source (foot contacts, jitter, pops) before retargeting; retarget onto matching rest poses (T- or A-pose aligned first); fix contacts with IK and animation layers rather than editing every key.

## Blender data model (4.4+, scripts must follow it)
- Every Action is layered and slotted since 4.4: one Action can animate several data-blocks through slots. F-curves live in a channelbag per slot; 5.0 removed `action.fcurves`, `action.groups` and `action.id_root` (use `action_slot.target_id_type`).
```python
from bpy_extras import anim_utils
ad = obj.animation_data_create()
act = bpy.data.actions.new("Walk")
slot = act.slots.new(id_type="OBJECT", name=obj.name)   # a new Action has no slot yet
ad.action = act
ad.action_slot = slot
cb = anim_utils.action_ensure_channelbag_for_slot(act, slot)   # 5.0+
fc = cb.fcurves.ensure("location", index=2, group_name="Object Transforms")
```
- NLA: push actions to strips to layer and blend clips; engines that read clips take one action per strip or per slot (export settings below). Bake (`bpy.ops.nla.bake`, visual keying, clear constraints) before exporting constraint-driven motion.
- Newer tools: Copy Global Transform is built in (5.0); Replace Action and the Gaussian Smooth F-curve modifier (5.1); in-between tools in Object Mode and pose-library rotation-mode conversion (5.2). Pose libraries are assets (`pose_library` add-on, core).
- Mocap import: BVH via the core `io_anim_bvh` add-on; FBX via `io_scene_fbx`; a C++ FBX importer (`bpy.ops.wm.fbx_import`) was experimental in 4.5 (its 5.2 status unverified).

## Export
- glTF (`bpy.ops.export_scene.gltf`): `export_animation_mode` = `ACTIONS` (default, one glTF animation per action), `ACTIVE_ACTIONS`, `BROADCAST`, `NLA_TRACKS` or `SCENE`; `export_force_sampling` is on by default (bakes constraints and drivers); 4 influences per vertex by default (`export_influence_nb`), deform bones only off by default (`export_def_bones`) — turn it on for engines.
- FBX (`bpy.ops.export_scene.fbx`): `bake_anim` with all actions or NLA strips; `add_leaf_bones` is on by default (most engines want it off); bone axes Y primary, X secondary by default; units: `apply_scale_options` (`FBX_SCALE_NONE`, `FBX_SCALE_UNITS`, `FBX_SCALE_CUSTOM`, `FBX_SCALE_ALL`) — re-import to check scale and orientation.
- USD for pipelines (skeletal animation as UsdSkel); check the target DCC reads the exported skeleton before committing to it.

## Verify
Playblast or viewport render of every clip at the delivery frame rate, Read · cycles loop without a pop (first and last frame compared) · feet do not slide on contacts (contact frames checked) · exported file re-imported into Blender or the target engine with matching length, rate and pose · versions of Blender and exporters reported.

Sources (checked 2026-10-05): https://developer.blender.org/docs/release_notes/5.0/python_api/ · https://developer.blender.org/docs/release_notes/5.0/animation_rigging/ · https://developer.blender.org/docs/release_notes/5.1/animation_rigging/ · https://developer.blender.org/docs/release_notes/5.2/animation_rigging/ · https://github.com/KhronosGroup/glTF-Blender-IO · https://www.blender.org/download/releases/
