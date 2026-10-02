---
name: robotics-engineering
description: Load before building or debugging robot software — ROS 2, tf2, URDF, ros2_control, Nav2, MoveIt 2, Gazebo.
---
# Robotics engineering (ROS 2, control, hardware)

## Scope and baseline
- Covers robot software, control and bring-up. Learning-based control and simulators for RL in `robot-learning`; numerical integrators and filters in `numerical-methods`; C++ builds in `cmake-ninja-builds`.
- ROS 2 distros (endoflife.date, Sep 2026): **Lyrical Luth** (May 2026, LTS, EOL May 2031), **Jazzy Jalisco** (May 2024, LTS, EOL May 2029), Kilted Kaiju (May 2025, EOL Dec 2026). Humble Hawksbill (May 2022, LTS) is supported until May 2027 — plan migrations off it. New work: Jazzy or Lyrical on their tier-1 Ubuntu. `printenv ROS_DISTRO` first.
- macOS is not a tier-1 ROS 2 platform: on the Mac use Docker (`osrf/ros:<distro>-desktop`, no GPU passthrough), a Linux VM/remote host, or RoboStack (conda-forge ROS via pixi — check the distro is published for osx-arm64). MuJoCo and pure-Python tooling run natively.
- Nav2 1.5.x and Gazebo (the new Gazebo; Gazebo Classic reached end of life in Jan 2025) pair with specific distros — follow the ROS docs' pairing table (Jazzy ↔ Gazebo Harmonic).

## Safety first
- Simulation before hardware, always. On hardware: reduced velocity/acceleration/torque limits, a reachable e-stop, a clear workspace, the user present and consenting to that specific motion.
- Never bypass limits, watchdogs, safety controllers or collision checking to make something work. A node that commands motion must stop the robot on timeout (command watchdog) and on shutdown.
- Nothing is published to a real robot's command interfaces without the user's consent (a subagent returns STATUS: blocked, NEXT: ASK USER; BlackCat asks with AskUserQuestion).

## Workspace and build
```bash
mkdir -p ~/ws/src && cd ~/ws
vcs import src < deps.repos            # pinned repos
rosdep install --from-paths src --ignore-src -y
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
source install/setup.bash              # every new shell
colcon test --packages-select my_pkg && colcon test-result --verbose
```
- Packages: `ament_cmake` (C++) or `ament_python`; `package.xml` format 3 with every dependency declared (rosdep resolves them). `--packages-up-to`, `--packages-select`, `--event-handlers console_direct+` for debugging builds.
- Never source two workspaces' setups in the wrong order (underlay first, overlay last); rebuild after switching branches that change interfaces.

## Nodes and communication
- rclcpp / rclpy nodes; components (composition) for zero-copy intra-process pipelines; lifecycle (managed) nodes for anything hardware-facing (configure → activate → deactivate → cleanup).
- Executors and callback groups: a long callback blocks everything in a single-threaded executor; use `MultiThreadedExecutor` with `MutuallyExclusive`/`Reentrant` groups deliberately. Never sleep in callbacks; use timers.
- Parameters: declare with types and descriptors, load from YAML (`--ros-args --params-file`), validate with parameter callbacks.
- **QoS** is the #1 silent failure: publisher and subscriber profiles must be compatible (`ros2 topic info -v /topic` shows both). Sensor streams: `SensorDataQoS` (best effort, small depth). Latched data (`/map`, `/robot_description`): `transient_local` durability on both sides. Commands: reliable, depth 1–10.
- Interfaces: define `.msg/.srv/.action` in a dedicated `*_interfaces` package. Actions for long goals with feedback and cancel (navigation, trajectories).
- Middleware: default Fast DDS; Cyclone DDS or Zenoh (`rmw_zenoh`) are alternatives (`RMW_IMPLEMENTATION=…`); all nodes of a system on the same RMW. Isolation: `ROS_DOMAIN_ID`, `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` (replaces `ROS_LOCALHOST_ONLY`).
- Launch: Python launch files with `DeclareLaunchArgument`, `IncludeLaunchDescription`, `ComposableNodeContainer`, namespaces and remappings; YAML launch for simple cases.

## Frames, models, time
- REP 103 (SI units, right-handed, x forward, y left, z up; ENU for world) and REP 105 (`map → odom → base_link → sensors`). One publisher per transform.
- `ros2 run tf2_tools view_frames`, `ros2 run tf2_ros tf2_echo a b`; lookups at the message stamp, with a timeout; never `Time(0)` silently when timing matters.
- URDF via xacro; `robot_state_publisher` publishes link transforms from `/joint_states`; inertials must be physically plausible (positive definite, realistic masses) or simulators explode. SDF for Gazebo worlds, MJCF for MuJoCo (convert with care; check joint axes, limits, damping).
- Simulation time: `use_sim_time:=true` on every node when a simulator publishes `/clock`.

