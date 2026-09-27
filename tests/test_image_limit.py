"""Tests for agent_guard.py image-limit mode: images an agent sees or uploads stay under the limit.

Run: uv run --with pytest --with pillow pytest -q tests/test_image_limit.py
Resizing needs sips (macOS), Pillow or ImageMagick; tests that resize are skipped without one.
"""
import base64
import importlib.util
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "dot-claude" / "hooks" / "agent_guard.py"
sys.path.insert(0, str(GUARD.parent))
import agent_guard as G  # noqa: E402

HAVE_PIL = bool(importlib.util.find_spec("PIL"))
HAVE_RESIZER = bool(shutil.which("sips") or shutil.which("magick") or shutil.which("convert") or HAVE_PIL)
needs_resizer = pytest.mark.skipif(not HAVE_RESIZER, reason="no sips, Pillow or ImageMagick here")
needs_pil = pytest.mark.skipif(not HAVE_PIL, reason="Pillow makes the JPEG/WebP fixtures")


def png(w, h, noise=False, alpha=False):
    ch = 4 if alpha else 3
    if noise:
        raw = b"".join(b"\x00" + os.urandom(w * ch) for _ in range(h))
    else:
        raw = b"".join(b"\x00" + bytes((x * 7 + y) % 256 for x in range(w) for _ in range(ch)) for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6 if alpha else 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def pil_image(w, h, fmt, **kw):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 60, 30)).save(buf, fmt, **kw)
    return buf.getvalue()


def run(ev, env, extra=None):
    e = dict(env, **(extra or {}))
    data = ev if isinstance(ev, str) else json.dumps(ev)
    return subprocess.run([sys.executable, str(GUARD), "image-limit"], input=data, capture_output=True,
                          text=True, env=e, timeout=120)


def hook_out(tool, inp, cwd, env, extra=None):
    p = run({"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": str(cwd), "tool_input": inp}, env, extra)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)["hookSpecificOutput"] if p.stdout.strip() else None


def upload(tool, inp, cwd, env, extra=None):
    out = hook_out(tool, inp, cwd, env, extra)
    assert out is None or "permissionDecision" not in out, out
    return out["updatedInput"] if out else None


def refused(tool, inp, cwd, env, extra=None):
    out = hook_out(tool, inp, cwd, env, extra)
    assert out and out["permissionDecision"] == "deny" and "updatedInput" not in out, out
    return out["permissionDecisionReason"]


@pytest.fixture
def env(tmp_path):
    e = {k: v for k, v in os.environ.items()
         if k not in ("STACK_IMAGE_MAX_PX", "STACK_IMAGE_UPLOAD_TOOLS", "STACK_IMAGE_MAX_B64", "CLAUDE_PROJECT_DIR")}
    e["XDG_STATE_HOME"] = str(tmp_path / "state")
    e["HOME"] = str(tmp_path / "home")
    (tmp_path / "home").mkdir()
    return e


def test_image_size_headers_and_traits():
    assert G.image_size(png(3, 2)) == (3, 2)
    assert G.image_size(b"GIF89a" + struct.pack("<HH", 640, 480) + b"\x00" * 8) == (640, 480)
    assert G.image_size(b"BM" + b"\x00" * 16 + struct.pack("<ii", 800, -600) + b"\x00" * 8) == (800, 600)
    vp8x = b"RIFF\x00\x00\x00\x00WEBPVP8X" + b"\x0a\x00\x00\x00" + b"\x12" + b"\x00" * 3 \
        + (2999).to_bytes(3, "little") + (1999).to_bytes(3, "little")
    assert G.image_size(vp8x) == (3000, 2000)
    assert G.image_traits(vp8x, "image/webp") == (True, True)          # alpha and animation flags
    jpeg = (b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
            + b"\xff\xc0" + struct.pack(">HBHH", 17, 8, 1200, 2400) + b"\x03" + b"\x00" * 9 + b"\xff\xd9")
    assert G.image_size(jpeg) == (2400, 1200)
    assert G.image_size(b"not an image") is None
    assert G.image_traits(png(4, 4, alpha=True), "image/png") == (True, False)
    assert G.image_traits(png(4, 4), "image/png") == (False, False)
    gif2 = b"GIF89a" + struct.pack("<HH", 10, 10) + b"\x00" * 3 + b"\x21\xf9\x04" + b"\x00" * 5 + b"\x21\xf9\x04"
    assert G.image_traits(gif2, "image/gif")[1] is True
    assert G.sniff_mime(b"II*\x00rest") == "image/tiff"
    assert G.sniff_mime(b"\x00\x00\x00\x1cftypheic") == "image/heic"
    assert [G.out_format(m, a) for m, a in (("image/jpeg", True), ("image/png", False), ("image/webp", False),
                                            ("image/webp", True), ("image/gif", True))] == \
        ["jpeg", "png", "jpeg", "png", "png"]


