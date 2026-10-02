# Remote NVIDIA hosts, Kaggle and remote Jupyter (moved from the cuda-engineer prompt)

Read by cuda-engineer, dl-engineer, llm-engineer and ml-engineer before working on a remote NVIDIA host or Kaggle. The consent gates live in each agent's prompt and are restated here: only a host the user or project docs name; paid instances, multi-hour jobs, `competitions submit` and public kernels need the user's consent (ASK USER).

## SSH hosts
- Reach a host only by its `~/.ssh/config` alias; never copy, print or move keys; never guess or provision a host.
- Preflight: `ssh <host> nvidia-smi`, plus the driver, CUDA runtime and `torch.version.cuda` from the project's environment on the host.
- Move code and data with `rsync`; run long jobs under `tmux` or `nohup … > run.log 2>&1 &` and wait on them with a Monitor until-loop on the log; one job per GPU (check `nvidia-smi` for other processes first).
- Remote Jupyter: `ssh -N -L <port>:localhost:<port> <host>` and the `jupyter` CLI, nbclient or papermill.
- Kill every process you started, remote ones included; report GPU time used.

## Kaggle
- CLI through `uvx kaggle`: `competitions download`, `kernels push|status|output`. Never print credentials (`KAGGLE_API_TOKEN`, `~/.kaggle/`).
- `competitions submit` and a public kernel are publishing: ASK USER first. Obey each competition's rules on external data and internet access.
- Web-only UIs (the Kaggle editor, Colab, cloud consoles): NEXT: browser-operator with the exact steps.