## ros2_control
- `controller_manager` + hardware interface plugin (`SystemInterface` read/write at the update rate) + controllers (`joint_trajectory_controller`, `diff_drive_controller`, `forward_command_controller`, `joint_state_broadcaster`). The same controllers run against `gz_ros2_control` in sim and your hardware plugin on the robot.
- Real time: the update loop must not allocate or block; Linux PREEMPT_RT (mainline since 6.12) plus CPU isolation for hard timing; measure jitter (cyclictest) before trusting 1 kHz loops.

## Navigation and manipulation
- Nav2: map server or SLAM Toolbox (mapping/localization), AMCL, costmaps (inflation radius vs robot footprint), planners (NavFn, Smac Hybrid-A*/Lattice), controllers (Regulated Pure Pursuit, MPPI, DWB), behavior trees, lifecycle manager. Tune on recorded bags and in sim; log `cmd_vel` vs odometry.
- robot_localization EKF/UKF: fuse wheel odometry, IMU and GPS with correct covariances; set `two_d_mode` for ground robots; one EKF per frame pair.
- MoveIt 2: MoveGroup / MoveItPy, planning pipelines (OMPL, Pilz industrial for LIN/PTP/CIRC, STOMP), collision objects, IK solvers (KDL, TRAC-IK, pick_ik), MoveIt Servo for teleop/visual servoing, time parameterization (TOTG or Ruckig).

## Kinematics, dynamics, control
- Kinematics: product-of-exponentials or DH (state which convention); Jacobians (geometric vs analytic); singularities (watch σ_min of J, use damped least squares `Δq = Jᵀ(JJᵀ + λ²I)⁻¹e`); redundancy via null-space projection.
- Dynamics: Pinocchio (RNEA inverse dynamics, ABA forward, CRBA mass matrix, analytic derivatives) or Drake (multibody, trajectory optimization, systems framework). Validate with energy conservation in a passive simulation.
- Control:
  - PID: derivative on measurement with low-pass filtering, anti-windup (clamping or back-calculation), feedforward (gravity, friction) first; tune at the real sample rate.
  - LQR on a linearization (`scipy.linalg.solve_continuous_are`/`solve_discrete_are`, python-control); check controllability and closed-loop poles.
  - MPC: acados or CasADi (+ IPOPT/OSQP); budget solve time below the control period with margin; warm-start; handle infeasibility (soft constraints).
  - Impedance/admittance for contact; whole-body QP control for humanoids and legged robots.
- Trajectories: quintic/trapezoidal profiles, TOPP-RA for time-optimal paths under limits, Ruckig for online jerk-limited motion.

## Estimation, calibration, perception
- Kalman family: linear KF, EKF (Jacobians checked numerically), UKF, error-state EKF for IMU orientation; factor graphs (GTSAM) for SLAM/VIO smoothing. Always check NEES/NIS consistency on logged data.
- Calibration: camera intrinsics (OpenCV / `camera_calibration`), camera–IMU (Kalibr), hand–eye (`cv2.calibrateHandEye`), time offsets between sensors.
- Perception: OpenCV, Open3D/PCL, depth cameras (align depth to color), AprilTag detection, learned detectors; synchronize with `message_filters` ApproximateTime; publish with correct frame_id and stamp.

## Embedded and hardware bring-up
- micro-ROS on microcontrollers (serial/UDP agent), CAN via SocketCAN (`candump`, `cansend`), EtherCAT masters for industrial drives, serial protocols with checksums and timeouts.
- Bring-up order: power and e-stop → communication (read-only) → sensor data sanity → single joint at low gain → full controller in a safe pose → task.
- Keep firmware, driver and URDF versions recorded together.

## Debugging and testing
- `ros2 doctor --report`, `ros2 node info`, `ros2 topic hz/bw/echo --once`, `rqt_graph`, RViz2, Foxglove Studio; `ros2 bag record -o run1 /topics…` (MCAP storage) and replay with `--clock` for regression tests.
- Tests: gtest/pytest per package, `launch_testing` for multi-node behavior, simulation scenarios in CI (headless Gazebo or MuJoCo), metrics over many seeds with confidence intervals.

## Agent access in this stack
The `ros` catalog server (ros-mcp over rosbridge) is mounted by mcp-broker on request; every call asks the user because it can move hardware. Prefer the ros2 CLI through Bash on a simulator for development.

## Checklist
Distro and RMW recorded · frames per REP 103/105 and tf tree checked · QoS compatible · sim-first evidence with metrics · limits and watchdogs intact · real-robot step explicitly approved · bags and launch commands to reproduce.
