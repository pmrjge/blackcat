# Equilibrium harness check image: Linux arm64, Lean 4.34.1 + Mathlib v4.34.1 (rev d13f23b7), uv + CPython 3.14.8.
# Build: bash build.sh --set full (user-run; Apple `container build`). No `# syntax=` line on purpose: it would pull a frontend image by tag.
#
# Pins (each verified 2026-10-04 against the upstream release; see PINS):
#  - base image by digest (index digest; arm64 variant da496358...), see the NOTE below.
#  - Lean toolchain: official release tarball lean-4.34.1-linux_aarch64.tar.zst, sha256 from the GitHub release asset
#    digest and re-computed locally on a downloaded copy (both fdb974c2...). No elan.
#  - uv 0.12.22 release tarball (sha256 from the GitHub release), CPython 3.14.8 python-build-standalone tag 20261001
#    (sha256 from the release SHA256SUMS). 3.14.8 is what `uv run --no-project python` selects on the host (checked);
#    CP/CR/ES oracles only declare requires-python >=3.10 / >=3.11, so no stricter pin exists in the pools.
#  - Mathlib: the host project's lakefile.toml + lake-manifest.json (sha256 in project/SHA256SUMS), rev d13f23b7 =
#    tag v4.34.1 (checked against the GitHub tag). `lake exe cache get` fetches prebuilt oleans at BUILD time only.
#  - Debian packages: apt snapshot of the base image's build date (APT_SNAPSHOT), so package versions are fixed.
# Run time: no network, non-root (10001:10001), nothing outside /tmp and the bind-mounted check copy is writable.

# NOTE (base digest): looked up 2026-10-04 from docker-library/repo-info (repos/debian/remote/trixie-slim.md, commit
# 0de62c7b, 2026-09-19), NOT from the registry (this agent cannot reach Docker Hub). A wrong digest fails the pull
# loudly, never silently (the builder verifies it when it pulls the base). To re-pin: see PINS.
ARG BASE_IMAGE=debian:trixie-slim@sha256:a99cfc517144bc59b1978475ec53b46ecabec7e43635402ee5b77cc54cd1b20a

# ---------------------------------------------------------------- base: apt pinned by snapshot date
FROM ${BASE_IMAGE} AS base
ARG APT_SNAPSHOT=20260918T000000Z
ENV DEBIAN_FRONTEND=noninteractive
# The slim base has no ca-certificates, so the snapshot is read over http; apt still verifies the signed InRelease.
RUN set -eu; \
    if [ -n "${APT_SNAPSHOT}" ]; then \
      rm -f /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list; \
      echo "deb http://snapshot.debian.org/archive/debian/${APT_SNAPSHOT}/ trixie main" > /etc/apt/sources.list; \
      echo 'Acquire::Check-Valid-Until "false"; Acquire::Retries "5";' > /etc/apt/apt.conf.d/99snapshot; \
    fi

# ---------------------------------------------------------------- tools: build-time only, not in the final image
FROM base AS tools
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git zstd xz-utils \
 && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------- fetch: pinned binaries, checksum verified
FROM tools AS fetch
ARG LEAN_VERSION=4.34.1
ARG LEAN_SHA256=fdb974c2cdb4627e090d5d4007b913e09d13c4868720fb5594e22808b3de9e37
ARG UV_VERSION=0.12.22
ARG UV_SHA256=6f66a14e8239871fb477f9746c941fedfa77e8fe28a8bc7c07e1dc7f53a66712
ARG PYTHON_VERSION=3.14.8
ARG PBS_TAG=20261001
ARG PYTHON_SHA256=4395ae16388f9d3409cba7e20161753ed3359b13d959345415029f874f675162
WORKDIR /tmp/dl
RUN set -eux; \
    curl --proto '=https' --tlsv1.2 -fsSL --retry 5 -o lean.tar.zst \
      "https://github.com/leanprover/lean4/releases/download/v${LEAN_VERSION}/lean-${LEAN_VERSION}-linux_aarch64.tar.zst"; \
    echo "${LEAN_SHA256}  lean.tar.zst" | sha256sum -c -; \
    mkdir -p /opt/lean; tar --zstd -xf lean.tar.zst -C /opt/lean --strip-components=1; \
    /opt/lean/bin/lean --version | grep -F "version ${LEAN_VERSION}"; \
    curl --proto '=https' --tlsv1.2 -fsSL --retry 5 -o uv.tar.gz \
      "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-aarch64-unknown-linux-gnu.tar.gz"; \
    echo "${UV_SHA256}  uv.tar.gz" | sha256sum -c -; \
    mkdir -p /opt/uv; tar -xzf uv.tar.gz -C /opt/uv --strip-components=1; \
    /opt/uv/uv --version | grep -F "${UV_VERSION}"; \
    curl --proto '=https' --tlsv1.2 -fsSL --retry 5 -o py.tar.gz \
      "https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/cpython-${PYTHON_VERSION}%2B${PBS_TAG}-aarch64-unknown-linux-gnu-install_only_stripped.tar.gz"; \
    echo "${PYTHON_SHA256}  py.tar.gz" | sha256sum -c -; \
    mkdir -p /opt/python; tar -xzf py.tar.gz -C /opt/python --strip-components=1; \
    [ -e /opt/python/bin/python ] || ln -s python3 /opt/python/bin/python; \
    /opt/python/bin/python3 --version | grep -F "${PYTHON_VERSION}"; \
    rm -rf /tmp/dl

