# gfs – Git Format-patch Series helper

A CLI tool built on top of `git format-patch` that simplifies the Linux
kernel upstream patch workflow. Instead of manually juggling format-patch
flags, maintainer lists, and changelog trails across versions, `gfs`
handles it all in a single command:

- **Versioned patch series** — generate v1, v2, v3, … with one command.
- **Automatic maintainer CCs** — runs `get_maintainer.pl` and adds the
  right CCs for you.
- **Changelog trail injection** — automatically carries forward the
  changelog history across versions, so reviewers see what changed.
- **Checkpatch integration** — run `checkpatch.pl` on your series
  before sending.

## Requirements

- Python 3.10+
- Git
- **All commands must be run from the root of a Linux kernel tree**
  (the tool needs `scripts/get_maintainer.pl` and `scripts/checkpatch.pl`).

## Installation

Install from PyPI:

```bash
pip install gfs-tool
```

Or from source (from the gfs directory):

```bash
pip install .
```

Or in editable/development mode:

```bash
pip install -e .
```

After installation, the `gfs` command is available system-wide:

```bash
gfs --help
```

## Quick start

```bash
# All gfs commands must be run from the root of a Linux kernel tree
cd /path/to/linux

# 1. Create v1 of a new series
gfs init -c <sha> -n 3 --prefix "PATCH" -t for-pm-upstream --to user@example.com --cc user@example.com

# 2. Run checkpatch
gfs check -t for-pm-upstream

# 3. After review → generate v2
gfs -v 2 -c <sha> -n 3 --prefix "PATCH v2" -t for-pm-upstream

# 4. Fill in changelog notes manually, then checkpatch again
gfs check -t for-pm-upstream
```

---

## Commands

### `gfs init` — Initialise a new patch series (v1)

Creates the first version of a patch series and saves `--to` / `--cc`
in `<topic>/.series.json` so you don't have to repeat them.

```bash
gfs init -c <commit-sha> -n <num-patches> --prefix <prefix> -t <topic> [--to <email>] [--cc <email>]
```

| Flag | Required | Description |
|------|----------|-------------|
| `-c`, `--commit` | ✅ | Base commit SHA for `git format-patch` |
| `-n`, `--num-patches` | ✅ | Number of patches to generate |
| `-p`, `--prefix` | ✅ | Subject prefix, e.g. `"PATCH"`, `"PATCH v2"` |
| `-t`, `--topic` | ✅ | Topic output directory, e.g. `for-pm-upstream` |
| `--to` | | `To:` email address |
| `--cc` | | `Cc:` email address |

**Example:**

```bash
gfs init -c abc1234 -n 3 --prefix "PATCH" -t for-topic --to user@example.com --cc user@example.com
```

**Output structure:**

```
for-topic/
├── .series.json            ← saved to/cc config
└── v1/
    ├── 0000-cover-letter.patch
    ├── 0001-subsys-Add-foo-support.patch
    ├── 0002-subsys-Add-bar-support.patch
    └── 0003-subsys-Add-baz-support.patch
```

---

### `gfs -v N` — Generate a new version (v2, v3, …)

Generates the next version of the patch series. Automatically injects
changelog trail headers into every patch.

```bash
gfs -v <version> -c <commit-sha> -n <num-patches> --prefix <prefix> -t <topic> [--to <email>] [--cc <email>]
```

| Flag | Required | Description |
|------|----------|-------------|
| `-v`, `--version` | ✅ | Version number (2, 3, 4, …) |
| `-c`, `--commit` | ✅ | Base commit SHA |
| `-n`, `--num-patches` | ✅ | Number of patches |
| `-p`, `--prefix` | ✅ | Subject prefix, e.g. `"PATCH v2"` |
| `-t`, `--topic` | ✅ | Topic directory |
| `--to` | | Override saved `To:` address |
| `--cc` | | Override saved `Cc:` address |

**Example:**

```bash
gfs -v 2 -c abc1234 -n 3 --prefix "PATCH v2" -t for-topic
```

---

### `gfs check` — Run checkpatch.pl

Runs `./scripts/checkpatch.pl --strict --codespell` on all patches
in the given topic directory.

```bash
gfs check -t <topic> [-v <version>]
```

| Flag | Required | Description |
|------|----------|-------------|
| `-t`, `--topic` | ✅ | Topic directory |
| `-v`, `--version` | | Version to check (default: latest) |

**Examples:**

```bash
# Check latest version
gfs check -t for-topic

# Check a specific version
gfs check -t for-topic -v 3
```

---

## How it works

### Two-pass `git format-patch`

Every `init` and `-v N` invocation runs `git format-patch` **twice**:

1. **Pass 1** — generates the patch files:
   ```
   git format-patch <sha> -N --to=<to> --cc=<cc> --subject-prefix="PATCH vN" --thread --cover-letter -o <topic>/vN/
   ```

2. **Pass 2** — re-generates adding maintainers in CC:
   ```
   git format-patch <sha> -N --to=<to> --cc=<cc> --subject-prefix="PATCH vN" --thread --cover-letter -o <topic>/vN/ --cc="$(scripts/get_maintainer.pl --no-rolestats --separator=, <topic>/vN/000*)"
   ```

   The second pass needs the files from the first pass to exist so that
   `get_maintainer.pl` can parse them and determine the correct
   maintainers/reviewers.

### Changelog trail injection

For version ≥ 2, `gfs` automatically injects changelog headers between
`---` and the diffstat in every patch file. It reads the trail from the
**previous version** and prepends a new empty header.

You then fill in the details manually.

**v2 patches will contain:**

```diff
Signed-off-by: You <you@example.com>
---
v1->v2:
 - 

 drivers/subsys/foo.c | 131 +++...
```

