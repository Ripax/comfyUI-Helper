#!/usr/bin/env python3

"""
ComfyUI Makepoint Installer
===========================

Installs the makepoint command on:

    Windows
    Linux
    macOS

The installer does NOT require makepoint.py to be inside
the ComfyUI installation directory.

Usage:

    python install.py

    python install.py --status

    python install.py --uninstall

    python install.py --system
"""

import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path
import argparse


APP_NAME = "makepoint"
SCRIPT_NAME = "makepoint.py"

SYSTEM = platform.system().lower()

IS_WINDOWS = SYSTEM == "windows"
IS_MACOS = SYSTEM == "darwin"
IS_LINUX = SYSTEM == "linux"


# ----------------------------------------------------------------------
# Source
# ----------------------------------------------------------------------

SOURCE_DIR = Path(__file__).resolve().parent
SOURCE_SCRIPT = SOURCE_DIR / SCRIPT_NAME


# ----------------------------------------------------------------------
# Installation directories
# ----------------------------------------------------------------------

def user_install_dir():

    comfy_root = os.environ.get("COMFY_ROOT")

    if comfy_root:
        return Path(comfy_root).expanduser().resolve()

    if IS_WINDOWS:

        local_appdata = os.environ.get("LOCALAPPDATA")

        if not local_appdata:
            local_appdata = (
                Path.home()
                / "AppData"
                / "Local"
            )

        return Path(local_appdata) / "makepoint"

    return Path.home() / ".local" / "bin"


def system_install_dir():

    if IS_WINDOWS:

        program_data = os.environ.get(
            "PROGRAMDATA",
            r"C:\ProgramData",
        )

        return Path(program_data) / "makepoint"

    return Path("/usr/local/bin")


# ----------------------------------------------------------------------
# Output helpers
# ----------------------------------------------------------------------

def info(message):
    print(f"[INFO]    {message}")


def success(message):
    print(f"[OK]      {message}")


def warning(message):
    print(f"[WARNING] {message}")


def error(message):
    print(f"[ERROR]   {message}")


# ----------------------------------------------------------------------
# PATH helpers
# ----------------------------------------------------------------------

def current_path():

    return os.environ.get(
        "PATH",
        "",
    ).split(os.pathsep)


def path_contains(directory):

    directory = str(
        Path(directory).resolve()
    ).lower()

    for entry in current_path():

        if not entry:
            continue

        try:

            if str(
                Path(entry).resolve()
            ).lower() == directory:

                return True

        except Exception:
            pass

    return False


def add_windows_user_path(directory):

    directory = str(
        Path(directory).resolve()
    )

    powershell_script = f"""
$dir = '{directory}'
$current = [Environment]::GetEnvironmentVariable('Path', 'User')

if ([string]::IsNullOrWhiteSpace($current)) {{
    $current = ''
}}

$parts = $current -split ';' |
    Where-Object {{ $_ -and $_ -ne $dir }}

$newPath = ($parts + $dir) -join ';'

[Environment]::SetEnvironmentVariable(
    'Path',
    $newPath,
    'User'
)
"""

    try:

        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                powershell_script,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        if result.returncode == 0:

            success(
                "Added makepoint to Windows user PATH."
            )

            return True

        warning(
            result.stdout.strip()
        )

    except Exception as exc:

        warning(
            f"Could not update PATH: {exc}"
        )

    return False


def add_unix_user_path(directory):

    home = Path.home()

    shell = os.environ.get(
        "SHELL",
        "",
    )

    shell_name = Path(shell).name

    if shell_name == "zsh":

        rc_files = [
            home / ".zshrc",
        ]

    elif shell_name == "fish":

        rc_files = [
            home
            / ".config"
            / "fish"
            / "config.fish",
        ]

    else:

        rc_files = [
            home / ".bashrc",
            home / ".profile",
        ]

    for rc_file in rc_files:

        try:

            rc_file.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            if rc_file.exists():

                content = rc_file.read_text(
                    encoding="utf-8",
                    errors="ignore",
                )

                if ".local/bin" in content:
                    continue

            with rc_file.open(
                "a",
                encoding="utf-8",
            ) as fh:

                fh.write(
                    "\n"
                    "# ComfyUI makepoint\n"
                    'export PATH="$HOME/.local/bin:$PATH"\n'
                )

            success(
                f"Updated {rc_file}"
            )

        except Exception as exc:

            warning(
                f"Could not update {rc_file}: {exc}"
            )

    return True


