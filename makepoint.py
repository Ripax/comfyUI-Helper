#!/usr/bin/env python3

"""
ComfyUI Restore Point Manager
=============================

Create a complete snapshot of a ComfyUI installation and restore it later.

Usage:

    Backup:
        python makepoint.py --backup

    Backup to a specific directory:
        python makepoint.py --backup --output "D:\\ComfyBackups"

    Restore:
        python makepoint.py --restore "D:\\ComfyBackups\\ComfyUI_RestorePoint_20261114_120000"

    Restore from a commit in Ripax/restore_points:
        python makepoint.py --restore 0123456789abcdef0123456789abcdef01234567

    Restore without installing packages:
        python makepoint.py --restore "D:\\ComfyBackups\\..." --no-packages

    Show current installation:
        python makepoint.py --info
"""

import argparse
import datetime
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------

SCRIPT_PATH = Path(__file__).resolve()

# ComfyUI Desktop layout:
#
# ComfyUI-Installs/
# └── ComfyUI/
#     ├── standalone-env/
#     └── ComfyUI/
#         ├── custom_nodes/
#         ├── models/
#         ├── comfy/
#         └── main.py
#
# makepoint.py is expected to be inside:
#   ComfyUI-Installs/ComfyUI/
#
# Detect the actual ComfyUI source directory. Prefer COMFY_ROOT when it is
# explicitly set so the script works when installed outside the repo root.

env_comfy_root = os.environ.get("COMFY_ROOT")

POSSIBLE_COMFYUI_DIRS = []

if env_comfy_root:
    comfy_root = Path(env_comfy_root).expanduser().resolve()
    POSSIBLE_COMFYUI_DIRS.extend(
        [
            comfy_root,
            comfy_root / "ComfyUI",
        ]
    )

python_environment = Path(sys.executable).resolve().parent
if python_environment.name.lower() == "standalone-env":
    desktop_root = python_environment.parent
    POSSIBLE_COMFYUI_DIRS.extend(
        [
            desktop_root,
            desktop_root / "ComfyUI",
        ]
    )

POSSIBLE_COMFYUI_DIRS.extend(
    [
        SCRIPT_PATH.parent / "ComfyUI",
        SCRIPT_PATH.parent,
    ]
)

COMFYUI_DIR = None

for path in POSSIBLE_COMFYUI_DIRS:
    if not path.exists():
        continue

    if (
        (path / "custom_nodes").is_dir()
        and (path / "main.py").exists()
    ):
        COMFYUI_DIR = path
        break

if COMFYUI_DIR is None:
    if env_comfy_root:
        COMFYUI_DIR = Path(env_comfy_root).expanduser().resolve()
    elif (SCRIPT_PATH.parent / "ComfyUI").is_dir():
        COMFYUI_DIR = SCRIPT_PATH.parent / "ComfyUI"
    else:
        COMFYUI_DIR = SCRIPT_PATH.parent

CUSTOM_NODES_DIR = COMFYUI_DIR / "custom_nodes"

DEFAULT_BACKUP_DIR = COMFYUI_DIR / "restore_points"

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def log(message):
    print(f"[MAKEPOINT] {message}")


def success(message):
    print(f"[OK]       {message}")


def warning(message):
    print(f"[WARNING]  {message}")


def error(message):
    print(f"[ERROR]    {message}")


def run_command(command, cwd=None):
    """
    Run command and return stdout.
    """
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        return result.returncode, result.stdout.strip()

    except Exception as exc:
        return 1, str(exc)


def git_command(args, cwd):
    return run_command(["git"] + args, cwd=cwd)


def read_text_file(path):
    try:
        return path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return None


# ----------------------------------------------------------------------
# Python / pip information
# ----------------------------------------------------------------------

def get_python_info():
    return {
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "executable": sys.executable,
        "platform": platform.platform(),
        "architecture": platform.machine(),
    }


def get_pip_packages():
    """
    Get the exact installed Python packages from this ComfyUI environment.
    """

    log("Collecting installed Python packages...")

    code, output = run_command(
        [
            sys.executable,
            "-m",
            "pip",
            "freeze",
        ]
    )

    if code != 0:
        warning("Could not execute pip freeze.")
        return []

    packages = []

    for line in output.splitlines():
        line = line.strip()

        if not line:
            continue

        packages.append(line)

    success(f"Found {len(packages)} Python packages.")

    return packages


