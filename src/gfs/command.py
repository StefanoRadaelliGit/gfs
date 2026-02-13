#!/usr/bin/env python3
"""
gfs CLI entry point.

Subcommands
-----------
  init   — initialise a new patch series (v1)
  check  — run checkpatch.pl on a topic

Default (no subcommand):
  gfs -v N -c <sha> -n <num> -p <prefix> -t <topic>
"""

import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

import gfs


def cmd_init(args):
    """Initialise a new series: save config, run format-patch for v1."""
    cfg = {
        "to": ",".join(args.to_mail) if args.to_mail else "",
        "cc": ",".join(args.cc_mail) if args.cc_mail else "",
    }
    config_path = Path(args.topic) / gfs.CONFIG_NAME
    config_path.parent.mkdir(parents=True, exist_ok=True)
    gfs.save_config(cfg, config_path)
    gfs.run_format_patch(args.commit, args.num_patches, args.prefix,
                         args.topic, version=1,
                         to_mail=cfg["to"], cc_mail=cfg["cc"],
                         base=args.base or "",
                         skip_maintainers=args.no_cc)


def cmd_run(args):
    """Generate a subsequent version (v2, v3, …)."""
    topic = args.topic
    config_path = Path(topic) / gfs.CONFIG_NAME
    cfg = {}
    if config_path.exists():
        with open(config_path) as f:
            cfg = json.load(f)

    to_mail = ",".join(args.to_mail) if args.to_mail else cfg.get("to", "")
    cc_mail = ",".join(args.cc_mail) if args.cc_mail else cfg.get("cc", "")

    gfs.run_format_patch(args.commit, args.num_patches, args.prefix,
                         topic, args.version,
                         to_mail=to_mail, cc_mail=cc_mail,
                         base=args.base or "",
                         skip_maintainers=args.no_cc)

    if args.version > 1:
        gfs.copy_cover_letter_content(topic, args.version)
        gfs.add_changelog_trail(topic, args.version)


