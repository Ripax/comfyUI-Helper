# Copilot instructions for comfyUI-Helper

## Project overview

This repository is a small Python utility, not a package with multiple modules. The main entry point is `makepoint.py`, which creates a restore point for a ComfyUI installation and can later restore it. The script is designed to live in the root of a ComfyUI checkout, where it derives the installation path from its own parent directory.

The backup workflow records:

- Python interpreter details and `pip freeze` output
- ComfyUI git metadata and, when available, a git diff patch
- Custom node inventory from `<ComfyUI>/custom_nodes`
- Node-specific requirements and package metadata (`requirements.txt`, `pyproject.toml`, etc.)
- Optional model inventory for the `<ComfyUI>/models` directory
- A JSON manifest (`restore_point.json`) plus `custom_nodes.json` and `pip-freeze.txt`

The restore workflow reads that manifest and then optionally restores the ComfyUI Git revision, custom nodes, and Python packages.

## Build, test, and lint commands

There is no formal build, test, or lint configuration in this repository.

Use these smoke checks instead:

- `python makepoint.py --help`
- `python makepoint.py --info`
- `python -m py_compile makepoint.py`

Backup/restore commands are the actual operational validation path:

- Create a backup: `python makepoint.py --backup`
- Create a backup in a custom location: `python makepoint.py --backup --output "D:\ComfyBackups"`
- Include model inventory: `python makepoint.py --backup --models`
- Restore from a backup: `python makepoint.py --restore "D:\ComfyBackups\ComfyUI_RestorePoint_20261114_120000"`
- Restore only Python packages: `python makepoint.py --restore "D:\ComfyBackups\..." --no-nodes --no-comfyui`
- Restore only custom nodes: `python makepoint.py --restore "D:\ComfyBackups\..." --no-packages --no-comfyui`

If a change affects CLI semantics, validate with `--help` plus a small manual run against a temporary restore point directory.

## High-level architecture

`makepoint.py` is a single-file script organized around a few phases:

1. Environment discovery
   - `get_python_info()` and `get_pip_packages()` collect the runtime and package state.
   - `get_comfyui_git_info()` and `get_comfyui_version()` inspect the ComfyUI installation.
   - `find_manager_files()` checks for known ComfyUI Manager paths.

2. Custom node scanning
   - `scan_custom_nodes()` walks `<ComfyUI>/custom_nodes` and records node metadata.
   - It attempts to detect Git repos, `requirements.txt` files, and common package metadata files.
   - This is the main input to the restore logic for custom node reinstallation.

3. Backup creation
   - `create_backup()` builds a manifest with the environment snapshot and writes files to a timestamped backup directory.
   - It creates `restore_point.json`, `custom_nodes.json`, and a `pip-freeze.txt` export.
   - `--models` adds a model inventory by walking the `models` directory without copying model files.

4. Restore flow
   - `restore_backup()` loads the manifest, warns that the current installation will be modified, and asks for confirmation.
   - It can optionally restore the ComfyUI Git revision, custom nodes, and Python packages.
   - `restore_custom_nodes()` re-clones or updates each custom node repo and installs their requirements.
   - `restore_packages()` writes a temp requirements file and runs `python -m pip install -r ...`.

5. Human-facing CLI
   - `argparse` handles `--backup`, `--restore`, `--output`, `--models`, `--no-packages`, `--no-nodes`, `--no-comfyui`, and `--info`.
   - All runtime behavior is intentionally transparent and command-line driven.

## Key conventions

- The script assumes it sits directly inside a ComfyUI installation root; path logic is built around `Path(__file__).resolve().parent`.
- Do not assume this repository is a reusable Python package. Most logic is in one script and intentionally uses stdlib modules only.
- Backup and restore behavior are intentionally destructive when used with `--restore`; the script asks for confirmation before modifying the current ComfyUI installation.
- Custom node restoration is Git-based: if a node repo has a `remote_url` and commit metadata, the script will clone or update it and check out the recorded commit.
- Python package restoration is done via `pip install -r` on the saved package list, not by re-creating a venv or packaging metadata.
- Output paths are relative to the ComfyUI install unless `--output` is explicitly provided.
- Manifest files are the source of truth for restoration; avoid making assumptions from the live filesystem alone when working in restore logic.
- Preserve the existing CLI contract and flags even when adding or refactoring behavior.

## Additional repo notes

- README content is minimal; this script is the primary documentation source.
- There is no `.github/copilot-instructions.md` or other repo-specific AI guidance file currently in place.
- There are no detected package managers, test frameworks, or linters configured for this repository beyond the Python standard library and the script’s CLI entry point.