**v3 patches will contain (after you filled v2):**

```diff
Signed-off-by: You <you@example.com>
---
v2->v3:
 - 

v1->v2:
 - Refactored initialization logic.

 drivers/subsys/foo.c | 118 +++...
```

**v4 patches will contain:**

```diff
Signed-off-by: You <you@example.com>
---
v3->v4:
 - 

v2->v3:
 - Simplified error handling.

v1->v2:
 - Refactored initialization logic.

 drivers/subsys/foo.c | 117 +++...
```

### Per-topic configuration

Each topic directory stores a `.series.json` with saved `to` and `cc`
addresses, so you don't need to repeat them every time:

```json
{
  "to": "user@example.com",
  "cc": "user@example.com"
}
```

This also means you can work on **multiple series in parallel**, each
with its own independent config.

---

## Typical workflow

```bash
# All gfs commands must be run from the root of a Linux kernel tree
cd /path/to/linux

# ── Start a new series ───────────────────────────────────────────
gfs init -c abc123 -n 3 --prefix "PATCH" -t for-pm-upstream --to user@example.com --cc user@example.com

# ── Check patches ────────────────────────────────────────────────
gfs check -t for-pm-upstream

# ── Send v1 with git send-email ──────────────────────────────────
git send-email for-pm-upstream/v1/*.patch

# ── After review: amend commits, then generate v2 ────────────────
gfs -v 2 -c abc123 -n 3 --prefix "PATCH v2" -t for-pm-upstream

# ── Fill in changelog notes in each patch file ───────────────────
vim for-pm-upstream/v2/0001-*.patch   # add notes under "v1->v2:"

# ── Check & send v2 ─────────────────────────────────────────────
gfs check -t for-pm-upstream
git send-email for-pm-upstream/v2/*.patch

# ── v3, v4, … repeat ────────────────────────────────────────────
gfs -v 3 -c abc123 -n 3 --prefix "PATCH v3" -t for-pm-upstream
```

---

## Directory layout

After several iterations your topic directory will look like:

```
for-topic/
├── .series.json
├── v1/
│   ├── 0000-cover-letter.patch
│   ├── 0001-subsys-Add-foo-support.patch
│   ├── 0002-subsys-Add-bar-support.patch
│   └── 0003-subsys-Add-baz-support.patch
├── v2/
│   ├── 0000-cover-letter.patch
│   ├── ...
├── v3/
│   ├── ...
└── v4/
    └── ...
```

---

## Example session

A complete walk-through from v1 to v3 of a 3-patch series.

### 1. Initialise the series (v1)

```console
$ cd /path/to/linux

$ gfs init -c abc1234 -n 3 --prefix "PATCH" -t for-topic --to user@example.com --cc user@example.com

  ✓ config saved → for-topic/.series.json

  ── Pass 1: generate patches ──

  ✓ for-topic/v1/0000-cover-letter.patch
  ✓ for-topic/v1/0001-subsys-Add-foo-support.patch
  ✓ for-topic/v1/0002-subsys-Add-bar-support.patch
  ✓ for-topic/v1/0003-subsys-Add-baz-support.patch

  ── Pass 2: adding get_maintainer.pl cc ──

  ✓ for-topic/v1/0000-cover-letter.patch
  ✓ for-topic/v1/0001-subsys-Add-foo-support.patch
  ✓ for-topic/v1/0002-subsys-Add-bar-support.patch
  ✓ for-topic/v1/0003-subsys-Add-baz-support.patch
```

### 2. Check with checkpatch and send v1

```console
$ gfs check -t for-topic

  ── checkpatch.pl on for-topic/v1 ──

  ▸ ./scripts/checkpatch.pl --strict --codespell for-topic/v1/*.patch

$ git send-email for-topic/v1/*.patch
```

### 3. After review — generate v2

Amend commits based on review feedback, then:

```console
$ gfs -v 2 -c abc1234 -n 3 --prefix "PATCH v2" -t for-topic

  ── Pass 1: generate patches ──
  ...
  ── Pass 2: adding get_maintainer.pl cc ──
  ...

  📝 Adding changelog trail (v1->v2):

  ✓ trail injected → 0000-cover-letter.patch
  ✓ trail injected → 0001-subsys-Add-foo-support.patch
  ✓ trail injected → 0002-subsys-Add-bar-support.patch
  ✓ trail injected → 0003-subsys-Add-baz-support.patch
```

Each patch and the cover letter now contain:

```
v1->v2:
 - 
```

### 4. Fill in the changelog notes

Edit each patch and write what changed:

```console
$ vim for-topic/v2/0001-*.patch
```

Replace the empty ` - ` with actual notes:

```diff
v1->v2:
 - Refactored initialization logic.
```

### 5. Check and send v2

```console
$ gfs check -t for-topic
$ git send-email for-topic/v2/*.patch
```

### 6. After another review — generate v3

```console
$ gfs -v 3 -c abc1234 -n 3 --prefix "PATCH v3" -t for-topic
```

The changelog trail now accumulates automatically. Each patch contains:

```diff
Signed-off-by: You <you@example.com>
---
v2->v3:
 - 

v1->v2:
 - Refactored initialization logic.

 drivers/subsys/foo.c | 118 +++...
```

And the cover letter contains the same trail before the shortlog:

```
v2->v3:
 - 

v1->v2:
 - Refactored initialization logic.

User Name (3):
  subsys: Add foo support
  ...
```

Fill in `v2->v3:`, run checkpatch, send — and repeat for v4, v5, …

---

## Sending the series

Once your patches are ready, send them with `git send-email`:

```bash
git send-email --cc linux-kernel@vger.kernel.org ./for-topic/v1/*.patch
```