@needs_resizer
def test_read_result_is_scaled_below_the_limit(env):
    data = png(2000, 1200)
    resp = {"type": "image", "file": {"base64": base64.b64encode(data).decode(), "type": "image/png",
                                      "originalSize": len(data),
                                      "dimensions": {"originalWidth": 3000, "originalHeight": 1800,
                                                     "displayWidth": 2000, "displayHeight": 1200}}}
    p = run({"hook_event_name": "PostToolUse", "tool_name": "Read", "tool_response": resp}, env)
    assert p.returncode == 0, p.stderr
    new = json.loads(p.stdout)["hookSpecificOutput"]["updatedToolOutput"]
    size = G.image_size(base64.b64decode(new["file"]["base64"]))
    assert max(size) <= 1919 and size[0] == 1919
    assert new["file"]["type"] == "image/png" and new["file"]["dimensions"]["displayWidth"] == size[0]
    assert new["file"]["dimensions"]["originalWidth"] == 3000 and new["type"] == "image"
    assert set(new["file"]) == set(resp["file"])          # same shape as Read's own output


@needs_resizer
def test_mcp_image_blocks_are_scaled(env):
    b64 = base64.b64encode(png(2600, 1500)).decode()
    small = base64.b64encode(png(100, 50)).decode()
    resp = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
            {"type": "text", "text": "[Image: source: /tmp/x.png]"},
            {"type": "image", "data": small, "mimeType": "image/png"}]
    p = run({"hook_event_name": "PostToolUse", "tool_name": "mcp__playwright__browser_take_screenshot",
             "tool_response": resp}, env)
    new = json.loads(p.stdout)["hookSpecificOutput"]["updatedToolOutput"]
    assert max(G.image_size(base64.b64decode(new[0]["source"]["data"]))) <= 1919
    assert new[1] == resp[1] and new[2] == resp[2]         # text and small images untouched


@needs_resizer
def test_result_above_the_api_size_cap_becomes_jpeg_or_stays(env):
    b64 = base64.b64encode(png(2400, 1300, noise=True)).decode()     # noise: PNG barely compresses
    ev = {"hook_event_name": "PostToolUse", "tool_name": "Read",
          "tool_response": {"type": "image", "file": {"base64": b64, "type": "image/png"}}}
    p = run(ev, env, {"STACK_IMAGE_MAX_B64": "3500000"})
    new = json.loads(p.stdout)["hookSpecificOutput"]["updatedToolOutput"]["file"]
    assert new["type"] == "image/jpeg" and len(new["base64"]) <= 3500000
    assert max(G.image_size(base64.b64decode(new["base64"]))) <= 1919
    p = run(ev, env, {"STACK_IMAGE_MAX_B64": "1000"})                 # nothing fits: left as it was
    assert p.returncode == 0 and p.stdout.strip() == ""


@needs_pil
def test_jpeg_results_stay_jpeg(env):
    b64 = base64.b64encode(pil_image(2600, 1400, "JPEG", quality=90)).decode()
    p = run({"hook_event_name": "PostToolUse", "tool_name": "mcp__computer-use__screenshot",
             "tool_response": [{"type": "image", "data": b64, "mimeType": "image/jpeg"}]}, env)
    new = json.loads(p.stdout)["hookSpecificOutput"]["updatedToolOutput"][0]
    assert new["mimeType"] == "image/jpeg" and base64.b64decode(new["data"])[:2] == b"\xff\xd8"


def test_small_images_and_text_results_pass_unchanged(env):
    b64 = base64.b64encode(png(640, 480)).decode()
    for ev in ({"hook_event_name": "PostToolUse", "tool_name": "Read",
                "tool_response": {"type": "image", "file": {"base64": b64, "type": "image/png"}}},
               {"hook_event_name": "PostToolUse", "tool_name": "Read",
                "tool_response": {"type": "text", "file": {"content": "hello"}}},
               {"hook_event_name": "PostToolUse", "tool_name": "mcp__exa__search",
                "tool_response": [{"type": "text", "text": "results"}]}):
        p = run(ev, env)
        assert p.returncode == 0 and p.stdout.strip() == "", p.stdout