# ----------------------------------------------------------------------
# Git information
# ----------------------------------------------------------------------

def get_git_info(directory):
    """
    Return git repository information for a directory.
    """

    if not (directory / ".git").exists():
        return None

    result = {
        "is_git_repository": True,
        "remote_url": None,
        "branch": None,
        "commit": None,
        "commit_short": None,
    }

    code, output = git_command(
        ["config", "--get", "remote.origin.url"],
        directory,
    )

    if code == 0:
        result["remote_url"] = output

    code, output = git_command(
        ["rev-parse", "--abbrev-ref", "HEAD"],
        directory,
    )

    if code == 0:
        result["branch"] = output

    code, output = git_command(
        ["rev-parse", "HEAD"],
        directory,
    )

    if code == 0:
        result["commit"] = output

    code, output = git_command(
        ["rev-parse", "--short", "HEAD"],
        directory,
    )

    if code == 0:
        result["commit_short"] = output

    return result


# ----------------------------------------------------------------------
# Custom nodes
# ----------------------------------------------------------------------

def find_requirements(node_dir):
    """
    Find requirements files inside a custom node repository.
    """

    files = []

    possible_names = [
        "requirements.txt",
        "requirements-win.txt",
        "requirements-windows.txt",
        "requirements-linux.txt",
        "requirements_mac.txt",
        "requirements-apple.txt",
    ]

    for name in possible_names:
        path = node_dir / name

        if path.exists():
            files.append(str(path.relative_to(node_dir)))

    return files


def find_package_metadata(node_dir):
    """
    Look for common Python package metadata.
    """

    metadata = []

    names = [
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "package.json",
    ]

    for name in names:
        path = node_dir / name

        if path.exists():
            metadata.append(name)

    return metadata


def scan_custom_nodes():
    """
    Scan ComfyUI/custom_nodes.
    """

    nodes = []

    if not CUSTOM_NODES_DIR.exists():
        warning(f"Custom nodes directory does not exist: {CUSTOM_NODES_DIR}")
        return nodes

    log(f"Scanning custom nodes: {CUSTOM_NODES_DIR}")

    for node_dir in sorted(CUSTOM_NODES_DIR.iterdir()):

        if not node_dir.is_dir():
            continue

        # Ignore hidden folders
        if node_dir.name.startswith(".") or node_dir.name == "__pycache__":
            continue

        node = {
            "name": node_dir.name,
            "path": str(node_dir),
            "git": get_git_info(node_dir),
            "requirements": find_requirements(node_dir),
            "package_metadata": find_package_metadata(node_dir),
            "files": [],
        }

        # Useful node files
        interesting_files = [
            "__init__.py",
            "README.md",
            "README.txt",
            "requirements.txt",
            "pyproject.toml",
            "setup.py",
        ]

        for filename in interesting_files:

            path = node_dir / filename

            if path.exists():
                node["files"].append(filename)

        nodes.append(node)

    success(f"Found {len(nodes)} custom nodes.")

    return nodes


# ----------------------------------------------------------------------
# ComfyUI information
# ----------------------------------------------------------------------

def get_comfyui_git_info():
    return get_git_info(COMFYUI_DIR)


def get_comfyui_version():
    """
    Try to find the ComfyUI version.
    """

    possible_files = [
        COMFYUI_DIR / "comfy" / "__init__.py",
        COMFYUI_DIR / "__version__.py",
        COMFYUI_DIR / "version.py",
    ]

    for path in possible_files:

        if not path.exists():
            continue

        content = read_text_file(path)

        if not content:
            continue

        for line in content.splitlines():

            if "__version__" in line:

                return line.strip()

    return None


# ----------------------------------------------------------------------
# Manager information
# ----------------------------------------------------------------------

def find_manager_files():
    """
    Find ComfyUI Manager configuration files.
    """

    candidates = [
        COMFYUI_DIR / "user" / "default" / "ComfyUI-Manager",
        COMFYUI_DIR / "user" / "default" / "ComfyUI-Manager" / "cache",
        COMFYUI_DIR / "custom_nodes" / "ComfyUI-Manager",
    ]

    found = []

    for path in candidates:

        if path.exists():
            found.append(str(path))

    return found


