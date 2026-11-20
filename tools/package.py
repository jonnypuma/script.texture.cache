# -*- coding: utf-8 -*-
"""Package script.texture.cache into a Kodi-installable ZIP archive."""

import argparse
import os
import sys
import xml.etree.ElementTree as ET
import zipfile

REQUIRED_PATHS = (
    "addon.xml",
    "common.py",
    "context.py",
    "main.py",
    "service.py",
    "texturecache.py",
    "webserver.py",
    os.path.join("resources", "settings.xml"),
)

EXCLUDED_DIRS = frozenset({
    ".git",
    ".github",
    ".pytest_cache",
    "__pycache__",
    "dist",
    "tests",
})

EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".tmp")


def read_addon_metadata(repo_root):
    addon_xml = os.path.join(repo_root, "addon.xml")
    tree = ET.parse(addon_xml)
    root = tree.getroot()
    addon_id = root.get("id")
    version = root.get("version")
    if not addon_id or not version:
        raise ValueError("addon.xml must define id and version attributes")
    return addon_id, version


def validate_required_files(repo_root):
    missing = [rel for rel in REQUIRED_PATHS if not os.path.isfile(os.path.join(repo_root, rel))]
    if missing:
        raise FileNotFoundError("Missing required addon file(s): %s" % ", ".join(missing))


def build_zip(repo_root, output_path=None):
    addon_id, version = read_addon_metadata(repo_root)
    validate_required_files(repo_root)

    if output_path is None:
        dist_dir = os.path.join(repo_root, "dist")
        os.makedirs(dist_dir, exist_ok=True)
        output_path = os.path.join(dist_dir, "%s-%s.zip" % (addon_id, version))
    else:
        parent = os.path.dirname(os.path.abspath(output_path))
        if parent:
            os.makedirs(parent, exist_ok=True)

    file_count = 0
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(repo_root):
            dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith("."))
            for filename in sorted(filenames):
                if filename.startswith(".") or filename.endswith(EXCLUDED_SUFFIXES):
                    continue
                full_path = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(full_path, repo_root)
                arcname = "%s/%s" % (addon_id, rel_path.replace(os.sep, "/"))
                zf.write(full_path, arcname)
                file_count += 1

    return output_path, file_count


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a Kodi-installable ZIP for script.texture.cache.")
    parser.add_argument("-o", "--output", help="Output ZIP file path (default: dist/<id>-<version>.zip)")
    args = parser.parse_args(argv)

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        out_path, count = build_zip(repo_root, args.output)
    except Exception as exc:
        sys.stderr.write("Error: %s\n" % exc)
        return 1

    print("Created %s (%d files)" % (out_path, count))
    return 0


if __name__ == "__main__":
    sys.exit(main())
