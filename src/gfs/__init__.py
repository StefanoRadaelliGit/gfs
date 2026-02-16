"""
gfs – git format-patch series helper with automatic changelog trail.

This module contains the core logic:
  - patch file helpers (find, extract trail, inject trail)
  - two-pass git format-patch runner
  - changelog trail builder
  - per-topic config management
"""

__version__ = "0.0.4"

import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

CONFIG_NAME = ".series.json"


# ── config helpers ───────────────────────────────────────────────────
def save_config(cfg: dict, path: Path):
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"  ✓ config saved → {path}")


# ── patch file helpers ───────────────────────────────────────────────
def patch_number(filepath: str) -> str:
    """Extract the numeric prefix from a patch filename, e.g. '0001'."""
    return Path(filepath).name.split("-", 1)[0]


def find_patches_in(directory: str) -> dict[str, str]:
    """Return {number: filepath} for all .patch files in directory."""
    patches = {}
    for p in sorted(glob.glob(os.path.join(directory, "*.patch"))):
        num = patch_number(p)
        patches[num] = p
    return patches


def extract_trail(patch_path: str) -> str:
    """
    Extract the existing changelog trail from a patch file.

    The trail sits between the first '---' separator line and the
    diffstat (first line matching ' <path> | <num>') or other end markers.
    """
    with open(patch_path) as f:
        lines = f.readlines()

    # Find the '---' separator
    separator_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "---":
            separator_idx = i
            break

    if separator_idx is None:
        return ""

    # Collect lines after '---' that belong to the trail.
    trail_lines = []
    for i in range(separator_idx + 1, len(lines)):
        line = lines[i]
        # diffstat line:  " drivers/clk/foo.c | 42 +++"
        if re.match(r'^ \S.+\|', line):
            break
        # diff start
        if line.startswith("diff --git"):
            break
        # cover letter shortlog: "Author (N):"
        if re.match(r'^\S.+ \(\d+\):', line):
            break
        trail_lines.append(line)

    # Strip leading/trailing blank lines
    text = "".join(trail_lines).strip("\n")
    return text


def build_trail(version: int, old_trail: str) -> str:
    """
    Build the changelog trail block.

    Prepends a new empty 'v(N-1)->vN:' header to the existing trail.
    The user can fill in the details manually afterwards.

    Example for v3:
        v2->v3:

        v1->v2:
         - ...
    """
    header = f"v{version - 1}->v{version}:\n - "
    if old_trail:
        return header + "\n\n" + old_trail
    return header


def inject_trail(patch_path: str, trail_block: str):
    """
    Inject the trail block into the patch file, between '---' and
    the diffstat / file-list.
    """
    with open(patch_path) as f:
        lines = f.readlines()

    # Find the '---' separator
    separator_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "---":
            separator_idx = i
            break

    if separator_idx is None:
        print(f"  ⚠ Could not find '---' separator in {patch_path}, skipping.",
              file=sys.stderr)
        return

    # Insert trail block right after '---'
    trail_with_newlines = trail_block + "\n\n"
    new_lines = (
        lines[: separator_idx + 1]      # up to and including '---'
        + [trail_with_newlines]          # changelog trail
        + lines[separator_idx + 1:]     # diffstat + diff
    )

    with open(patch_path, "w") as f:
        f.writelines(new_lines)

    print(f"  ✓ trail injected → {Path(patch_path).name}")


def inject_trail_cover_letter(patch_path: str, trail_block: str):
    """
    Inject the trail block into a cover letter.

    Cover letters don't have a '---' separator like normal patches.
    The trail is inserted before the shortlog section, i.e. right
    before the first line matching 'Author (N):' pattern.
    """
    with open(patch_path) as f:
        lines = f.readlines()

    # Find the shortlog header: "Author Name (N):"
    shortlog_idx = None
    for i, line in enumerate(lines):
        if re.match(r'^\S.+ \(\d+\):', line):
            shortlog_idx = i
            break

    if shortlog_idx is None:
        print(f"  ⚠ Could not find shortlog in {patch_path}, skipping.",
              file=sys.stderr)
        return

    trail_with_newlines = trail_block + "\n\n"
    new_lines = (
        lines[:shortlog_idx]
        + [trail_with_newlines]
        + lines[shortlog_idx:]
    )

    with open(patch_path, "w") as f:
        f.writelines(new_lines)

    print(f"  ✓ trail injected → {Path(patch_path).name}")