# ----------------------------------------------------------------------
# Model inventory
# ----------------------------------------------------------------------

def scan_models():
    """
    Scan model directories.

    This DOES NOT copy models.
    It only records what exists.
    """

    model_dirs = [
        "models",
    ]

    models = []

    for relative in model_dirs:

        base = COMFYUI_DIR / relative

        if not base.exists():
            continue

        for root, dirs, files in os.walk(base):

            for filename in files:

                path = Path(root) / filename

                try:
                    size = path.stat().st_size
                except OSError:
                    size = None

                models.append(
                    {
                        "path": str(path.relative_to(COMFYUI_DIR)),
                        "size": size,
                    }
                )

    return models


# ----------------------------------------------------------------------
# Backup
# ----------------------------------------------------------------------

def create_backup(output_dir=None, include_models=False):

    timestamp = datetime.datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    if output_dir:
        backup_root = Path(output_dir)
    else:
        backup_root = DEFAULT_BACKUP_DIR

    backup_dir = backup_root / f"ComfyUI_RestorePoint_{timestamp}"

    backup_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    log("")
    log("=" * 70)
    log("Creating ComfyUI Restore Point")
    log("=" * 70)
    log(f"ComfyUI : {COMFYUI_DIR}")
    log(f"Output  : {backup_dir}")
    log("")

    manifest = {
        "restore_point_format": 1,
        "created": datetime.datetime.now().isoformat(),
        "computer": platform.node(),
        "comfyui_path": str(COMFYUI_DIR),
        "python": get_python_info(),
        "comfyui": {
            "version": get_comfyui_version(),
            "git": get_comfyui_git_info(),
        },
        "python_packages": get_pip_packages(),
        "custom_nodes": scan_custom_nodes(),
        "manager": {
            "paths": find_manager_files(),
        },
        "models": [],
    }

    if include_models:
        log("Scanning models...")
        manifest["models"] = scan_models()
        success(
            f"Found {len(manifest['models'])} model files."
        )

    # Save pip freeze separately
    pip_file = backup_dir / "pip-freeze.txt"

    pip_file.write_text(
        "\n".join(manifest["python_packages"]) + "\n",
        encoding="utf-8",
    )

    # Save manifest
    manifest_file = backup_dir / "restore_point.json"

    manifest_file.write_text(
        json.dumps(
            manifest,
            indent=4,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Save custom node git information separately
    nodes_file = backup_dir / "custom_nodes.json"

    nodes_file.write_text(
        json.dumps(
            manifest["custom_nodes"],
            indent=4,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Save ComfyUI git diff if applicable
    if manifest["comfyui"]["git"]:

        code, diff = git_command(
            ["diff"],
            COMFYUI_DIR,
        )

        if code == 0:

            (backup_dir / "comfyui-git-diff.patch").write_text(
                diff,
                encoding="utf-8",
            )

    success("Restore point created.")

    log("")
    log("Files:")
    log(f"  {manifest_file}")
    log(f"  {pip_file}")
    log(f"  {nodes_file}")

    log("")
    log("Restore point summary:")
    log(f"  Python packages : {len(manifest['python_packages'])}")
    log(f"  Custom nodes    : {len(manifest['custom_nodes'])}")
    log(f"  Models          : {len(manifest['models'])}")

    log("")
    log(f"Restore with:")
    log(
        f'  "{sys.executable}" makepoint.py '
        f'--restore "{backup_dir}"'
    )

    return backup_dir


def push_backup_to_github(backup_dir, dry_run=False):
    repository_url = "https://github.com/Ripax/restore_points.git"

    if dry_run:
        log("Checking the GitHub push without publishing the restore point...")
    else:
        log("Pushing restore point to the public GitHub repository...")

    with tempfile.TemporaryDirectory(prefix="makepoint-github-") as temp_dir:
        repository_dir = Path(temp_dir) / "restore_points"
        code, output = run_command(
            [
                "git",
                "clone",
                "--branch",
                "main",
                repository_url,
                str(repository_dir),
            ]
        )

        if code != 0:
            error("Could not clone the restore point repository.")
            print(output)
            return False

        destination = repository_dir / backup_dir.name
        if destination.exists():
            error(f"A restore point named {backup_dir.name} already exists on GitHub.")
            return False

        shutil.copytree(backup_dir, destination)

        code, output = git_command(["add", "--", backup_dir.name], repository_dir)
        if code != 0:
            error("Could not stage the restore point.")
            print(output)
            return False

        code, output = git_command(
            ["commit", "-m", f"Add restore point {backup_dir.name}"],
            repository_dir,
        )
        if code != 0:
            error("Could not commit the restore point. Check your Git identity configuration.")
            print(output)
            return False

        push_args = ["push", "origin", "main"]
        if dry_run:
            push_args.insert(1, "--dry-run")

        code, output = git_command(push_args, repository_dir)
        if code != 0:
            if dry_run:
                error("GitHub push dry run failed. Check your GitHub credentials and access.")
            else:
                error("Could not push the restore point. Check your GitHub credentials and access.")
            print(output)
            return False

    if dry_run:
        success(f"GitHub push dry run passed; nothing was published to {repository_url}.")
    else:
        success(f"Restore point pushed to {repository_url}.")
    return True


def is_commit_id(value):
    return (
        4 <= len(value) <= 40
        and all(character in "0123456789abcdefABCDEF" for character in value)
    )


def print_restore_points_tui(title, headers, rows, empty_message):
    display_rows = rows or [[empty_message] + [""] * (len(headers) - 1)]
    widths = [
        max(
            len(header),
            *(len(row[index]) for row in display_rows),
        )
        for index, header in enumerate(headers)
    ]
    border = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
    content_width = sum(widths) + 3 * len(widths) - 1

    print()
    print(border)
    print(f"| {title.center(content_width - 2)} |")
    print(border)
    print("| " + " | ".join(
        header.ljust(width)
        for header, width in zip(headers, widths)
    ) + " |")
    print(border)

    for row in display_rows:
        print("| " + " | ".join(
            value.ljust(width)
            for value, width in zip(row, widths)
        ) + " |")

    print(border)


def list_local_restore_points():
    if not DEFAULT_BACKUP_DIR.is_dir():
        print_restore_points_tui(
            "LOCAL RESTORE POINTS",
            ["DATE", "BACKUP", "RESTORE PATH"],
            [],
            "No local restore points found",
        )
        return True

    try:
        backup_dirs = [
            path
            for path in DEFAULT_BACKUP_DIR.iterdir()
            if path.is_dir() and (path / "restore_point.json").is_file()
        ]
    except OSError as exc:
        error(f"Could not list local restore points: {exc}")
        return False

    restore_points = []
    for backup_dir in backup_dirs:
        manifest_file = backup_dir / "restore_point.json"
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warning(f"Skipping invalid local restore point {backup_dir}: {exc}")
            continue

        if not isinstance(manifest, dict):
            warning(f"Skipping invalid local restore point manifest: {manifest_file}")
            continue

        created = manifest.get("created", "unknown")
        restore_points.append(
            {
                "created": str(created) if created else "unknown",
                "path": backup_dir,
            }
        )

    restore_points.sort(
        key=lambda item: (item["created"] != "unknown", item["created"]),
        reverse=True,
    )

    print_restore_points_tui(
        f"LOCAL RESTORE POINTS ({len(restore_points)})",
        ["DATE", "BACKUP", "RESTORE PATH"],
        [
            [
                restore_point["created"],
                restore_point["path"].name,
                str(restore_point["path"]),
            ]
            for restore_point in restore_points
        ],
        "No local restore points found",
    )

    return True


def list_github_restore_points():
    repository_url = "https://github.com/Ripax/restore_points.git"

    with tempfile.TemporaryDirectory(prefix="makepoint-list-") as temp_dir:
        repository_dir = Path(temp_dir) / "restore_points"
        code, output = run_command(
            [
                "git",
                "clone",
                "--branch",
                "main",
                repository_url,
                str(repository_dir),
            ]
        )
        if code != 0:
            error("Could not clone the restore point repository.")
            print(output)
            return False

        code, output = git_command(
            ["ls-tree", "--name-only", "-d", "HEAD"],
            repository_dir,
        )
        if code != 0:
            error("Could not list restore points in the GitHub repository.")
            print(output)
            return False

        restore_points = []
        for directory_name in output.splitlines():
            manifest_file = repository_dir / directory_name / "restore_point.json"
            if not manifest_file.is_file():
                continue

            try:
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                error(f"Could not read {manifest_file}: {exc}")
                return False

            code, commit_id = git_command(
                [
                    "log",
                    "-1",
                    "--format=%H",
                    "--diff-filter=A",
                    "HEAD",
                    "--",
                    f"{directory_name}/restore_point.json",
                ],
                repository_dir,
            )
            if code != 0 or not commit_id:
                error(f"Could not find the commit for {directory_name}.")
                print(commit_id)
                return False

            restore_points.append(
                {
                    "created": manifest.get("created", "unknown"),
                    "name": directory_name,
                    "commit": commit_id,
                }
            )

        restore_points.sort(
            key=lambda item: item["created"],
            reverse=True,
        )

        print_restore_points_tui(
            f"GITHUB RESTORE POINTS ({len(restore_points)})",
            ["DATE", "BACKUP", "COMMIT ID"],
            [
                [
                    str(restore_point["created"]),
                    restore_point["name"],
                    restore_point["commit"],
                ]
                for restore_point in restore_points
            ],
            "No GitHub restore points found",
        )

    print("Restore a GitHub backup with: python makepoint.py --restore <COMMIT_ID>")

    return True


def download_github_restore_point(commit_id, destination_dir):
    repository_url = "https://github.com/Ripax/restore_points.git"
    repository_dir = Path(destination_dir) / "restore_points"

    log(f"Downloading restore point for commit {commit_id}...")

    code, output = run_command(
        [
            "git",
            "clone",
            "--branch",
            "main",
            repository_url,
            str(repository_dir),
        ]
    )
    if code != 0:
        error("Could not clone the restore point repository.")
        print(output)
        return None

    code, resolved_commit = git_command(
        ["rev-parse", "--verify", f"{commit_id}^{{commit}}"],
        repository_dir,
    )
    if code != 0:
        error(f"Commit {commit_id} was not found in the restore point repository.")
        print(resolved_commit)
        return None

    code, output = git_command(
        [
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "-r",
            resolved_commit,
        ],
        repository_dir,
    )
    if code != 0:
        error(f"Could not inspect commit {resolved_commit}.")
        print(output)
        return None

    backup_dirs = {
        Path(*changed_file.split("/")).parent
        for changed_file in output.splitlines()
        if changed_file.endswith("/restore_point.json")
    }

    if not backup_dirs:
        error(f"Commit {resolved_commit} does not contain a restore point.")
        return None

    if len(backup_dirs) != 1:
        error(
            f"Commit {resolved_commit} contains multiple restore points; "
            "use a commit that adds exactly one."
        )
        return None

    code, output = git_command(
        ["checkout", "--detach", resolved_commit],
        repository_dir,
    )
    if code != 0:
        error(f"Could not check out commit {resolved_commit}.")
        print(output)
        return None

    backup_path = repository_dir / next(iter(backup_dirs))
    if not (backup_path / "restore_point.json").is_file():
        error(f"Restore point manifest is missing from commit {resolved_commit}.")
        return None

    success(f"Downloaded restore point: {backup_path.name}")
    return backup_path


# ----------------------------------------------------------------------
# Restore
# ----------------------------------------------------------------------

def install_requirements(requirements_file):

    log(f"Installing: {requirements_file}")

    code, output = run_command(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            str(requirements_file),
        ]
    )

    print(output)

    return code == 0


def restore_git_repository(node, target_dir):

    git_info = node.get("git")

    if not git_info:
        warning(
            f"{node['name']}: no git information available."
        )
        return

    remote = git_info.get("remote_url")
    commit = git_info.get("commit")

    if not remote:
        warning(
            f"{node['name']}: no Git remote URL."
        )
        return

    target_dir.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if target_dir.exists():

        log(
            f"{node['name']}: already exists, updating..."
        )

        if (target_dir / ".git").exists():

            git_command(
                ["fetch", "--all"],
                target_dir,
            )

            if commit:

                code, output = git_command(
                    ["checkout", commit],
                    target_dir,
                )

                if code != 0:
                    warning(output)

            return

    log(
        f"Cloning {node['name']}..."
    )

    code, output = run_command(
        [
            "git",
            "clone",
            remote,
            str(target_dir),
        ]
    )

    if code != 0:

        warning(
            f"Could not clone {node['name']}:"
        )

        print(output)

        return

    if commit:

        code, output = git_command(
            ["checkout", commit],
            target_dir,
        )

        if code != 0:
            warning(output)


def restore_packages(manifest):

    packages = manifest.get(
        "python_packages",
        [],
    )

    if not packages:
        warning("No Python packages found in restore point.")
        return

    log(
        f"Restoring {len(packages)} Python packages..."
    )

    # Write temporary requirements file
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        delete=False,
        encoding="utf-8",
    ) as temp:

        for package in packages:
            temp.write(package + "\n")

        temp_path = temp.name

    try:

        code, output = run_command(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                temp_path,
            ]
        )

        print(output)

        if code == 0:
            success("Python packages restored.")
        else:
            warning(
                "Some Python packages could not be restored."
            )

    finally:

        try:
            os.remove(temp_path)
        except OSError:
            pass


def restore_custom_nodes(manifest):

    nodes = manifest.get(
        "custom_nodes",
        [],
    )

    if not nodes:
        warning("No custom nodes found.")
        return

    log("")
    log(
        f"Restoring {len(nodes)} custom nodes..."
    )

    for node in nodes:

        name = node["name"]

        # The backup contains the original path.
        # Normally this should be ComfyUI/custom_nodes/<name>
        target = CUSTOM_NODES_DIR / name

        restore_git_repository(
            node,
            target,
        )

        # Install node-specific requirements
        for requirement in node.get(
            "requirements",
            [],
        ):

            requirement_file = target / requirement

            if requirement_file.exists():

                install_requirements(
                    requirement_file
                )


def restore_comfyui(manifest):

    comfy = manifest.get(
        "comfyui",
        {}
    )

    git_info = comfy.get("git")

    if not git_info:
        warning(
            "No ComfyUI Git information found."
        )
        return

    commit = git_info.get("commit")

    if not commit:
        return

    if not (COMFYUI_DIR / ".git").exists():
        warning(
            "Current ComfyUI installation is not a Git repository."
        )
        return

    log(
        f"ComfyUI restore commit: {commit}"
    )

    code, output = git_command(
        ["fetch", "--all"],
        COMFYUI_DIR,
    )

    if code != 0:
        warning(output)

    code, output = git_command(
        ["checkout", commit],
        COMFYUI_DIR,
    )

    if code == 0:
        success(
            f"ComfyUI restored to {commit}"
        )
    else:
        warning(output)


def restore_backup(
    backup_path,
    restore_packages_enabled=True,
    restore_nodes_enabled=True,
    restore_comfyui_enabled=True,
):

    backup_path = Path(backup_path)

    manifest_file = backup_path / "restore_point.json"

    if not manifest_file.exists():

        error(
            f"Restore point not found:\n{manifest_file}"
        )

        sys.exit(1)

    log("")
    log("=" * 70)
    log("ComfyUI Restore")
    log("=" * 70)
    log(f"Restore point: {backup_path}")
    log("")

    manifest = json.loads(
        manifest_file.read_text(
            encoding="utf-8"
        )
    )

    print(
        json.dumps(
            {
                "created": manifest.get("created"),
                "comfyui": manifest.get("comfyui"),
                "python": manifest.get("python"),
                "package_count": len(
                    manifest.get(
                        "python_packages",
                        []
                    )
                ),
                "custom_node_count": len(
                    manifest.get(
                        "custom_nodes",
                        []
                    )
                ),
            },
            indent=4,
        )
    )

    log("")
    warning(
        "This will modify your current ComfyUI installation."
    )

    answer = input(
        "Continue? [y/N]: "
    ).strip().lower()

    if answer not in (
        "y",
        "yes",
    ):

        log("Restore cancelled.")
        return

    if restore_comfyui_enabled:
        restore_comfyui(manifest)

    if restore_nodes_enabled:
        restore_custom_nodes(manifest)

    if restore_packages_enabled:
        restore_packages(manifest)

    log("")
    success("Restore completed.")
    log("")
    log(
        "Restart ComfyUI after the restore."
    )


# ----------------------------------------------------------------------
# Info
# ----------------------------------------------------------------------

def show_info():

    log("")
    log("=" * 70)
    log("Current ComfyUI Installation")
    log("=" * 70)

    print(
        json.dumps(
            {
                "ComfyUI": str(COMFYUI_DIR),
                "Python": get_python_info(),
                "ComfyUI Version": get_comfyui_version(),
                "Git": get_comfyui_git_info(),
                "Custom Nodes Directory": str(CUSTOM_NODES_DIR),
                "Custom Nodes": [
                    node["name"]
                    for node in scan_custom_nodes()
                ],
                "Packages": len(
                    get_pip_packages()
                ),
            },
            indent=4,
        )
    )


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Create and restore ComfyUI installation "
            "restore points."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Examples:

    Create restore point:
    python makepoint.py --backup

    Create and push a restore point to the public GitHub repository:
    python makepoint.py --backup --github

    Test backup creation without keeping files:
    python makepoint.py --backup --dry-run

    Test backup creation and GitHub push access without publishing:
    python makepoint.py --backup --github --dry-run

    Create restore point in another directory:
    python makepoint.py --backup --output D:\\ComfyBackups

    Include model inventory:
    python makepoint.py --backup --models

    Restore:
    python makepoint.py --restore D:\\ComfyBackups\\ComfyUI_RestorePoint_20261114_120000

    Restore from a GitHub restore-point commit:
    python makepoint.py --restore 0123456789abcdef0123456789abcdef01234567

    List local and GitHub restore points:
    python makepoint.py --restore list

    Restore only Python packages:
    python makepoint.py --restore D:\\Backup --nodes-only false

    Show current installation:
    python makepoint.py --info
        """,
    )

    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create a ComfyUI restore point.",
    )

    parser.add_argument(
        "--github",
        action="store_true",
        help=(
            "Push the new restore point to the public "
            "Ripax/restore_points GitHub repository."
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run backup checks in a temporary directory, then remove it. "
            "With --github, also test the push without publishing."
        ),
    )

    parser.add_argument(
        "--restore",
        metavar="PATH_OR_COMMIT",
        help=(
            "Restore from a local path or GitHub commit, or use 'list' "
            "to list local and GitHub restore points."
        ),
    )

    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Directory where the restore point will be created.",
    )

    parser.add_argument(
        "--models",
        action="store_true",
        help="Include model inventory in the restore point.",
    )

    parser.add_argument(
        "--no-packages",
        action="store_true",
        help="Do not restore Python packages.",
    )

    parser.add_argument(
        "--no-nodes",
        action="store_true",
        help="Do not restore custom nodes.",
    )

    parser.add_argument(
        "--no-comfyui",
        action="store_true",
        help="Do not restore the ComfyUI Git revision.",
    )

    parser.add_argument(
        "--info",
        action="store_true",
        help="Show current ComfyUI installation information.",
    )

    args = parser.parse_args()

    if args.github and not args.backup:
        parser.error("--github can only be used with --backup.")

    if args.backup:

        if args.dry_run:
            if args.output:
                parser.error("--output cannot be used with --dry-run.")

            with tempfile.TemporaryDirectory(prefix="makepoint-dry-run-") as temp_dir:
                backup_dir = create_backup(
                    output_dir=temp_dir,
                    include_models=args.models,
                )

                if args.github and not push_backup_to_github(
                    backup_dir,
                    dry_run=True,
                ):
                    return 1

            success("Dry run completed; temporary backup files were removed.")
            return

        backup_dir = create_backup(
            output_dir=args.output,
            include_models=args.models,
        )

        if args.github and not push_backup_to_github(backup_dir):
            return 1

        return

    if args.restore:

        if args.restore.lower() == "list":
            local_success = list_local_restore_points()
            github_success = list_github_restore_points()
            return 0 if local_success and github_success else 1

        restore_options = {
            "restore_packages_enabled": not args.no_packages,
            "restore_nodes_enabled": not args.no_nodes,
            "restore_comfyui_enabled": not args.no_comfyui,
        }

        restore_path = Path(args.restore)
        if restore_path.exists() or not is_commit_id(args.restore):
            restore_backup(args.restore, **restore_options)
        else:
            with tempfile.TemporaryDirectory(prefix="makepoint-restore-") as temp_dir:
                backup_path = download_github_restore_point(args.restore, temp_dir)
                if backup_path is None:
                    return 1

                restore_backup(backup_path, **restore_options)

        return

    if args.info:

        show_info()
        return

    parser.print_help()


if __name__ == "__main__":
    sys.exit(main())
