"""eqc_json.py: the one place that reads JSON written by Apple `container` (CLI 1.5.0) for lib/eq-container.

Run as `python3 -I eqc_json.py MODE ...` with the JSON on stdin (or an archive path). Standard library only, Python 3.9+
(macOS's /usr/bin/python3). Every reader fails closed: exit 1 and nothing on stdout when the shape is not the expected one.

  digest                 stdin: `container image inspect REF` -> the image digest sha256:<64 hex>
  ids LABEL=VALUE        stdin: `container list --all --format json` -> ids of the containers carrying that label
  exists ID              stdin: `container list --all --format json` -> exit 0 when a container with that id exists
  oci-config ARCHIVE     the linux/arm64 image config (OCI `config` object: User, Env, Entrypoint, ExposedPorts, Volumes,
                         Labels) of an archive written by `container image save --output ARCHIVE REF`, as JSON
  oci-cat ARCHIVE PATH   the bytes of PATH in that image (layers applied in order, whiteouts honoured, symlinks followed)
  oci-sha256 ARCHIVE PATH...   one `<sha256>  PATH` line per PATH (empty hash when the path is absent)

Shapes. Verified by the user on this host (container 1.5.0, 2026-10-05): `container image inspect alpine:latest` is a JSON
array whose element has exactly the keys configuration, id, variants. UNVERIFIED: where the digest lives inside it. The
candidates read here are `.configuration.index.digest` (CLI 1.5.0 source: ClientImage.details() builds
ImageDetail(name:, index: <OCI descriptor>, variants:); the 1.5.0 docs show the fields under "configuration") and `.id`;
at least one must be sha256:<64 hex> and all that are must agree, else exit 1. The container list shape
(`.[].configuration.id`, `.[].configuration.labels`) follows the 1.5.0 docs (container-inspection.md) and is UNVERIFIED.
The `image save` archive is read as an OCI image layout (index.json + blobs/sha256/...) or a docker-save layout
(manifest.json): which one 1.5.0 writes is UNVERIFIED.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import posixpath
import re
import sys
import tarfile

SHA = re.compile(r"sha256:[0-9a-f]{64}")
DIGEST_PATHS = (("configuration", "index", "digest"), ("id",))


def die() -> None:
    sys.exit(1)


def load_stdin() -> object:
    try:
        return json.load(sys.stdin)
    except ValueError:
        die()


def dig(obj: object, path: tuple) -> object:
    for k in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


def digest() -> None:
    data = load_stdin()
    if not (isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict)):
        die()
    found = {v for v in (dig(data[0], p) for p in DIGEST_PATHS) if isinstance(v, str) and SHA.fullmatch(v)}
    if len(found) != 1:
        die()
    print(found.pop())


def rows() -> list:
    data = load_stdin()
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def ids(sel: str) -> None:
    k, _, v = sel.partition("=")
    for r in rows():
        c = r.get("configuration")
        if isinstance(c, dict) and isinstance(c.get("labels"), dict) and c["labels"].get(k) == v and isinstance(c.get("id"), str):
            print(c["id"])


def exists(cid: str) -> None:
    sys.exit(0 if any(dig(r, ("configuration", "id")) == cid for r in rows()) else 1)


# ---- image archives ------------------------------------------------------------------------------------------------
class Archive:
    def __init__(self, path: str) -> None:
        self.tar = tarfile.open(path, "r:*")
        self.names = {m.name.lstrip("./"): m for m in self.tar.getmembers()}

    def read(self, name: str) -> bytes:
        m = self.names.get(name)
        if m is None or not m.isfile():
            die()
        f = self.tar.extractfile(m)
        return f.read() if f is not None else b""

    def blob(self, d: str) -> bytes:
        if not SHA.fullmatch(d or ""):
            die()
        data = self.read("blobs/sha256/" + d.split(":", 1)[1])
        if "sha256:" + hashlib.sha256(data).hexdigest() != d:
            die()  # a blob that does not hash to its name is never used
        return data

    def manifest(self) -> tuple:
        """(config dict, [layer bytes]) of the linux/arm64 image."""
        if "index.json" in self.names:
            desc = json.loads(self.read("index.json"))
            for _ in range(4):  # index -> (nested index) -> manifest
                ms = [m for m in desc.get("manifests", []) if isinstance(m, dict)]
                plat = [m for m in ms if (m.get("platform") or {}).get("architecture") == "arm64"
                        and (m.get("platform") or {}).get("os") == "linux"]
                pick = plat or ms
                if len(pick) != 1:
                    die()
                desc = json.loads(self.blob(pick[0].get("digest", "")))
                if "layers" in desc:
                    cfg = json.loads(self.blob(desc["config"]["digest"]))
                    return cfg, [self.blob(layer["digest"]) for layer in desc["layers"]]
            die()
        if "manifest.json" in self.names:
            man = json.loads(self.read("manifest.json"))
            if not (isinstance(man, list) and len(man) == 1):
                die()
            cfg = json.loads(self.read(man[0]["Config"]))
            return cfg, [self.read(layer) for layer in man[0]["Layers"]]
        die()
        raise AssertionError


def layer_tar(data: bytes) -> tarfile.TarFile:
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return tarfile.open(fileobj=io.BytesIO(data), mode="r:")


def image_fs(archive: str) -> tuple:
    """(config, {path: (TarInfo, layer tarfile)}) after applying every layer in order."""
    cfg, layers = Archive(archive).manifest()
    fs: dict = {}
    for data in layers:
        t = layer_tar(data)
        for m in t.getmembers():
            p = "/" + m.name.lstrip("./").rstrip("/")
            d, b = posixpath.split(p)
            if b == ".wh..wh..opq":
                for k in [k for k in fs if k.startswith(d.rstrip("/") + "/")]:
                    del fs[k]
                continue
            if b.startswith(".wh."):
                gone = posixpath.join(d, b[4:])
                for k in [k for k in fs if k == gone or k.startswith(gone + "/")]:
                    del fs[k]
                continue
            fs[p] = (m, t)
    return cfg, fs


def resolve(fs: dict, path: str) -> tuple:
    p = posixpath.normpath("/" + path)
    for _ in range(40):
        # follow symlinked parents too
        parts, cur = p.strip("/").split("/"), ""
        for i, part in enumerate(parts):
            cur = cur + "/" + part
            e = fs.get(cur)
            if e is not None and e[0].issym():
                tgt = e[0].linkname
                base = posixpath.dirname(cur)
                cur = posixpath.normpath(tgt if tgt.startswith("/") else posixpath.join(base, tgt))
                p = posixpath.normpath(cur + "/" + "/".join(parts[i + 1:])) if i + 1 < len(parts) else cur
                break
        else:
            e = fs.get(p)
            return e if e is not None and e[0].isfile() else None
    return None


def oci_config(archive: str) -> None:
    cfg, _ = Archive(archive).manifest()
    if not (cfg.get("architecture") == "arm64" and cfg.get("os") == "linux"):
        die()
    print(json.dumps(cfg.get("config") or {}, sort_keys=True))


def oci_read(archive: str, paths: list, mode: str) -> None:
    _, fs = image_fs(archive)
    for p in paths:
        e = resolve(fs, p)
        data = None
        if e is not None:
            f = e[1].extractfile(e[0])
            data = f.read() if f is not None else None
        if mode == "cat":
            if data is None:
                die()
            sys.stdout.buffer.write(data)
        else:
            print("%s  %s" % (hashlib.sha256(data).hexdigest() if data is not None else "", p))


def main(argv: list) -> None:
    if not argv:
        die()
    m, rest = argv[0], argv[1:]
    if m == "digest" and not rest:
        digest()
    elif m == "ids" and len(rest) == 1:
        ids(rest[0])
    elif m == "exists" and len(rest) == 1:
        exists(rest[0])
    elif m == "oci-config" and len(rest) == 1:
        oci_config(rest[0])
    elif m == "oci-cat" and len(rest) == 2:
        oci_read(rest[0], rest[1:], "cat")
    elif m == "oci-sha256" and len(rest) >= 2:
        oci_read(rest[0], rest[1:], "sha256")
    else:
        die()


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (OSError, KeyError, TypeError, ValueError, tarfile.TarError, EOFError):
        sys.exit(1)
