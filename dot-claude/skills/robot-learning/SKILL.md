---
name: robot-learning
description: Load before training or evaluating a robot policy or setting up a simulator for learning — MuJoCo/MJX, Isaac Lab, ManiSkill, Gymnasium, RL, imitation learning, VLAs, LeRobot, sim-to-real.
---
# Robot learning

## Scope and baseline
- Covers learned control: simulators, RL, imitation learning and VLA fine-tuning, data collection and sim-to-real. Classical control and ROS in `robotics-engineering`; experiment protocol in `ml-experiment`; training failures in `training-debug`; dataset hygiene in `dataset-curation`.
- Versions (GitHub releases, Sep 2026): MuJoCo 3.14.0, LeRobot 0.6.1. These move fast — read the current README/changelog (mcp__libdocs, mcp__huggingface) before writing code against them.
- Hardware split: MuJoCo (CPU; MJX on JAX; MuJoCo Warp on NVIDIA) and small policies run on the Mac; Isaac Sim / Isaac Lab need an NVIDIA GPU host on Linux (or Windows) — never plan them for Apple Silicon.

## Simulators
| Simulator | Use | Notes |
|---|---|---|
| MuJoCo (`uv add mujoco`) | contact-rich manipulation and locomotion, fast CPU sim, `mujoco.viewer` | MJCF models; MuJoCo Menagerie has curated robot models; MJX/MuJoCo Playground for GPU-parallel RL in JAX |
| Isaac Sim + Isaac Lab | GPU-parallel RL at thousands of envs, photoreal rendering, sensors | NVIDIA only; USD assets; rsl_rl/skrl/RL-Games trainers integrated |
| ManiSkill (SAPIEN) | GPU-parallel manipulation benchmarks | good baselines and demos |
| Gazebo | ROS 2-integrated system tests | not a fast RL simulator |
| Genesis, PyBullet | alternatives; PyBullet is legacy | check maintenance before adopting |
- Check physical plausibility before training: masses and inertias, joint limits and damping, actuator gear/force ranges, contact parameters (`solref`/`solimp` in MuJoCo), timestep vs control decimation (e.g. 500 Hz physics, 50 Hz policy).

## Environment conventions (Gymnasium)
- `obs, info = env.reset(seed=s)`; `obs, reward, terminated, truncated, info = env.step(a)`. **terminated** = true terminal state (no bootstrap), **truncated** = time limit (bootstrap from V(s')). Mixing them biases value estimates.
- Normalize observations (running mean/std, saved with the policy), scale actions to [-1, 1] and map to joint targets inside the env; keep action and observation specs in one versioned config.
- Vectorize (`gymnasium.vector`, or native GPU batching) and seed every env deterministically.

## Reinforcement learning
- Algorithms: PPO for on-policy with massive parallel sim (legged locomotion, dexterous hands), SAC/TD3 for sample-efficient off-policy on CPU sims. Libraries: Stable-Baselines3 (reliable baselines), CleanRL (single-file, readable), rsl_rl (legged, Isaac Lab), skrl, Brax/MJX PPO (JAX).
- Rewards: dense shaping terms with documented weights, plus the sparse task success you actually report; log every reward term separately; watch for reward hacking in rendered rollouts, not just curves.
- Curriculum (terrain, object randomization ranges) and asymmetric actor-critic (privileged critic observations in sim) are standard for sim-to-real.
- Sanity: random-policy and scripted baselines; returns go up on a trivially easy variant first; fixed seeds ×3+ before claiming a difference.

## Imitation learning and VLAs
- Behavior cloning with action chunking: ACT (transformer + CVAE, chunked actions), Diffusion Policy (denoised action sequences; robust multimodality), VQ-BeT. Temporal ensembling or receding-horizon execution smooths chunks.
- Vision-language-action models: open-weight families such as π0/π0.5 (openpi), SmolVLA (in LeRobot), OpenVLA, GR00T N1.x — fine-tune from a checkpoint on your embodiment's data rather than training from scratch; check each model's license, action space and camera requirements on its model card (mcp__huggingface).
- Data quality beats quantity: consistent teleoperation strategy, 50+ successful episodes for a narrow task (more for generalization), varied initial conditions, synchronized cameras and joint states, failed episodes labeled or removed.

## LeRobot
- Datasets in the LeRobotDataset format on the Hugging Face Hub (parquet + videos + metadata; episodes, fps, features); visualize before training.
- Recording, training and evaluation go through LeRobot's command-line entry points and config system — their names and flags changed across 0.x releases, so read `--help` and the README of the installed version (`uv pip show lerobot`).
- Supported low-cost hardware (SO-100/SO-101 arms, Koch, LeKiwi and others): calibrate motors first, check joint ranges, keep the leader–follower teleop latency low. Real-robot evaluation follows the safety rules in `robotics-engineering`.

## Sim-to-real
- Domain randomization: masses, friction, damping, motor strength, latency (0–40 ms), observation noise, camera pose and lighting for vision; randomize what you cannot identify, identify what you can (system identification of actuators; actuator networks for series-elastic or geared motors).
- Match control frequency, action filtering and observation delay between sim and robot; clip actions to safe ranges on the robot side too.
- Deploy with a safety layer: joint/velocity limits, torque limits, watchdog, and a human-held e-stop; first real runs at reduced gains.
- Residual RL or real-world fine-tuning only with automatic resets and supervision.

## Evaluation
- Success rate over N rollouts per condition (N ≥ 50 in sim when possible; real-robot N as the budget allows), with a Wilson 95 % interval; fixed seeds and a held-out set of initial conditions/objects/scenes. Never pick the checkpoint on the evaluation set.
- Report: task definition, success criterion, N, success ± CI, episode length, failure-mode breakdown from videos, compute and wall time, sim vs real gap.

## Compute and tracking
Policy training in PyTorch (MPS on the Mac for small models, CUDA host for large or vision-heavy); JAX for MJX/Brax. Track runs (mcp__wandb or local logs) with configs, seeds and git commit; store checkpoints and rollout videos with the run.

## Checklist
Env conventions correct (terminated vs truncated) · model physically plausible · baselines run · ≥3 seeds or N ≥ 50 rollouts with CIs · randomization documented · safety layer present before real deployment · data, config and code versions recorded.
