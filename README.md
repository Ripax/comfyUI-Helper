# comfyUI-Helper

Create a ComfyUI restore point with:

```powershell
python makepoint.py --backup
```

To also push it to [Ripax/restore_points](https://github.com/Ripax/restore_points):

```powershell
python makepoint.py --backup --github
```

Restore directly from a commit that added a backup to the GitHub repository:

```powershell
python makepoint.py --restore 0123456789abcdef0123456789abcdef01234567
```

Commit-based restore downloads the matching restore point to a temporary
directory, then follows the same confirmation and restore process as a local
backup path. By default, it restores the ComfyUI revision, custom nodes, and
Python packages.

List local backups from the default `restore_points` folder and GitHub backups
with their dates. Local entries include their restore path; GitHub entries
include their commit IDs. The list is displayed in separate boxed tables:

```powershell
python makepoint.py --restore list
```

Use a listed commit ID with `--restore` to restore that backup.

Test backup generation and remove the temporary files afterward:

```powershell
python makepoint.py --backup --dry-run
```

Test GitHub connectivity and push access without publishing:

```powershell
python makepoint.py --backup --github --dry-run
```

The GitHub repository is public. A restore point can contain your computer name,
local installation paths, installed package and custom-node metadata, and a
ComfyUI Git diff. Review the generated backup before publishing it. Pushing
requires Git and GitHub credentials configured for the repository. `--dry-run`
uses temporary files and does not change the remote; any temporary local Git
commit is removed afterward.