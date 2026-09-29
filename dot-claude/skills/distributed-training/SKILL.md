---
name: distributed-training
description: Load before training on more than one GPU or node — torchrun, DDP vs FSDP2 (fully_shard), mixed precision, activation checkpointing, DCP checkpoints, NCCL, JAX sharding.
---
# Distributed training

## Scope
Scaling a working single-GPU training loop across GPUs/nodes. Model and loop design → the dl-engineering skills (`diffusion-flow-models`, `training-debug`); LLM fine-tuning recipes → `llm-finetuning`; throughput/speed claims → `accelerator-perf`; host drivers/containers → `linux-workstation`, `container-images`; single-Mac MLX training stays in `llm-finetuning`/`local-llm-serving`. Versions (2026-09-29): PyTorch 2.14.0, Accelerate 1.15, DeepSpeed 0.19.7, JAX 0.11.2, Flax 0.12.10. Docs pages under `docs/stable/` redirect to `docs/2.14/`.

## 1. Decide by memory math first
Per parameter with AdamW in mixed precision: bf16 params 2 B + fp32 master 4 B + grads 2–4 B + Adam m, v 8 B ≈ **16–18 B/param**, plus activations (batch × seq × hidden × layers; activation checkpointing trades ~30% compute for most of it).
| Fits on one GPU? | Choose |
|---|---|
| Yes, with room | single GPU + gradient accumulation; add DDP only for speed |
| Model fits, optimizer state doesn't | FSDP2 (shards params, grads, optimizer state across ranks) |
| Doesn't fit even sharded on one node | FSDP2 + CPU offload, or 2-D (FSDP × tensor parallel) via torchtitan; DeepSpeed ZeRO-3 offload/NVMe if needed |
| LoRA/QLoRA fine-tune | often single GPU; else DDP/FSDP through Accelerate/TRL (`llm-finetuning`) |

Prove the single-GPU run first (loss decreasing, a tiny overfit test) before scaling.

## 2. Launch with torchrun
```bash
torchrun --standalone --nproc-per-node=gpu train.py                    # one node, all GPUs
torchrun --nnodes=2 --nproc-per-node=8 --rdzv-backend=c10d \
         --rdzv-endpoint=$HOST:29400 --rdzv-id=$JOB --max-restarts=3 train.py   # same command on each node
```
Workers get `RANK`, `LOCAL_RANK`, `WORLD_SIZE`, `LOCAL_WORLD_SIZE`, `MASTER_ADDR`, `MASTER_PORT`, `TORCHELASTIC_RESTART_COUNT`. Read `LOCAL_RANK` from the environment (`--local-rank` is passed only in the legacy path). `RANK` is not stable across restarts; on any failure all workers restart from the last checkpoint.
```python
dist.init_process_group("nccl"); torch.cuda.set_device(int(os.environ["LOCAL_RANK"]))
sampler = DistributedSampler(ds, shuffle=True, drop_last=True); sampler.set_epoch(epoch)   # every epoch
```
Log, evaluate-print and save only on rank 0 (but every rank participates in collectives and DCP saves). `dist.destroy_process_group()` at exit.

## 3. DDP
`DDP(model, device_ids=[local_rank])`; gradient accumulation with `with model.no_sync():` on non-final micro-steps; `find_unused_parameters=True` only if needed (slow); SyncBatchNorm for small per-GPU batches. Effective batch = per-GPU × accumulation × world size — rescale LR/warmup when it changes.

