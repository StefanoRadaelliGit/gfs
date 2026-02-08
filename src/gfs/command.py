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
        "to": args.to_mail or "",
        "cc": args.cc_mail or "",
    }
    config_path = Path(args.topic) / gfs.CONFIG_NAME
    config_path.parent.mkdir(parents=True, exist_ok=True)
    gfs.save_config(cfg, config_path)
    gfs.run_format_patch(args.commit, args.num_patches, args.prefix,
                         args.topic, version=1,
                         to_mail=cfg["to"], cc_mail=cfg["cc"])


def cmd_run(args):
    """Generate a subsequent version (v2, v3, …)."""
    topic = args.topic
    config_path = Path(topic) / gfs.CONFIG_NAME
    cfg = {}
    if config_path.exists():
        with open(config_path) as f:
            cfg = json.load(f)

    to_mail = args.to_mail or cfg.get("to", "")
    cc_mail = args.cc_mail or cfg.get("cc", "")

    gfs.run_format_patch(args.commit, args.num_patches, args.prefix,
                         topic, args.version,
                         to_mail=to_mail, cc_mail=cc_mail)

    if args.version > 1:
        gfs.copy_cover_letter_content(topic, args.version)
        gfs.add_changelog_trail(topic, args.version)


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
    cmd = ["./scripts/checkpatch.pl", "--strict", "--codespell"] + patches
    print(f"  ▸ {' '.join(cmd)}\n")
    subprocess.run(cmd)


def main():
    p = argparse.ArgumentParser(
        prog="gfs",
        description="git format-patch series helper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  gfs init -c <sha> -n 3 --prefix 'PATCH' -t my-topic\n"
            "  gfs -v 2 -c <sha> -n 3 --prefix 'PATCH v2' -t my-topic\n"
            "  gfs check -t my-topic\n"
        ),
    )
    sub = p.add_subparsers(dest="command")

    # -- init (first time) --
    sp = sub.add_parser("init", help="Initialise a new patch series (v1)")
    sp.add_argument("-c", "--commit", required=True, help="Base commit SHA")
    sp.add_argument("-n", "--num-patches", type=int, required=True,
                    help="Number of patches")
    sp.add_argument("--prefix", "-p", required=True,
                    help='Subject prefix, e.g. "PATCH mainline-linux"')
    sp.add_argument("--topic", "-t", required=True,
                    help='Topic directory, e.g. "for-pm-upstream"')
    sp.add_argument("--to", dest="to_mail", default=None,
                    help='To: email address')
    sp.add_argument("--cc", dest="cc_mail", default=None,
                    help='Cc: email address')
    sp.set_defaults(func=cmd_init)

    # -- check --
    sp = sub.add_parser("check", help="Run checkpatch.pl on a topic")
    sp.add_argument("--topic", "-t", required=True,
                    help='Topic directory, e.g. "for-test-gfs"')
    sp.add_argument("-v", "--version", type=int, default=None,
                    help="Version to check (default: latest)")
    sp.set_defaults(func=cmd_check)

    # -- default (subsequent versions) --
    p.add_argument("-v", "--version", type=int, help="Series version (2, 3, …)")
    p.add_argument("-c", "--commit", help="Base commit SHA")
    p.add_argument("-n", "--num-patches", type=int, help="Number of patches")
    p.add_argument("--prefix", "-p", help='Subject prefix')
    p.add_argument("--topic", "-t", default=None,
                   help="Topic directory, e.g. for-test-gfs")
    p.add_argument("--to", dest="to_mail", default=None,
                   help="To: email address (overrides saved value)")
    p.add_argument("--cc", dest="cc_mail", default=None,
                   help="Cc: email address (overrides saved value)")

    args = p.parse_args()

    if args.command == "init":
        args.func(args)
    elif args.command == "check":
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
