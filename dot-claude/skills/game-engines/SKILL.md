---
name: game-engines
description: Use for Godot, Unity, Unreal or Bevy — project structure, scripting, engine tests, headless builds.
---
# Game engines

Baseline rules (frame budget, profiling, consent for publishing): `game-graphics`.

## Versions
- Godot 4.7.2-stable — Verified 2026-10-02 https://github.com/godotengine/godot/releases/latest
- Bevy 0.19.1 (breaking changes every minor: follow the migration guide) — Verified 2026-10-02 https://github.com/bevyengine/bevy/releases/latest
- Unity 6.3 is the newest LTS line (exact build unverified) — https://unity.com/releases/unity-6/support
- Unreal Engine 5.8 is the newest release (announcement seen only in search results: unverified) — https://forums.unrealengine.com/t/unreal-engine-5-8-released/2729274
- Engine versions are pinned per project (`project.godot` features, `ProjectSettings/ProjectVersion.txt`, `.uproject` EngineAssociation, `Cargo.toml`); upgrading an engine is a separate task with a backup branch.

## Choosing
| need | pick |
|---|---|
| 2D or small/mid 3D, open source, fast iteration, scripting in GDScript or C# | Godot |
| broad platform reach incl. mobile/consoles, large asset ecosystem, C# | Unity |
| high-end 3D, large worlds, C++ and Blueprints, Nanite/Lumen | Unreal |
| code-first Rust, ECS, custom engines and tools | Bevy (or wgpu directly) |

## Godot 4
- Scenes and nodes; composition over deep inheritance; signals for decoupling; autoloads only for true singletons.
- GDScript with static types (`var speed: float = 4.0`, typed arrays) — faster and checked; C# for heavy logic where the project uses .NET.
- `_physics_process(delta)` for physics (fixed rate), `_process` for visuals; `CharacterBody3D.move_and_slide()`.
- Resources (`.tres`) for data; `@export` for designer-tunable values; never load large resources in hot paths (`preload` or background `ResourceLoader.load_threaded_request`).
- Headless: `godot --headless --path . --export-release "<preset>" build/game` (needs export templates of the same version); tests with GUT or gdUnit4 via `godot --headless -s`.
- GDExtension (C++/Rust via godot-rust) for native performance.

## Unity 6
- Scripts as `MonoBehaviour` for scene glue, plain C# classes and ScriptableObjects for logic and data; DOTS/ECS (Entities) for very many entities.
- Avoid per-frame allocations (LINQ, boxing, string concat in `Update`); cache component lookups; object pooling (`UnityEngine.Pool`).
- Render pipelines: URP (most projects) or HDRP; don't mix shaders between them.
- Addressables for content loading; assembly definitions to cut compile times.
- Batch builds: `Unity -batchmode -quit -projectPath . -executeMethod Build.PerformBuild -logFile build.log`; tests: `-runTests -testPlatform EditMode|PlayMode -testResults results.xml`. Unity licensing (Personal/Pro, seat activation) applies to CLI runs: check before automating.
- `.meta` files always committed with their assets; Force Text serialization; Smart Merge (UnityYAMLMerge) configured for git.

## Unreal Engine 5
- C++ for systems, Blueprints for content and iteration; expose C++ to Blueprints with `UFUNCTION(BlueprintCallable)`/`UPROPERTY(EditAnywhere)`; never hold raw pointers to UObjects without `UPROPERTY` or `TWeakObjectPtr` (GC).
- Gameplay Framework (GameMode, PlayerController, Pawn, GameState) and the Gameplay Ability System for ability-heavy games; Enhanced Input.
- Builds: `RunUAT.sh BuildCookRun -project=Game.uproject -platform=Mac -clientconfig=Development -build -cook -stage -pak -archive -archivedirectory=out/`; automation tests with `UnrealEditor-Cmd Game.uproject -ExecCmds="Automation RunTests Game" -unattended -nullrhi`.
- Large binary assets: git LFS or Perforce as the project uses; never commit `Binaries/`, `Intermediate/`, `Saved/`, `DerivedDataCache/`.

## Bevy
- ECS: components are plain data, systems are functions over queries, resources for globals, events/observers for messages; schedules (`Startup`, `Update`, `FixedUpdate`) and system ordering explicit (`.chain()`, `.before/.after`).
- Plugins per feature; states for menus/game flow; assets via `AssetServer` handles.
- Fast iteration: dynamic linking feature in dev only; `cargo run --release` for performance checks.
- Tests: build a minimal `App` with the plugin under test, `app.update()`, assert on the `World`.

## Pitfalls
Upgrading an engine in place; editor-only code in runtime builds; physics in variable-step callbacks; forgetting export templates/SDK versions match the engine; Unity `.meta` loss breaking references; Unreal hot reload corrupting Blueprints (use Live Coding, restart on header changes).

## Verify
Headless build for the target succeeds · engine tests (GUT/gdUnit4, Unity Test Framework, Unreal Automation, cargo test) green · profiler capture for performance work · engine version reported.