# ── format-patch ─────────────────────────────────────────────────────
def run_format_patch(commit: str, num_patches: int, prefix: str,
                     topic: str, version: int,
                     to_mail: str = "", cc_mail: str = "",
                     base: str = "",
                     skip_maintainers: bool = False,
                     skip_to: bool = False) -> list[str]:
    """Run git format-patch twice: first to generate files, then with
    get_maintainer.pl --cc so that the maintainer list is included.

    If skip_maintainers is True, only the first pass is run (no
    get_maintainer.pl CCs are added).
    If skip_to is True, saved To: addresses are omitted."""
    outdir = os.path.join(topic, f"v{version}")

    base_cmd = [
        "git", "format-patch",
        commit,
        f"-{num_patches}",
        f"--subject-prefix={prefix}",
        "--thread",
        "--cover-letter",
        "-o", outdir,
    ]
    if base:
        base_cmd.append(f"--base={base}")
    if to_mail and not skip_to:
        for addr in to_mail.split(","):
            addr = addr.strip()
            if addr:
                base_cmd.append(f"--to={addr}")
    if cc_mail and not skip_maintainers:
        for addr in cc_mail.split(","):
            addr = addr.strip()
            if addr:
                base_cmd.append(f"--cc={addr}")

    # ── 1st run: generate the patch files ────────────────────────
    print("\n  ── Pass 1: generate patches ──\n")
    print(f"  ▸ {' '.join(base_cmd)}\n")
    result = subprocess.run(base_cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print("git format-patch (pass 1) failed:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)

    files = [l for l in result.stdout.strip().splitlines() if l]
    for f in files:
        print(f"  ✓ {f}")

    if skip_maintainers:
        print("\n  ℹ Skipping pass 2 (--no-maintainers).")
        return files

    # ── 2nd run: re-generate with get_maintainer.pl cc ───────────
    cover_glob = os.path.join(outdir, "000*")
    get_maintainer_cmd = (
        f"scripts/get_maintainer.pl --no-rolestats --separator=, {cover_glob}"
    )

    print(f"\n  ── Pass 2: adding get_maintainer.pl cc ──\n")
    print(f"  ▸ {get_maintainer_cmd}")
    maint_result = subprocess.run(
        get_maintainer_cmd, shell=True, capture_output=True, text=True
    )
    maintainers = maint_result.stdout.strip()

    if not maintainers:
        print("  ⚠ get_maintainer.pl returned empty, skipping pass 2.",
              file=sys.stderr)
        return files

    cmd2 = base_cmd + [f"--cc={maintainers}"]
    print(f"  ▸ {' '.join(cmd2)}\n")
    result2 = subprocess.run(cmd2, capture_output=True, text=True)

    if result2.returncode != 0:
        print("git format-patch (pass 2) failed:", file=sys.stderr)
        print(result2.stderr, file=sys.stderr)
        sys.exit(1)

    files = [l for l in result2.stdout.strip().splitlines() if l]
    for f in files:
        print(f"  ✓ {f}")
    return files


def extract_trail_cover_letter(patch_path: str) -> str:
    """
    Extract changelog trail from a cover letter.

    The trail sits between the body text and the shortlog
    (first line matching 'Author (N):').  We scan forward looking
    for the first 'vN->vM:' header, then collect everything up to
    the shortlog line.
    """
    with open(patch_path) as f:
        lines = f.readlines()

    # Find the shortlog header: "Author Name (N):"
    shortlog_idx = None
    for i, line in enumerate(lines):
        if re.match(r'^\S.+ \(\d+\):', line):
            shortlog_idx = i
            break

    if shortlog_idx is None:
        return ""

    # Find the first trail header (vN->vM:) before the shortlog
    trail_start = None
    for i in range(shortlog_idx):
        if re.match(r'^v\d+->v\d+:', lines[i].strip()):
            trail_start = i
            break

    if trail_start is None:
        return ""

    # Collect everything from the first trail header up to (but not
    # including) the shortlog line, stripping trailing blank lines.
    trail_lines = lines[trail_start:shortlog_idx]
    text = "".join(trail_lines).strip("\n")
    return text


def extract_cover_letter_content(cover_path: str) -> tuple[str, str]:
    """
    Extract the subject line and body from a cover letter.

    Returns (subject, body) where:
      - subject is the text after the prefix in the Subject: header
        e.g. for 'Subject: [PATCH v2 0/3] My series' → 'My series'
      - body is everything between the first blank line after headers
        and the shortlog / trail section.
    """
    with open(cover_path) as f:
        lines = f.readlines()

    # ── Extract subject ──────────────────────────────────────────
    subject = ""
    for i, line in enumerate(lines):
        if line.startswith("Subject:"):
            # Subject may span multiple lines (folded headers)
            subj_lines = [line]
            for j in range(i + 1, len(lines)):
                # Folded header lines start with whitespace
                if lines[j].startswith(" ") or lines[j].startswith("\t"):
                    subj_lines.append(lines[j])
                else:
                    break
            full_subject = " ".join(l.strip() for l in subj_lines)
            # Extract the part after "] "
            m = re.search(r'\]\s*(.+)$', full_subject)
            if m:
                subject = m.group(1).strip()
            break

    # ── Extract body ─────────────────────────────────────────────
    # Body starts after the first blank line (end of mail headers)
    body_start = None
    for i, line in enumerate(lines):
        if line.strip() == "" and body_start is None:
            # Check that we're past the headers (after Subject, Date, etc.)
            if any(lines[j].startswith("Subject:") for j in range(i)):
                body_start = i + 1
                break

    if body_start is None:
        return subject, ""

    # Body ends at the shortlog or trail header
    body_end = len(lines)
    for i in range(body_start, len(lines)):
        # Shortlog: "Author Name (N):"
        if re.match(r'^\S.+ \(\d+\):', lines[i]):
            body_end = i
            break
        # Trail header: "vN->vM:"
        if re.match(r'^v\d+->v\d+:', lines[i].strip()):
            body_end = i
            break

    body = "".join(lines[body_start:body_end]).strip("\n")
    return subject, body


def copy_cover_letter_content(topic: str, version: int):
    """
    Copy the subject and body from the previous version's cover letter
    into the new version, replacing the git format-patch placeholders.
    """
    prev_version = version - 1
    prev_dir = os.path.join(topic, f"v{prev_version}")
    new_dir = os.path.join(topic, f"v{version}")

    prev_covers = [p for p in glob.glob(os.path.join(prev_dir, "0000-*.patch"))]
    new_covers = [p for p in glob.glob(os.path.join(new_dir, "0000-*.patch"))]

    if not prev_covers or not new_covers:
        return

    prev_cover = prev_covers[0]
    new_cover = new_covers[0]

    subject, body = extract_cover_letter_content(prev_cover)

    if not subject and not body:
        return

    with open(new_cover) as f:
        content = f.read()

    if subject:
        content = content.replace("*** SUBJECT HERE ***", subject)
    if body:
        content = content.replace("*** BLURB HERE ***", body)

    with open(new_cover, "w") as f:
        f.write(content)

    print(f"\n  📋 Cover letter content copied from v{prev_version}:")
    if subject:
        print(f"     Subject: {subject}")
    if body:
        preview = body.split("\n")[0][:60]
        print(f"     Body: {preview}...")


def add_changelog_trail(topic: str, version: int):
    """
    After generating v{version} patches, inject changelog trail by
    pulling history from v{version-1}.
    """
    prev_version = version - 1
    prev_dir = os.path.join(topic, f"v{prev_version}")

    if not os.path.isdir(prev_dir):
        print(f"\n  ℹ No previous version directory ({prev_dir}), skipping trail.")
        return

    prev_patches = find_patches_in(prev_dir)
    new_patches = find_patches_in(os.path.join(topic, f"v{version}"))

    print(f"\n  📝 Adding changelog trail (v{prev_version}->v{version}):\n")

    for num in sorted(new_patches.keys()):
        new_path = new_patches[num]
        is_cover = Path(new_path).name.startswith("0000-")

        # Get old trail from previous version (if matching patch exists)
        old_trail = ""
        if num in prev_patches:
            if is_cover:
                old_trail = extract_trail_cover_letter(prev_patches[num])
            else:
                old_trail = extract_trail(prev_patches[num])

        # Build trail block with empty new header and inject
        trail = build_trail(version, old_trail)
        if is_cover:
            inject_trail_cover_letter(new_path, trail)
        else:
            inject_trail(new_path, trail)
