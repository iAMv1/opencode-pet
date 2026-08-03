# Releases

This guide explains how to build and publish releases of OpenCode Pet.

## Automated Releases (Recommended)

Releases are built automatically using GitHub Actions when you push a new tag:

```bash
# 1. Update version in code/README if needed
# 2. Commit all changes
git add -A
git commit -m "chore: prepare for v0.6.1 release"

# 3. Create and push a tag
git tag -a v0.6.1 -m "Release v0.6.1: bug fixes and improvements"
git push origin v0.6.1
```

GitHub Actions will automatically:
1. Build `OpenCodePet.exe` using PyInstaller on Windows
2. Create a GitHub Release with the executable attached
3. Generate release notes from your commits

**That's it!** The executable will be available at:
https://github.com/iAMv1/opencode-pet/releases/tag/v0.6.1

## Manual Build (Local Development)

If you want to build the executable locally for testing:

### Prerequisites

- Windows 10/11
- Python 3.11 or 3.12
- Git

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/iAMv1/opencode-pet.git
cd opencode-pet

# 2. Install Python dependencies
pip install -r desktop/requirements.txt
pip install pyinstaller

# 3. Build the executable
cd desktop
build.bat

# 4. The executable will be at: desktop/dist/OpenCodePet.exe
```

### What Gets Built

The PyInstaller build (`desktop/build.bat`) creates a single standalone executable:
- **File**: `OpenCodePet.exe` (~50 MB)
- **Location**: `desktop/dist/OpenCodePet.exe`
- **Includes**: Python runtime, all dependencies, sprites, HTML files
- **No installation needed**: Just double-click to run

### Build Configuration

The build is configured in two places:
- `desktop/build.bat` - Simple build script for local development
- `OpenCodePet.spec` - PyInstaller specification file (used by CI/CD)

Both create a single-file executable with:
- Windowed mode (no console)
- Icon: `desktop/pet.ico`
- All data files bundled (sprites, HTML, Python files)

## Release Checklist

Before creating a release:

- [ ] All tests pass: `python tests/run_all.py`
- [ ] Version number updated in README.md (if applicable)
- [ ] CHANGELOG.md updated (if you have one)
- [ ] Code committed and pushed to main
- [ ] Tag created and pushed: `git tag -a vX.Y.Z && git push origin vX.Y.Z`
- [ ] GitHub Actions workflow completes successfully
- [ ] Release is published on GitHub
- [ ] Test the downloaded executable from the release

## File Structure for Releases

```
OpenCodePet-v0.6.0/
├── OpenCodePet.exe          # Main executable (~50 MB)
└── README.txt               # Quick start instructions (optional)
```

## Distribution

Users can download the executable from:
- **GitHub Releases**: https://github.com/iAMv1/opencode-pet/releases
- **Direct link**: https://github.com/iAMv1/opencode-pet/releases/latest/download/OpenCodePet.exe

## Troubleshooting

### Build fails with "module not found"
Make sure you've installed all dependencies:
```bash
pip install -r desktop/requirements.txt
pip install pyinstaller
```

### Executable is too large
The executable includes the Python runtime and all dependencies (~50 MB). This is normal for PyInstaller one-file mode. To reduce size:
- Use UPX compression (already enabled in `OpenCodePet.spec`)
- Exclude unused modules in the spec file
- Consider using a different bundler like Nuitka

### Antivirus flags the executable
This is common for PyInstaller executables. Solutions:
- Code sign the executable (requires certificate)
- Submit to antivirus vendors for whitelisting
- Provide a ZIP archive (sometimes helps)
- Document that it's a false positive

## GitHub Actions Workflow

The automated build is defined in `.github/workflows/release.yml`:

- **Trigger**: Push of a tag matching `v*` (e.g., `v0.6.0`)
- **Runs on**: Windows latest
- **Python versions**: 3.11 and 3.12 (builds both)
- **Artifacts**: Uploaded for 90 days
- **Release**: Created automatically with the executable attached

To modify the workflow, edit `.github/workflows/release.yml`.

## License Note

Bundled pixel art sources:
- petdex fan art (Pikachu/Charmander/Doraemon/Gardevoir/Giratina — personal use only, remove before distributing)
- **LPC Cat** by bluecarrot16 (CC-BY 3.0 / GPL, https://opengameart.org/content/lpc-cats-and-dogs). LPC sprites are shippable with attribution.

When distributing the executable, ensure you comply with these licenses.