@needs_resizer
def test_uploads_get_a_copy_next_to_the_original(env, tmp_path):
    proj = tmp_path / "proj"
    (proj / "assets").mkdir(parents=True)
    big = proj / "assets" / "big.png"
    big.write_bytes(png(2400, 1300))
    big.chmod(0o640)
    (proj / "small.png").write_bytes(png(300, 200))
    for tool in ("mcp__playwright__browser_file_upload", "mcp__claude-in-chrome__file_upload",
                 "mcp__playwright__browser_drop", "mcp__magg__pw_browser_file_upload"):
        new = upload(tool, {"paths": [str(big), str(proj / "small.png")], "ref": "e1"}, proj, env)
        copy = proj / "assets" / ".downscaled" / "big.png"
        assert new == {"paths": [str(copy), str(proj / "small.png")], "ref": "e1"}, tool
    assert G.image_size(copy.read_bytes()) == (1919, 1039) and copy.stat().st_mode & 0o777 == 0o640
    assert (copy.parent / ".gitignore").read_text().splitlines()[-1] == "*"      # git ignores the folder
    assert G.image_size(big.read_bytes()) == (2400, 1300)                          # the original is untouched
    assert copy.stat().st_mtime_ns == big.stat().st_mtime_ns                       # the copy carries it
    inode = copy.stat().st_ino
    upload("mcp__playwright__browser_file_upload", {"paths": [str(big)]}, proj, env)
    assert copy.stat().st_ino == inode                                              # reused, not rewritten
    big.write_bytes(png(2000, 3000))                                                # replaced by another
    os.utime(big, ns=(1, 10 ** 18))                                                 # image, even an older one
    upload("mcp__playwright__browser_file_upload", {"paths": [str(big)]}, proj, env)
    assert G.image_size(copy.read_bytes()) == (1279, 1919)
    extra = {"STACK_IMAGE_UPLOAD_TOOLS": r"mcp__acme__send"}
    uri = upload("mcp__acme__send", {"note": "logo", "image": big.as_uri()}, proj, env, extra)
    assert uri["image"] == copy.as_uri() and uri["note"] == "logo"                  # escaped as given
    raw = upload("mcp__acme__send", {"image": "file://" + str(big)}, proj, env, extra)
    assert raw["image"] == "file://" + str(copy)
    assert sorted(p.name for p in copy.parent.iterdir()) == [".gitignore", "big.png"]   # nothing else, ever


@needs_pil
def test_upload_formats_and_names(env, tmp_path):
    (tmp_path / "photo.jpg").write_bytes(pil_image(2400, 1600, "JPEG"))
    (tmp_path / "photo.webp").write_bytes(pil_image(2400, 1600, "WEBP"))
    (tmp_path / "photo.bmp").write_bytes(pil_image(2400, 1600, "BMP"))
    names = ["photo.jpg", "photo.webp", "photo.bmp"]
    new = upload("mcp__claude-in-chrome__file_upload", {"paths": [str(tmp_path / n) for n in names]}, tmp_path, env)
    d = tmp_path / ".downscaled"
    assert new["paths"] == [str(d / "photo.jpg"), str(d / "photo-webp.jpg"), str(d / "photo-bmp.jpg")]
    assert all((d / n).read_bytes()[:2] == b"\xff\xd8" for n in ("photo.jpg", "photo-webp.jpg", "photo-bmp.jpg"))


def test_images_that_cant_be_copied_are_refused_with_the_fix(env, tmp_path):
    gif = (b"GIF89a" + struct.pack("<HH", 2400, 1300) + b"\x00" * 3
           + (b"\x21\xf9\x04\x00\x00\x00\x00\x00" + b"\x2c" + b"\x00" * 9) * 2 + b"\x3b")
    (tmp_path / "anim.gif").write_bytes(gif)
    why = refused("mcp__playwright__browser_file_upload", {"paths": [str(tmp_path / "anim.gif")]}, tmp_path, env)
    assert "animated" in why and "under 1920 px" in why and "sips -Z 1919" in why
    assert not (tmp_path / ".downscaled").exists()
    small = tmp_path / "small.gif"
    small.write_bytes(gif.replace(struct.pack("<HH", 2400, 1300), struct.pack("<HH", 200, 100)))
    assert upload("mcp__playwright__browser_file_upload", {"paths": [str(small)]}, tmp_path, env) is None


@needs_resizer
def test_symlinks_are_never_followed_or_laundered(env, tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    old = victim / "notes.txt"
    old.write_text("keep me")
    os.utime(old, (1, 1))                                     # ancient: an old prune would have deleted it
    proj = tmp_path / "proj"
    (proj / "images").mkdir(parents=True)
    (proj / "images" / "hero.png").write_bytes(png(2400, 1300))
    (proj / "images" / ".downscaled").symlink_to(victim)      # a repo can commit this
    why = refused("mcp__playwright__browser_file_upload", {"paths": [str(proj / "images" / "hero.png")]}, proj, env)
    assert "isn't a plain folder" in why
    assert sorted(p.name for p in victim.iterdir()) == ["notes.txt"] and old.read_text() == "keep me"
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "scan.png").write_bytes(png(2400, 1300))
    (proj / "ref.png").symlink_to(secret / "scan.png")        # a symlinked file: no copy somewhere else
    why = refused("mcp__claude-in-chrome__file_upload", {"paths": [str(proj / "ref.png")]}, proj, env)
    assert "symlink" in why and not (proj / ".downscaled").exists()