# ---------------------------------------------------------------- mathlib: clone the pinned deps, fetch the olean cache
FROM tools AS mathlib
ENV PATH=/opt/lean/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin HOME=/root LANG=C.UTF-8
COPY --from=fetch /opt/lean /opt/lean
COPY project/ /opt/eq/stack_mathlib/
WORKDIR /opt/eq/stack_mathlib
ARG MATHLIB_REV=d13f23b723b8a846827a245b89c10fc7d3f11612
RUN set -eux; \
    sha256sum -c SHA256SUMS; \
    grep -F "\"rev\": \"${MATHLIB_REV}\"" lake-manifest.json; \
    grep -Fx 'leanprover/lean4:v4.34.1' lean-toolchain
# Network (build time only): github.com (git clones of the 9 locked packages), the Mathlib cache host
# (lakecache.blob.core.windows.net) and, if the toolchain asks for it, github.com release downloads of leantar.
RUN lake exe cache get
RUN set -eux; \
    printf 'import Mathlib\nexample : (2:Nat) + 2 = 4 := by norm_num\n#eval Lean.versionString\n' > /tmp/smoke.lean; \
    LP=$(lake env printenv LEAN_PATH); echo "LEAN_PATH=$LP"; \
    LEAN_PATH="$LP" lean /tmp/smoke.lean; \
    rm -f /tmp/smoke.lean
RUN set -eux; \
    cd /opt/eq/stack_mathlib/.lake/packages; \
    n=$(find . -name '*.olean' | wc -l); \
    h=$(find . -name '*.olean' | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1); \
    { echo "lean: $(lean --version)"; \
      echo "mathlib_rev: ${MATHLIB_REV}"; \
      echo "olean_files: $n"; \
      echo "olean_tree_sha256: $h"; \
      echo "olean_tree_recipe: cd .lake/packages && find . -name '*.olean' | LC_ALL=C sort | xargs sha256sum | sha256sum"; \
      echo "project_sha256sums:"; sed 's/^/  /' /opt/eq/stack_mathlib/SHA256SUMS; \
    } > /opt/eq/PROVENANCE.txt; \
    cat /opt/eq/PROVENANCE.txt; \
    rm -rf /root/.cache

# ---------------------------------------------------------------- runtime
FROM base AS runtime
RUN apt-get update \
 && apt-get install -y --no-install-recommends git jq perl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -g 10001 eq && useradd -u 10001 -g 10001 -M -d /tmp -s /usr/sbin/nologin eq \
 && mkdir -p /work /fixture /items /eqsrc/work /in /eq/tunnel \
 && git config --system --add safe.directory '*'
COPY --from=fetch /opt/lean /opt/lean
COPY --from=fetch /opt/uv /opt/uv
COPY --from=fetch /opt/python /opt/python
COPY --from=mathlib /opt/eq /opt/eq
ENV PATH=/opt/lean/bin:/opt/uv:/opt/python/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    HOME=/tmp TMPDIR=/tmp LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    EQ_LEAN_PROJECT=/opt/eq/stack_mathlib \
    UV_PYTHON=/opt/python/bin/python3 UV_PYTHON_DOWNLOADS=never UV_OFFLINE=1 UV_NO_CONFIG=1 UV_NO_PROGRESS=1 \
    UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1
# One build-time `lake env` as root and as the run user, so a missing write permission shows up here, not in the probe.
RUN set -eux; \
    chmod -R a+rX /opt; \
    { echo "uv: $(/opt/uv/uv --version)"; echo "python: $(/opt/python/bin/python3 --version)"; \
      echo "base_image_os: $(. /etc/os-release && echo "$PRETTY_NAME")"; \
      echo "git: $(git --version)"; echo "jq: $(jq --version)"; echo "perl: $(perl -e 'print $^V')"; \
    } >> /opt/eq/PROVENANCE.txt; \
    cd /opt/eq/stack_mathlib && lake env printenv LEAN_PATH | tr ':' '\n' | head -n 3
LABEL org.opencontainers.image.title="eq-lean" \
      org.opencontainers.image.description="Equilibrium harness isolated checks: Lean 4.34.1 + Mathlib v4.34.1, uv, CPython 3.14.8 (arm64)"
USER 10001:10001
WORKDIR /work
CMD ["bash"]
