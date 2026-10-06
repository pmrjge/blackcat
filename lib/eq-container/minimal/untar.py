"""untar.py ARCHIVE.tar.zst DEST: unpack a zstd tarball into DEST with its first path component stripped (what
`tar --zstd -xf ARCHIVE -C DEST --strip-components=1` does). Runs in the fetch stage of Dockerfile.minimal on the
sha256-verified Lean archive, with the pinned python-build-standalone CPython 3.14 (tarfile reads zstd since 3.14): the
builder image (buildpack-deps) has no zstd. tarfile's "data" filter refuses absolute paths, links that leave DEST, device
files, and clears setuid/setgid bits. Exit 1 (nothing partial is kept by the caller: the stage fails) on any error.
"""

from __future__ import annotations

import sys
import tarfile


def strip1(name: str) -> str:
    """'top/a/b' -> 'a/b'; '' for the top directory itself."""
    while name.startswith("./"):  # never str.lstrip("./"): that strips a character set (".hidden" -> "hidden")
        name = name[2:]
    parts = name.split("/", 1)
    return parts[1] if len(parts) == 2 else ""


def main(src: str, dest: str) -> None:
    with tarfile.open(src, "r:zst") as t:
        members = []
        for m in t.getmembers():
            name = strip1(m.name)
            if not name.strip("/"):
                continue
            m.name = name
            if m.islnk():
                m.linkname = strip1(m.linkname)
            members.append(m)
        if not members:
            sys.exit("untar.py: %s holds no member below its top directory" % src)
        t.extractall(dest, members=members, filter="data")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: untar.py ARCHIVE.tar.zst DEST")
    try:
        main(sys.argv[1], sys.argv[2])
    except (OSError, tarfile.TarError, ValueError) as e:
        sys.exit("untar.py: %s" % e)
