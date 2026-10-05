---
name: character-rigging
description: Use for character rigs — skeletons, controls, IK/FK, constraints, skin weights, shape keys, facial rigs, engine-ready skeletons.
---
# Character rigging

Hub: `3d-animation` (animation, actions, export). bpy and headless runs: `blender-3d`. Mesh topology for deformation: `sculpting-texturing`. Versions: Blender 5.2 LTS (2026-07-14); the API notes below are from the 5.0–5.2 release notes.

## 1. Before the first bone
- Get the brief: target (film, game engine, real-time web, XR), engine skeleton constraints (bone count, influences per vertex, naming, root motion, scale), the animation list, and whether the rig must match an existing skeleton (retargeting, shared animation library).
- Check the mesh: applied scale and rotation (scale 1.0, meters), clean manifold topology, edge loops around every joint (shoulder, elbow, wrist, fingers, hips, knees, mouth and eyes), symmetry on the X axis, rest pose chosen on purpose (A-pose deforms shoulders better, T-pose retargets more simply). A topology problem goes back to modeling; rig work does not paper over it.
- Name everything: `<side>_<part>_<type>` or Blender's `.L`/`.R` suffix (which Blender mirrors automatically); prefixes `DEF-`, `MCH-` and `ORG-` follow Rigify's convention for deform, mechanism and original bones.

## 2. Skeleton architecture
- Three layers: **deform** bones (the only ones skinned and exported to engines), **mechanism** bones (IK chains, twist helpers, constraint targets) and **controls** (what the animator touches, with custom shapes). Controls drive mechanism, mechanism drives deform, never the reverse.
- One root at the origin, then the hips (center of gravity) or a separate COG control; spine as 3–5 bones with a spline IK or a chain of copy-rotation controls; neck 1–2 bones; head.
- Limbs: three-bone chains with a slight bend in the rest pose toward the knee or elbow direction so IK solves the right way; pole targets placed on that plane; IK/FK switch with snapping both ways (Rigify gives this; custom rigs need a snap operator or script).
- Twist: forearm and upper-arm twist bones (or a B-Bone segment count with ease) so the wrist can rotate 180° without candy-wrapping.
- Roll matters: align bone rolls (Recalculate Roll to a global axis or the active bone) so mirrored controls rotate the same way on both sides.
- Bone collections (since 4.0) organize controls (`armature.collections.new("FK Arm.L")`, `collection.assign(bone)`); lock what animators must not key.

