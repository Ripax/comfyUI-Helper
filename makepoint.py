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
from pathlib import Path


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------

SCRIPT_PATH = Path(__file__).resolve()

# Expected location:
# <ComfyUI>/makepoint.py
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
        if node_dir.name.startswith("."):
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

    success(f"Found {len(nodes)} custom node repositories.")

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

    Create restore point in another directory:
    python makepoint.py --backup --output D:\\ComfyBackups

    Include model inventory:
    python makepoint.py --backup --models

    Restore:
    python makepoint.py --restore D:\\ComfyBackups\\ComfyUI_RestorePoint_20261114_120000

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
        "--restore",
        metavar="PATH",
        help="Restore from a restore point.",
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

    if args.backup:

        create_backup(
            output_dir=args.output,
            include_models=args.models,
        )

        return

    if args.restore:

        restore_backup(
            args.restore,
            restore_packages_enabled=not args.no_packages,
            restore_nodes_enabled=not args.no_nodes,
            restore_comfyui_enabled=not args.no_comfyui,
        )

        return

    if args.info:

        show_info()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