def cmd_sync(args):
    """
    Sync/initialize a project from an existing patch directory.

    Scans the given directory (or auto-detects topic/version from path),
    extracts metadata from the patches, and creates the .series.json config.
    """
    path = Path(args.path).resolve()

    # Determine topic and version from the path
    # Expected structure: topic/vN/*.patch
    if path.name.startswith("v") and path.name[1:].isdigit():
        # User gave us the version directory directly (e.g., topic/v2)
        version_dir = path
        topic_dir = path.parent
        version = int(path.name[1:])
    elif path.is_dir():
        # User gave us the topic directory, find the latest version
        topic_dir = path
        versions = sorted(
            [d for d in path.iterdir()
             if d.is_dir() and d.name.startswith("v") and d.name[1:].isdigit()],
            key=lambda d: int(d.name[1:])
        )
        if not versions:
            print(f"Error: no version directories (v1, v2, ...) found in {path}/",
                  file=sys.stderr)
            sys.exit(1)
        version_dir = versions[-1]
        version = int(version_dir.name[1:])
    else:
        print(f"Error: {path} is not a valid directory", file=sys.stderr)
        sys.exit(1)

    topic = topic_dir.name

    # Find patches in the version directory
    patches = sorted(glob.glob(os.path.join(version_dir, "*.patch")))
    if not patches:
        print(f"Error: no .patch files found in {version_dir}/", file=sys.stderr)
        sys.exit(1)

    # Count patches (excluding cover letter 0000-*)
    real_patches = [p for p in patches if not Path(p).name.startswith("0000-")]
    num_patches = len(real_patches)

    # Extract metadata from the cover letter (preferred) or first patch
    prefix = ""
    to_raw = ""
    cc_raw = ""

    cover_patches = [p for p in patches if Path(p).name.startswith("0000-")]
    sample_patch = cover_patches[0] if cover_patches else (
        real_patches[0] if real_patches else patches[0])

    # Parse mail headers, handling folded (continuation) lines.
    # Header order in git format-patch: Subject, To, Cc — so we must
    # NOT stop at Subject.
    with open(sample_patch) as f:
        current_header = None   # "to", "cc", or None
        current_value = ""
        for line in f:
            if line.startswith("To:"):
                if current_header == "cc":
                    cc_raw = current_value.strip()
                current_header = "to"
                current_value = line[3:].strip()
            elif line.startswith("Cc:"):
                if current_header == "to":
                    to_raw = current_value.strip()
                current_header = "cc"
                current_value = line[3:].strip()
            elif line.startswith("Subject:"):
                if current_header == "to":
                    to_raw = current_value.strip()
                elif current_header == "cc":
                    cc_raw = current_value.strip()
                current_header = None
                # Extract prefix from Subject: [PREFIX N/M] title
                import re
                m = re.search(r'\[([^\]]+)\s+\d+/\d+\]', line)
                if m:
                    prefix = m.group(1).strip()
            elif current_header and (line.startswith(" ") or line.startswith("\t")):
                # Continuation (folded) line
                current_value += line.strip()
            else:
                if current_header == "to":
                    to_raw = current_value.strip()
                elif current_header == "cc":
                    cc_raw = current_value.strip()
                current_header = None
                current_value = ""
                # Blank line = end of mail headers
                if line.strip() == "":
                    break
        # Flush if we hit EOF without a blank line
        if current_header == "to":
            to_raw = current_value.strip()
        elif current_header == "cc":
            cc_raw = current_value.strip()

    # Strip trailing commas from raw values
    to_raw = to_raw.rstrip(",").strip()
    cc_raw = cc_raw.rstrip(",").strip()

    # Build config — preserve original order
    cfg = {
        "to": to_raw,
        "cc": cc_raw,
    }

    config_path = topic_dir / gfs.CONFIG_NAME

    print(f"\n  ── gfs sync ──\n")
    print(f"  📂 Topic:      {topic}")
    print(f"  📌 Version:    v{version}")
    print(f"  📝 Patches:    {num_patches}")
    if prefix:
        print(f"  🏷️  Prefix:     {prefix}")
    if cfg["to"]:
        print(f"  📧 To:         {cfg['to'][:60]}{'...' if len(cfg['to']) > 60 else ''}")
    if cfg["cc"]:
        print(f"  📧 Cc:         {cfg['cc'][:60]}{'...' if len(cfg['cc']) > 60 else ''}")

    gfs.save_config(cfg, config_path)

    print(f"\n  ✅ Project initialized from existing patches.")
    print(f"\n  Next steps:")
    print(f"    • Edit {config_path} if needed")
    print(f"    • Run: gfs -v {version + 1} -c <sha> -n {num_patches} -p '{prefix} v{version + 1}' -t {topic}")


def cmd_check(args):
    """Run checkpatch.pl on the latest (or given) version of a topic."""
    topic = args.topic
    if args.version:
        version = args.version
    else:
        # Find the latest version directory
        versions = sorted(
            [d for d in Path(topic).iterdir()
             if d.is_dir() and d.name.startswith("v") and d.name[1:].isdigit()],
            key=lambda d: int(d.name[1:])
        )
        if not versions:
            print(f"Error: no version directories found in {topic}/", file=sys.stderr)
            sys.exit(1)
        version = int(versions[-1].name[1:])

    patch_dir = os.path.join(topic, f"v{version}")
    patches = sorted(glob.glob(os.path.join(patch_dir, "*.patch")))

    if not patches:
        print(f"Error: no patches found in {patch_dir}/", file=sys.stderr)
        sys.exit(1)

    print(f"\n  ── checkpatch.pl on {patch_dir} ──\n")
    cmd = ["./scripts/checkpatch.pl", "--max-line-length=80",
           "--strict", "--codespell"] + patches
    print(f"  ▸ {' '.join(cmd)}\n")
    subprocess.run(cmd)