# ----------------------------------------------------------------------
# Windows launcher
# ----------------------------------------------------------------------

def create_windows_launcher(
    install_dir,
    installed_script,
):

    launcher = install_dir / "makepoint.cmd"

    python_exe = Path(
        sys.executable
    ).resolve()

    comfy_root = os.environ.get("COMFY_ROOT")
    comfy_root_line = (
        f'set "COMFY_ROOT={comfy_root}"\n'
        if comfy_root
        else ""
    )

    content = f"""@echo off
setlocal

{comfy_root_line}
"{python_exe}" "{installed_script}" %*

set "EXITCODE=%ERRORLEVEL%"

endlocal
exit /b %EXITCODE%
"""

    launcher.write_text(
        content,
        encoding="utf-8",
    )

    return launcher


# ----------------------------------------------------------------------
# Unix launcher
# ----------------------------------------------------------------------

def create_unix_launcher(
    install_dir,
    installed_script,
):

    launcher = install_dir / APP_NAME

    python_exe = Path(
        sys.executable
    ).resolve()

    content = f"""#!/bin/sh
exec "{python_exe}" "{installed_script}" "$@"
"""

    launcher.write_text(
        content,
        encoding="utf-8",
    )

    mode = launcher.stat().st_mode

    launcher.chmod(
        mode
        | stat.S_IXUSR
        | stat.S_IXGRP
        | stat.S_IXOTH
    )

    return launcher


# ----------------------------------------------------------------------
# Install
# ----------------------------------------------------------------------

def install(system=False):

    print()
    print("=" * 70)
    print("ComfyUI Makepoint Installer")
    print("=" * 70)
    print()

    info(
        f"Operating system : {platform.system()}"
    )

    info(
        f"Python           : {sys.executable}"
    )

    info(
        f"Source directory : {SOURCE_DIR}"
    )

    info(
        f"Source script    : {SOURCE_SCRIPT}"
    )

    print()

    # --------------------------------------------------------------
    # Validate source
    # --------------------------------------------------------------

    if not SOURCE_SCRIPT.is_file():

        error(
            "makepoint.py was not found next to install.py."
        )

        print()
        print(
            "Expected structure:"
        )
        print()
        print(
            f"    {SOURCE_DIR}"
        )
        print(
            "    ├── install.py"
        )
        print(
            "    └── makepoint.py"
        )
        print()

        return 1

    # --------------------------------------------------------------
    # Install directory
    # --------------------------------------------------------------

    if system:

        install_dir = system_install_dir()

    else:

        install_dir = user_install_dir()

    info(
        f"Installation directory: {install_dir}"
    )

    try:

        install_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    except PermissionError:

        error(
            f"Permission denied: {install_dir}"
        )

        if system:

            if IS_WINDOWS:

                print(
                    "Run CMD/PowerShell as Administrator."
                )

            else:

                print(
                    "Run the installer with sudo."
                )

        return 1

    # --------------------------------------------------------------
    # Copy makepoint.py
    # --------------------------------------------------------------

    installed_script = (
        install_dir / SCRIPT_NAME
    )

    try:

        shutil.copy2(
            SOURCE_SCRIPT,
            installed_script,
        )

        success(
            f"Installed: {installed_script}"
        )

    except Exception as exc:

        error(
            f"Could not install makepoint.py: {exc}"
        )

        return 1

    # --------------------------------------------------------------
    # Create command
    # --------------------------------------------------------------

    try:

        if IS_WINDOWS:

            launcher = create_windows_launcher(
                install_dir,
                installed_script,
            )

        else:

            launcher = create_unix_launcher(
                install_dir,
                installed_script,
            )

        success(
            f"Installed command: {launcher}"
        )

    except Exception as exc:

        error(
            f"Could not create launcher: {exc}"
        )

        return 1

    # --------------------------------------------------------------
    # PATH
    # --------------------------------------------------------------

    if not path_contains(install_dir):

        warning(
            f"{install_dir} is not in PATH."
        )

        if not system:

            if IS_WINDOWS:

                add_windows_user_path(
                    install_dir
                )

            else:

                add_unix_user_path(
                    install_dir
                )

        else:

            warning(
                "Please add the installation directory "
                "to PATH manually if necessary."
            )

    else:

        success(
            "Installation directory is already in PATH."
        )

    # --------------------------------------------------------------
    # Done
    # --------------------------------------------------------------

    print()
    print("=" * 70)
    print("Installation completed successfully")
    print("=" * 70)
    print()

    print(
        "IMPORTANT: Open a NEW terminal before testing."
    )

    print()

    print(
        "Test:"
    )

    print(
        "    makepoint --info"
    )

    print()

    print(
        "Backup:"
    )

    print(
        "    makepoint --backup"
    )

    print()

    print(
        "List restore points:"
    )

    print(
        "    makepoint --list"
    )

    print()

    print(
        "Restore:"
    )

    print(
        "    makepoint --restore <path>"
    )

    print()

    return 0


