#!/usr/bin/env python3
"""Build deterministic local archives from explicit project-file allowlists."""

import hashlib
import json
from pathlib import Path
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def build(name, files):
    path = DIST / name
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in sorted(set(files)):
            source = ROOT / relative
            if source.is_symlink() or not source.is_file():
                raise ValueError(f"Expected a regular project file: {relative}")
            item = zipfile.ZipInfo(relative, (2026, 1, 1, 0, 0, 0))
            item.create_system = 3
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = (0o100755 if source.stat().st_mode & 0o111 else 0o100644) << 16
            archive.writestr(item, source.read_bytes())
    with zipfile.ZipFile(path) as archive:
        if archive.testzip():
            raise ValueError(f"Invalid ZIP: {name}")
    return path


def main():
    plugin = json.loads((ROOT / "manifest.json").read_text())
    extension = json.loads((ROOT / "browser/manifest.json").read_text())
    for size, filename in extension["icons"].items():
        data = (ROOT / "browser" / filename).read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", data[16:24]) != (int(size), int(size)):
            raise ValueError(f"Invalid icon: {filename}")
    browser = ["browser/" + name for name in (
        "manifest.json", "background.js", "site-metadata.js", "status.html", "status.js",
        "icons/16.png", "icons/32.png", "icons/48.png", "icons/128.png")]
    source = ["manifest.json", "Panel.qml", "BarWidget.qml", "README.md", "PRIVACY.md", "LICENSE", ".gitignore", "preview.png",
              "agent/focus_ratio_agent.py"] + browser
    for pattern in ("scripts/*.sh", "scripts/*.py", "tests/*.py", "tests/*.js", "tests/*.mjs", "tests/*.sh", "assets/*.svg",
                    "release/*.md", "release/assets/*.png", "site/*.html"):
        source.extend(str(path.relative_to(ROOT)) for path in ROOT.glob(pattern))
    DIST.mkdir(exist_ok=True)
    source_zip = build(f"focus-source-{plugin['version']}.zip", source)
    # Chrome requires manifest.json at the archive root, without a browser/ prefix.
    extension_zip = DIST / f"focus-chrome-{extension['version']}.zip"
    with zipfile.ZipFile(source_zip) as archive, zipfile.ZipFile(extension_zip, "w") as output:
        for name in sorted(browser + ["LICENSE"]):
            info = archive.getinfo(name)
            info.filename = name.removeprefix("browser/")
            output.writestr(info, archive.read(name))
    with zipfile.ZipFile(extension_zip) as archive:
        assert archive.testzip() is None
        assert json.loads(archive.read("manifest.json")) == extension
        for filename in extension["icons"].values():
            assert filename in archive.namelist()
    paths = [source_zip, extension_zip]
    (DIST / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in paths))
    for path in paths:
        print(f"{path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