def main():
    p = argparse.ArgumentParser(
        prog="gfs",
        description="git format-patch series helper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  gfs init -c <tip-sha> -n 3 -b <base-sha> --prefix 'PATCH' -t my-topic\n"
            "  gfs -v 2 -c <tip-sha> -n 3 -b <base-sha> --prefix 'PATCH v2' -t my-topic\n"
            "  gfs check -t my-topic\n"
            "  gfs sync my-topic/v2       # init project from existing patches\n"
            "  gfs sync .                 # sync from current directory\n"
        ),
    )
    sub = p.add_subparsers(dest="command")

    # -- init (first time) --
    sp = sub.add_parser("init", help="Initialise a new patch series (v1)")
    sp.add_argument("-c", "--commit", required=True,
                    help="Tip commit SHA (last commit in series)")
    sp.add_argument("-n", "--num-patches", type=int, required=True,
                    help="Number of patches")
    sp.add_argument("-b", "--base", default=None,
                    help="Optional base commit (git format-patch --base)")
    sp.add_argument("--prefix", "-p", required=True,
                    help='Subject prefix, e.g. "PATCH mainline-linux"')
    sp.add_argument("--topic", "-t", required=True,
                    help='Topic directory, e.g. "for-pm-upstream"')
    sp.add_argument("--to", dest="to_mail", action="append", default=None,
                    help='To: email address (may be repeated)')
    sp.add_argument("--cc", dest="cc_mail", action="append", default=None,
                    help='Cc: email address (may be repeated)')
    sp.add_argument("--no-cc", action="store_true", default=False,
                    help="Skip get_maintainer.pl pass (single format-patch run)")
    sp.set_defaults(func=cmd_init)

    # -- check --
    sp = sub.add_parser("check", help="Run checkpatch.pl on a topic")
    sp.add_argument("--topic", "-t", required=True,
                    help='Topic directory, e.g. "for-test-gfs"')
    sp.add_argument("-v", "--version", type=int, default=None,
                    help="Version to check (default: latest)")
    sp.set_defaults(func=cmd_check)

    # -- sync --
    sp = sub.add_parser("sync", help="Initialize project from existing patches")
    sp.add_argument("path", nargs="?", default=".",
                    help="Path to topic directory or version subdirectory (default: current dir)")
    sp.set_defaults(func=cmd_sync)

    # -- default (subsequent versions) --
    p.add_argument("-v", "--version", type=int, help="Series version (2, 3, …)")
    p.add_argument("-c", "--commit", help="Tip commit SHA (last commit in series)")
    p.add_argument("-n", "--num-patches", type=int, help="Number of patches")
    p.add_argument("-b", "--base", default=None,
                   help="Optional base commit (git format-patch --base)")
    p.add_argument("--prefix", "-p", help='Subject prefix')
    p.add_argument("--topic", "-t", default=None,
                   help="Topic directory, e.g. for-test-gfs")
    p.add_argument("--to", dest="to_mail", action="append", default=None,
                   help="To: email address (may be repeated; overrides saved value)")
    p.add_argument("--cc", dest="cc_mail", action="append", default=None,
                   help="Cc: email address (may be repeated; overrides saved value)")
    p.add_argument("--no-cc", action="store_true", default=False,
                   help="Skip get_maintainer.pl pass (single format-patch run)")

    args = p.parse_args()

    if args.command == "init":
        args.func(args)
    elif args.command == "check":
        args.func(args)
    elif args.command == "sync":
        args.func(args)
    else:
        for required in ("version", "commit", "num_patches", "prefix", "topic"):
            if getattr(args, required, None) is None:
                print(f"Error: --{required.replace('_', '-')} is required.",
                      file=sys.stderr)
                sys.exit(1)
        cmd_run(args)


if __name__ == "__main__":
    main()