## 3. Constraints and drivers
- IK (chain length set, pole angle tuned so the rest pose doesn't twist), Damped Track and Stretch To for aim and squash, Copy Rotation/Location with mix modes for layered controls, Child Of for props (keyed influence, with Set Inverse), Armature constraint for multi-parent switches.
- 5.0 added the **Geometry Attribute** constraint (drive a bone from a mesh attribute) and bone custom shape options "Affect Gizmo" and "Use As Pivot"; 5.2 adds Copy Constraints to the Ctrl+L menu and armature Duplicate and Rename.
- Drivers: single-property or transform-channel variables, simple expressions only (Python expressions in drivers need auto-run scripts and are slower); custom properties on a properties bone for switches (IK/FK, space switches, visibility).

## 4. Skinning
- Bind with automatic weights (Ctrl+P → With Automatic Weights) as a start only; fix in Weight Paint with the deform bones' vertex groups, normalized, at most 4 influences per vertex for most engines (Limit Total, then Normalize All).
- Paint while posed (pose mode toggles in Weight Paint with the armature selected) and test each joint at its extremes.
- Shoulders, hips and the neck usually need helper bones or corrective shape keys; weights alone cannot hold volume at 90°+ bends.
- Data Transfer modifier (vertex groups, nearest face interpolated) to copy weights to clothing and LOD meshes; apply it before export.
- Corrective shapes: a shape key driven by the joint angle (a driver on the shape key's value reading the bone's rotation in its local space, or Blender's "Rotational Difference" variable between two bones).

## 5. Shape keys and faces
- Shape keys are per mesh: one Basis plus relative keys; 5.0 added "Make Basis" and flipped the Join as Shapes direction; 5.1 added "Apply to Basis".
- Facial rigs combine jaw and eye bones with shape keys for lips, brows, cheeks and lids. For real-time faces driven by face tracking, the 52 ARKit blendshape names (`jawOpen`, `eyeBlinkLeft`, `mouthSmileLeft`, …) are the common contract; check the target's exact list.
- Keep shape keys symmetric pairs (`_L`/`_R`) generated from one sculpted full shape with a vertex-group split (Blender: Shape Key → Mirror, or split with vertex groups and a script).
- Modifiers that change vertex count (Subdivision, Mirror unapplied) and shape keys don't mix at export: apply them on a copy first (the exporters' handling when they must apply modifiers to a shape-keyed mesh is unverified here: read their warnings and re-import).

## 6. Rigify (core add-on)
- Add a metarig (Human), fit it to the mesh in Edit Mode, Generate Rig, then bind the mesh to the generated rig's `DEF-` bones. Re-generate after metarig edits; never edit the generated rig by hand (changes are lost on the next generate) — script post-generate fixes.
- For engines: export a separate deform-only skeleton (Rigify's `DEF-` hierarchy is not a single clean chain: parent DEF bones to each other with a script or use an engine-skeleton add-on) and bake the animation onto it.

## 7. Scripting rigs (Blender 5.x API)
```python
import bpy
arm = bpy.data.armatures.new("Rig"); rig = bpy.data.objects.new("Rig", arm)
bpy.context.scene.collection.objects.link(rig)
with bpy.context.temp_override(active_object=rig, selected_objects=[rig]):
    bpy.ops.object.mode_set(mode="EDIT")
    root = arm.edit_bones.new("root"); root.head = (0, 0, 0); root.tail = (0, 0.3, 0)
    bpy.ops.object.mode_set(mode="POSE")
pb = rig.pose.bones["root"]
pb.hide = False                  # 5.0: visibility in Object/Pose Mode lives on the pose bone
pb.select = True                 # 5.0: Bone.select was removed; pose and edit bones carry select
```
- 5.0 API breaks: `Bone.hide` now affects Edit Mode only (use `PoseBone.hide`); `Bone.select`, `select_head`, `select_tail` removed (pose bones and edit bones have them); the legacy `action.fcurves` API is gone (channelbags, see the hub).
- Edit bones exist only in Edit Mode: store names, not `EditBone` references, across mode switches.
- Build the rig in a script that rebuilds from the bind mesh and a joint-position file, so a mesh change means a rerun, not hand edits.

## 8. Engine-ready skeletons
- Deform bones only, one root, no scale keys unless the engine supports them, no leaf bones (`add_leaf_bones=False` in FBX; glTF has `export_def_bones` off by default — turn it on), 4 weights per vertex.
- Axis and scale: Blender is Z-up, right-handed, meters; Unreal is Z-up left-handed in centimeters; Unity and glTF are Y-up. Export at scale 1.0 and check the result in the engine rather than compensating in the rig.
- Retargeting: match rest poses and bone names (or write a bone map), keep the same hierarchy depth for spine and limbs, and test with a reference clip before animating at scale.

## Verify
Range-of-motion action (every joint to its limits, fingers, face shapes) rendered and Read · no candy-wrap at 180° wrist twist · weights normalized, ≤ 4 influences where the engine requires it · IK/FK snaps both ways without a pop · rig rebuild script reruns cleanly · export re-imported with the same bone count, rest pose and a test clip · Blender version reported.

Sources (checked 2026-10-05): https://developer.blender.org/docs/release_notes/5.0/animation_rigging/ · https://developer.blender.org/docs/release_notes/5.0/python_api/ · https://developer.blender.org/docs/release_notes/5.1/animation_rigging/ · https://developer.blender.org/docs/release_notes/5.2/animation_rigging/ · https://developer.apple.com/documentation/arkit/arfaceanchor/blendshapelocation (ARKit names) · https://github.com/KhronosGroup/glTF-Blender-IO
