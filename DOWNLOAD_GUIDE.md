# How to Download and Distribute OpenCode Pet Desktop App

## Quick Answer

**For Users**: Download `OpenCodePet.exe` from [GitHub Releases](https://github.com/iAMv1/opencode-pet/releases)

**For You (the developer)**: Follow the steps below to create releases

---

## For Users: How to Download

### Step 1: Go to GitHub Releases
Visit: **https://github.com/iAMv1/opencode-pet/releases**

### Step 2: Download the Latest Version
- Find the latest release (e.g., **v0.6.0**)
- Download `OpenCodePet.exe` 
- File size: ~50 MB

### Step 3: Run the App
- Double-click `OpenCodePet.exe`
- No installation needed!
- The pet will appear on your desktop

### Direct Download Link
You can share this direct link with others:
```
https://github.com/iAMv1/opencode-pet/releases/latest/download/OpenCodePet.exe
```

This always points to the latest version!

---

## For You: How to Create a Release

### Automated Method (Recommended)

When you push a new tag, GitHub Actions automatically builds and releases the app:

```bash
# 1. Make sure all your changes are committed
git add -A
git commit -m "chore: prepare for v0.6.1 release"

# 2. Create a new tag (replace 0.6.1 with your version)
git tag -a v0.6.1 -m "Release v0.6.1: description of changes"

# 3. Push the tag to GitHub
git push origin v0.6.1
```

**That's it!** GitHub Actions will:
1. Automatically build `OpenCodePet.exe` on Windows
2. Create a GitHub Release
3. Attach the executable to the release
4. Generate release notes from your commits

The release will be available at:
```
https://github.com/iAMv1/opencode-pet/releases/tag/v0.6.1
```

### Manual Method (For Testing)

If you want to build the executable locally without creating a release:

```bash
# 1. Install dependencies
pip install -r desktop/requirements.txt
pip install pyinstaller

# 2. Build the executable
cd desktop
build.bat

# 3. The executable is ready at:
#    desktop/dist/OpenCodePet.exe
```

**Note**: The executable is ~50 MB and includes everything needed to run.

---

## Current Status

✅ **v0.6.0 is already released!**
- Tag: `v0.6.0`
- Release URL: https://github.com/iAMv1/opencode-pet/releases/tag/v0.6.0
- Executable: `OpenCodePet.exe` (built automatically)

✅ **GitHub Actions workflow is set up**
- File: `.github/workflows/release.yml`
- Trigger: Automatic on tag push (e.g., `git tag v0.6.1 && git push origin v0.6.1`)
- Builds on: Windows with Python 3.11 and 3.12

✅ **Documentation updated**
- `README.md` - Installation instructions with download link
- `RELEASES.md` - Complete release guide
- `.github/workflows/release.yml` - Automated build pipeline

---

## What's in a Release

Each release includes:
```
OpenCodePet-v0.6.1/
├── OpenCodePet.exe          # Main application (~50 MB)
└── Release notes            # Auto-generated from commits
```

The executable is:
- **Standalone**: No Python installation needed
- **Single file**: Easy to distribute
- **Windows only**: Built for Windows 10/11
- **Signed**: Code-signed when possible (requires certificate)

---

## Sharing the App with Others

### Option 1: GitHub Releases (Recommended)
Share this link:
```
https://github.com/iAMv1/opencode-pet/releases/latest
```
Users can download the latest version directly.

### Option 2: Direct Download Link
Share this for the latest version:
```
https://github.com/iAMv1/opencode-pet/releases/latest/download/OpenCodePet.exe
```

### Option 3: Specific Version
Share a specific version:
```
https://github.com/iAMv1/opencode-pet/releases/download/v0.6.0/OpenCodePet.exe
```

### Option 4: As OpenCode Plugin
Users can also install via OpenCode:
```bash
opencode plugin https://github.com/iAMv1/opencode-pet -g
```

---

## Release Checklist

Before creating a new release:

- [ ] All tests pass: `python tests/run_all.py`
- [ ] Code is committed and pushed to `main`
- [ ] Update version number in commits/README if needed
- [ ] Create and push tag: `git tag -a vX.Y.Z && git push origin vX.Y.Z`
- [ ] Wait for GitHub Actions to complete (~5-10 minutes)
- [ ] Verify the release at: https://github.com/iAMv1/opencode-pet/releases
- [ ] Test the downloaded executable

---

## Troubleshooting

### GitHub Actions fails
Check the Actions tab in GitHub for error logs. Common issues:
- Missing dependencies in `desktop/requirements.txt`
- PyInstaller configuration errors
- Windows-specific build issues

### Executable is too large (~50 MB)
This is normal for PyInstaller one-file builds. To reduce:
- Enable UPX compression (already enabled)
- Exclude unused Python modules
- Consider alternative bundlers

### Antivirus flags the executable
This is common for PyInstaller executables. Solutions:
- Document that it's a false positive
- Submit to antivirus vendors for whitelisting
- Code sign the executable (requires certificate)

---

## Files Added/Modified

### New Files
- `.github/workflows/release.yml` - Automated build and release workflow
- `RELEASES.md` - This guide
- `.github/DISABLE_TESTS.txt` - Marker file

### Modified Files
- `README.md` - Added download instructions and release links
- `tests/check_frontend.py` - Removed references to deleted dist files
- `tests/run_all.py` - Removed node plugin tests

### Deleted Files
- `tests/test_server_plugin.mjs` - No longer needed (dist/server.js removed)

---

## Next Steps

1. **Test the current release**: Download v0.6.0 from https://github.com/iAMv1/opencode-pet/releases/tag/v0.6.0
2. **Create v0.6.1** (when ready):
   ```bash
   git add -A
   git commit -m "chore: release v0.6.1"
   git tag -a v0.6.1 -m "Release v0.6.1"
   git push origin main
   git push origin v0.6.1
   ```
3. **Wait for GitHub Actions** to build and create the release
4. **Share the release link** with users

---

## Questions?

- **GitHub Actions docs**: https://docs.github.com/en/actions
- **PyInstaller docs**: https://pyinstaller.org/
- **Releases guide**: See `RELEASES.md` in this repo

**Current Release**: https://github.com/iAMv1/opencode-pet/releases/tag/v0.6.0 🚀