## 4. FSDP2 (`fully_shard`)
```python
from torch.distributed.fsdp import fully_shard, MixedPrecisionPolicy, CPUOffloadPolicy
mp = MixedPrecisionPolicy(param_dtype=torch.bfloat16, reduce_dtype=torch.float32)
for block in model.layers:                       # bottom-up: each transformer block first...
    fully_shard(block, mp_policy=mp)
fully_shard(model, mp_policy=mp)                 # ...then the root (embeddings, head)
optim = torch.optim.AdamW(model.parameters(), lr=lr)   # build AFTER sharding: params are now DTensors
```
- Parameters become `DTensor`s sharded on dim 0 in place; FQNs unchanged. Call `model(x)`, not `model.forward(x)` (or `register_fsdp_forward_method`).
- `reshard_after_forward`: default True for blocks, False for the root; `False` trades memory for no re-all-gather in backward; an `int` reshards to a smaller (intra-node) group.
- Gradient accumulation: `model.set_requires_gradient_sync(False)` on non-final micro-steps (FSDP1's `no_sync`); `set_is_last_backward` for microbatching schedules.
- `CPUOffloadPolicy(pin_memory=True)` offloads params, grads and optimizer state (the optimizer step runs on CPU — slow, last resort).
- Mixed precision: bf16 compute with fp32 reduction is the default choice; fp16 needs loss scaling (check GradScaler support with DTensor on your PyTorch version) — prefer bf16; low precision (fp8/MX) through torchao after the bf16 run is stable.
- Activation checkpointing per block (`torch.utils.checkpoint` with `use_reentrant=False`, or torchtitan's AC options) before sharding the root; `torch.compile` per block after correctness is confirmed.
- FSDP1 (`FullyShardedDataParallel` wrapper, `FlatParameter`) is legacy; migrate to `fully_shard` (torchtitan `docs/fsdp.md` maps the options).

## 5. Checkpointing (test resume before the long run)
```python
import torch.distributed.checkpoint as dcp
from torch.distributed.checkpoint.state_dict import get_state_dict, set_state_dict, StateDictOptions
msd, osd = get_state_dict(model, optim)
dcp.save({"model": msd, "optim": osd, "step": step}, checkpoint_id=f"ckpt/step_{step}")
# resume: build + shard model/optim identically, then
msd, osd = get_state_dict(model, optim); state = {"model": msd, "optim": osd}
dcp.load(state, checkpoint_id=path); set_state_dict(model, optim, model_state_dict=state["model"], optim_state_dict=state["optim"])
```
- DCP writes one shard set per rank and **reshards at load time** (different world size or parallelism is fine). `dcp.async_save` (experimental) overlaps saving with training; wait on the returned future before the next save.
- Also save RNG states, dataloader/sampler position, LR scheduler and grad scaler; a `Stateful` object's `state_dict`/`load_state_dict` are called by DCP.
- Export a consolidated file for inference with `StateDictOptions(full_state_dict=True, cpu_offload=True)` on rank 0, or `torch.distributed.checkpoint.format_utils.dcp_to_torch_save` offline.
- Cadence from expected failure rate (e.g. every 30–60 min); keep the last N; do a kill-and-resume test in the first hour and verify the loss curve continues.

## 6. NCCL and hangs
- Topology: `nvidia-smi topo -m` (NVLink vs PCIe vs across sockets); consumer RTX cards lack NVLink and P2P may be disabled — expect slower all-reduce.
- Debug: `NCCL_DEBUG=INFO` (`WARN` in production), `TORCH_DISTRIBUTED_DEBUG=DETAIL`, `TORCH_NCCL_ASYNC_ERROR_HANDLING=1`; `init_process_group(timeout=timedelta(minutes=10))` so hangs become errors; py-spy dump on each rank to find the stuck collective.
- Classic hang: rank-divergent control flow (a rank skips a collective — early `break`, data-dependent `if`, uneven last batch). Use `drop_last=True`, identical loop counts, and all-reduce any "should stop" flag.
- Multi-node: `NCCL_SOCKET_IFNAME` to pick the NIC, same NCCL/CUDA/PyTorch versions on every node, open ports, clocks in sync.
- Inside containers: `--ipc=host` or a large `--shm-size`, `--gpus all`, and the host's IB/RDMA devices if used.

## 7. Determinism and data
Seed per rank (`base_seed + rank`) for augmentation, identical for model init (or broadcast from rank 0); shard data by rank (sampler or streaming dataset shards); `persistent_workers=True`, `pin_memory=True`; validate that no two ranks see the same sample within an epoch.

## 8. JAX / Flax
`mesh = jax.make_mesh((n_data, n_model), ("data", "model"))`; `NamedSharding(mesh, PartitionSpec("data"))` for batches, parameter shardings via annotations (Flax NNX `nnx.with_partitioning`); `jax.jit` with `in_shardings`/`out_shardings` or sharding constraints; multi-host `jax.distributed.initialize()`; checkpoints with Orbax (sharded, restorable to a different mesh). Check the current JAX sharding docs — APIs move between minor versions.

## 9. Frameworks
torchtitan (reference FSDP2/TP/PP/CP recipes for LLM pre-training), HF Accelerate (`accelerate config` → FSDP2 or DeepSpeed backends; good for HF models), DeepSpeed (ZeRO-3 with CPU/NVMe offload), Lightning Fabric. Pick one; don't mix launchers.

## 10. Scaling check (report it)
Tokens or samples/s per GPU at 1, 2, N GPUs; scaling efficiency = throughput_N / (N × throughput_1); MFU if the model's FLOPs are known; peak memory per rank (`torch.cuda.max_memory_allocated`). Losses at equal effective batch should match the single-GPU run within noise over the first few hundred steps — otherwise suspect sampler, LR scaling or reduction dtype.

Sources (checked 2026-09-29): https://docs.pytorch.org/docs/2.14/distributed.fsdp.fully_shard.html · https://docs.pytorch.org/docs/2.14/distributed.checkpoint.html · https://docs.pytorch.org/docs/2.14/elastic/run.html · https://docs.pytorch.org/tutorials/intermediate/FSDP_tutorial.html · https://github.com/pytorch/torchtitan/blob/main/docs/fsdp.md · https://github.com/pytorch/pytorch/releases (v2.14.0, 2026-09-02) · https://github.com/huggingface/accelerate/releases · https://github.com/deepspeedai/DeepSpeed/releases · https://github.com/jax-ml/jax/releases