# ----------------------------------------------------------------------
# Uninstall
# ----------------------------------------------------------------------

def uninstall(system=False):

    if system:

        install_dir = system_install_dir()

    else:

        install_dir = user_install_dir()

    print()
    print(
        f"Removing makepoint from: {install_dir}"
    )
    print()

    if not install_dir.exists():

        warning(
            "makepoint is not installed."
        )

        return 0

    try:

        shutil.rmtree(
            install_dir
        )

        success(
            "makepoint removed."
        )

    except PermissionError:

        error(
            "Permission denied."
        )

        if system:

            if IS_WINDOWS:
                print(
                    "Run as Administrator."
                )
            else:
                print(
                    "Run with sudo."
                )

        return 1

    return 0


# ----------------------------------------------------------------------
# Status
# ----------------------------------------------------------------------

def status(system=False):

    if system:

        install_dir = system_install_dir()

    else:

        install_dir = user_install_dir()

    script = (
        install_dir / SCRIPT_NAME
    )

    if IS_WINDOWS:

        launcher = (
            install_dir / "makepoint.cmd"
        )

    else:

        launcher = (
            install_dir / APP_NAME
        )

    print()
    print("=" * 70)
    print("Makepoint Status")
    print("=" * 70)
    print()

    print(
        f"OS              : {platform.system()}"
    )

    print(
        f"Python          : {sys.executable}"
    )

    print(
        f"Install dir     : {install_dir}"
    )

    print(
        f"makepoint.py    : "
        f"{'YES' if script.exists() else 'NO'}"
    )

    print(
        f"Command         : "
        f"{'YES' if launcher.exists() else 'NO'}"
    )

    print(
        f"In PATH         : "
        f"{'YES' if path_contains(install_dir) else 'NO'}"
    )

    print()

    return 0


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Install ComfyUI makepoint "
            "on Windows, Linux and macOS."
        )
    )

    parser.add_argument(
        "--install",
        action="store_true",
        help="Install makepoint.",
    )

    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Uninstall makepoint.",
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help="Show installation status.",
    )

    parser.add_argument(
        "--system",
        action="store_true",
        help="Install system-wide.",
    )

    parser.add_argument(
        "--user",
        action="store_true",
        help="Install for current user.",
    )

    args = parser.parse_args()

    if args.uninstall:

        return uninstall(
            system=args.system
        )

    if args.status:

        return status(
            system=args.system
        )

    # Default action = install
    return install(
        system=args.system
    )


if __name__ == "__main__":

    sys.exit(
        main()
    )