@needs_resizer
def test_only_upload_tools_and_their_arguments_are_rewritten(env, tmp_path):
    big = tmp_path / "big.png"
    big.write_bytes(png(2400, 1300))
    for tool, inp in (("mcp__illustrator__place_image", {"file_path": str(big)}),   # a local app: never
                      ("mcp__x__generate_image", {"file_path": str(big)}),           # an output path
                      ("mcp__fs__write_file", {"path": str(big)}),
                      ("mcp__image-studio__generate_image", {"reference_images": [str(big)]}),   # scales itself
                      ("mcp__image-studio__edit_image", {"images": [str(big)]}),
                      ("mcp__magg__docling_convert", {"source": str(big)})):
        assert upload(tool, inp, tmp_path, env) is None, tool
    assert not (tmp_path / ".downscaled").exists()
    extra = {"STACK_IMAGE_UPLOAD_TOOLS": r"mcp__acme__(send|post)_image"}
    new = upload("mcp__acme__send_image", {"imageUrl": str(big), "caption": str(big)}, tmp_path, env, extra)
    assert new == {"imageUrl": str(tmp_path / ".downscaled" / "big.png"), "caption": str(big)}
    assert upload("mcp__acme__other", {"image": str(big)}, tmp_path, env, extra) is None


@needs_resizer
def test_relative_paths_must_mean_one_file(env, tmp_path):
    proj, sub = tmp_path / "proj", tmp_path / "proj" / "sub"
    sub.mkdir(parents=True)
    (proj / "big.png").write_bytes(png(2400, 1300))
    extra = {"CLAUDE_PROJECT_DIR": str(proj)}
    new = upload("mcp__playwright__browser_file_upload", {"paths": ["big.png"]}, sub, env, extra)
    assert new == {"paths": [str(proj / ".downscaled" / "big.png")]}
    (sub / "big.png").write_bytes(png(2500, 1300))        # now "big.png" could mean either file
    assert upload("mcp__playwright__browser_file_upload", {"paths": ["big.png"]}, sub, env, extra) is None


@needs_resizer
def test_files_protected_by_read_deny_rules_are_not_copied(env):
    ssh = Path(env["HOME"]) / ".ssh"
    ssh.mkdir()
    (ssh / "big.png").write_bytes(png(2400, 1300))
    assert upload("mcp__playwright__browser_file_upload", {"paths": [str(ssh / "big.png")]}, env["HOME"], env) is None
    assert not (ssh / ".downscaled").exists()


@needs_resizer
def test_unwritable_folder_is_refused_with_the_fix(env, tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    (ro / "big.png").write_bytes(png(2400, 1300))
    ro.chmod(0o555)
    try:
        if os.access(ro, os.W_OK):
            pytest.skip("running as a user who can write anywhere")
        assert "can't take" in refused("mcp__playwright__browser_file_upload", {"paths": [str(ro / "big.png")]}, tmp_path, env)
    finally:
        ro.chmod(0o755)


def test_limit_off_and_bad_input_never_block(env):
    b64 = base64.b64encode(png(2600, 1500)).decode()
    ev = {"hook_event_name": "PostToolUse", "tool_name": "Read",
          "tool_response": {"type": "image", "file": {"base64": b64, "type": "image/png"}}}
    p = run(ev, env, {"STACK_IMAGE_MAX_PX": "0"})
    assert p.returncode == 0 and p.stdout.strip() == ""
    for raw in ('{"hook_event_name": "PreToolUse", "tool_name": "mcp__playwright__browser_file_upload", "tool_input": [',
                "not json image", '{"hook_event_name": "PostToolUse", "tool_name": "Read"}',
                '{"hook_event_name": "PreToolUse", "tool_name": "mcp__playwright__browser_file_upload", '
                '"tool_input": {"paths": [123, null, "", "/no/such/file.png"]}}'):
        p = run(raw, env)
        assert p.returncode == 0 and p.stdout.strip() == "", (raw, p.stdout)
    p = run({"hook_event_name": "PreToolUse", "tool_name": "mcp__acme__x", "tool_input": {}}, env,
            {"STACK_IMAGE_UPLOAD_TOOLS": "(unclosed"})
    assert p.returncode == 0 and p.stdout.strip() == ""


def test_settings_wire_image_limit_for_read_and_mcp():
    s = json.loads((ROOT / "dot-claude" / "settings.json").read_text())
    groups = {(ev, g.get("matcher")) for ev, gs in s["hooks"].items() for g in gs
              if any("image-limit" in h.get("command", "") for h in g["hooks"])}
    assert ("PostToolUse", "Read|mcp__.*") in groups and ("PreToolUse", "mcp__.*") in groups
