---
name: container-images
description: Use for Dockerfiles and images — multi-stage, digests, non-root, multi-arch, SBOM, hadolint, trivy.
---
# Container images

## Scope
Building images. Running them on the home server (compose, Podman quadlets, systemd, backups) → `self-hosting-ops`; CI jobs that build them → `ci-cd-pipelines`; CUDA driver/toolkit matching on the host → `linux-workstation`; secret handling in general → `secure-coding`.

## Dockerfile baseline
```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.13-slim@sha256:<digest> AS build
...
FROM python:3.13-slim@sha256:<digest>
RUN useradd --system --uid 10001 --no-create-home app
COPY --from=build --chown=app:app /app /app
USER 10001
ENTRYPOINT ["/app/.venv/bin/myapp"]      # exec form: PID 1 gets signals
```
- First line `# syntax=docker/dockerfile:1` (current stable frontend; enables `RUN --mount`, heredocs).
- Layer order = change frequency: base → system packages → dependency manifests + install → source. Copy lockfiles before source so code edits don't reinstall dependencies.
- `.dockerignore`: `.git`, `.venv`, `node_modules`, `target`, `*.env`, secrets, build outputs. The build context is uploaded whole otherwise, and `COPY . .` bakes it in.
- One concern per image; exec-form `ENTRYPOINT`/`CMD`; `exec "$@"` at the end of entrypoint scripts; add `tini` (or `docker run --init`) when the app spawns children and doesn't reap them.
- `HEALTHCHECK` only with a real probe command that exists in the image (distroless has no curl).

## Base images
| Base | Use | Trade-off |
|---|---|---|
| `*-slim` (Debian) | default for Python/Node | shell + apt available for debugging |
| Alpine | small static tools | musl: slower Python wheels/compat issues, DNS quirks |
| distroless / `gcr.io/distroless/*`, Chainguard | runtime-only | no shell or package manager; debug with `:debug` tags or a sidecar |
| Docker Hardened Images (`dhi.io`, Docker Hub) | hardened Debian/Alpine runtime bases | free under Apache 2.0 since 2025-12-17, SBOM + SLSA L3 provenance; distroless-style runtime |
| `nvidia/cuda:<ver>-runtime-*` vs `-devel-*` | GPU apps | build in `devel`, ship on `runtime`; match the host driver (`linux-workstation`) |

- Pin `FROM name:tag@sha256:<index digest>`; get it with `docker buildx imagetools inspect name:tag` (the index `Digest:`, multi-arch). Renovate updates tag + digest together.

## BuildKit mounts (instead of layers you then delete)
```dockerfile
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && apt-get install -y --no-install-recommends build-essential
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc pnpm install --frozen-lockfile
RUN --mount=type=ssh git clone git@forge:org/private.git
```
Build with `docker buildx build --secret id=npmrc,src=$HOME/.npmrc --ssh default .`. Never pass secrets via `ARG`/`ENV` or `COPY` them: they persist in layers and `docker history`. Cargo: cache `/usr/local/cargo/registry` plus the target dir (or cargo-chef for a dependency layer); Go: `/go/pkg/mod` and `/root/.cache/go-build`; npm: `/root/.npm`.

## Language recipes
- **Python + uv** (uv docs, uv 0.12.x):
  ```dockerfile
  COPY --from=ghcr.io/astral-sh/uv:0.12.20 /uv /uvx /bin/
  ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 UV_PYTHON_DOWNLOADS=0
  WORKDIR /app
  RUN --mount=type=cache,target=/root/.cache/uv \
      --mount=type=bind,source=uv.lock,target=uv.lock \
      --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
      uv sync --locked --no-install-project --no-editable
  COPY . /app
  RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-editable
  ```
  Final stage: same Python base, `COPY --from=build /app/.venv /app/.venv`, run `/app/.venv/bin/<entry>`. Add `.venv` to `.dockerignore`. Workspaces: first sync with `--frozen --no-install-workspace`.
- **Node + pnpm**: copy `pnpm-lock.yaml`, `pnpm fetch` with a cache mount on the store, then copy source and `pnpm install --offline --frozen-lockfile`; `pnpm deploy --prod` for a pruned runtime tree.
- **Rust**: cargo-chef (`cargo chef prepare` / `cook --release`) or cache mounts; static musl or distroless `cc` runtime.
- **Compiled apps**: build stage with toolchains; runtime stage with only the binary, CA certs and tzdata if needed.

## Multi-arch
- `docker buildx build --platform linux/amd64,linux/arm64 -t reg/app:1.2 --push .` (push is the user's step; locally use `--load` for one platform or `-o type=oci,dest=app.tar`).
- On Apple Silicon, amd64 builds run under emulation: slow and occasionally wrong for JITs; prefer native builders or cross-compilation in the build stage (`FROM --platform=$BUILDPLATFORM`, `TARGETOS`/`TARGETARCH` args).
- `docker` driver needs the containerd image store for multi-platform and attestations; otherwise `docker buildx create --use` (docker-container driver).

## Runtime hardening (declare in the image, enforce at run)
Non-root numeric `USER`; no setuid binaries needed; run with `--read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges`; only needed ports; no Docker socket mounts; secrets at runtime through files/secret stores, not env baked into the image.

## Supply chain and scanning
- Provenance `mode=min` is attached by default; add `--provenance=mode=max --sbom=true` for release builds (`BUILDX_NO_DEFAULT_ATTESTATIONS=1` disables the default).
- SBOM also via `syft <image>` (v1.52); vulnerabilities via `trivy image <image>` (v0.74) or `grype <image>` (v0.119). Triage by fixable + reachable; fix by base bump before per-package pins; record accepted risks in `.trivyignore` with reasons and expiry.
- Lint: `hadolint Dockerfile` (v2.15.1; e.g. DL3008 pin apt versions — often acceptable to ignore with digests, DL3006/DL3007 untagged or `latest` base, DL4006 `pipefail` in `RUN` with pipes). Size: `dive <image>` (v0.13.1) to find fat layers.
- Reproducibility: pinned digests, lockfiles, `SOURCE_DATE_EPOCH` where the toolchain honours it.

## Verify before reporting
`docker build --check .` (build checks only, Buildx ≥ 0.15; `# check=error=true` makes findings fail) · build twice to confirm cache hits on a code-only change · `docker inspect -f '{{.Config.User}}' <img>` is non-root · smoke-test the entrypoint · image size noted · hadolint and trivy output attached.

Sources (checked 2026-09-29): https://docs.docker.com/build/building/best-practices/ · https://docs.docker.com/build/cache/optimize/ · https://docs.docker.com/build/metadata/attestations/ · https://docs.astral.sh/uv/guides/integration/docker/ · https://www.docker.com/press-release/docker-makes-hardened-images-free-open-and-transparent-for-everyone · https://github.com/hadolint/hadolint/releases · https://github.com/aquasecurity/trivy/releases · https://github.com/anchore/syft/releases · https://github.com/anchore/grype/releases · https://github.com/wagoodman/dive/releases
