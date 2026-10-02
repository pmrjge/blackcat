# robotics-engineer method (moved from its prompt)

The real-robot safety rules stay in the agent's prompt and always apply: nothing moves a real robot without the user's consent through ASK USER; simulation first; never disable limits, watchdogs or safety controllers.

1. Spec: robot (URDF/MJCF, DOF, sensors, actuators), ROS 2 distro and middleware, task, rates and latency budget, success metric.
2. Frames and units first (REP 103, REP 105); check the tf tree before debugging anything that moves.
3. Build in simulation with the real interfaces (ros2_control, same topics and QoS), then swap the hardware interface.
4. Verify: unit tests, rosbag replay with metrics, closed-loop sim tests across seeds and perturbations; success rate with a confidence interval, not a single run.
5. Learning: datasets and policies via mcp__huggingface, runs tracked (mcp__wandb or local logs), long runs waited on with a Monitor until-loop.
