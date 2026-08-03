# Release Package Contents

When you create a release, GitHub Actions automatically builds the application.

## What Gets Downloaded

Users will see **1 file** in the release:

### `OpenCodePet.exe` (Standalone Executable)
- **Size**: ~50 MB
- **What it is**: The complete desktop application in a single file
- **How to use**: Just double-click it - no installation needed!
- **Best for**: All users

## Example Release Page

When you visit https://github.com/iAMv1/opencode-pet/releases/tag/v0.6.1, users will see:

```
## OpenCode Pet v0.6.1

### Desktop Application

**Download `OpenCodePet.exe` below** - no installation required, just run it!

#### Requirements
- Windows 10/11

#### Installation
1. Download `OpenCodePet.exe`
2. Double-click to run
3. The pet will appear on your desktop

#### What's Changed
- Bug fixes
- Performance improvements
- etc.

---
**Built with**: PyInstaller + Python 3.11/3.12

### Assets
- [OpenCodePet.exe](link) - Standalone executable
```

## Creating a Release

To create a new release:

```bash
# 1. Make sure all changes are committed
git add -A
git commit -m "chore: release v0.6.1"

# 2. Create and push tag
git tag -a v0.6.1 -m "Release v0.6.1: bug fixes and improvements"
git push origin main
git push origin v0.6.1
```

GitHub Actions will automatically:
1. Build `OpenCodePet.exe` on Windows
2. Create a GitHub Release
3. Attach the executable
4. Generate release notes

## Direct Download Links

You can share this direct link with others:

**Latest version (always points to newest):**
```
https://github.com/iAMv1/opencode-pet/releases/latest/download/OpenCodePet.exe
```

**Specific version:**
```
https://github.com/iAMv1/opencode-pet/releases/download/v0.6.1/OpenCodePet.exe
```

## Current Status

✅ **v0.6.0 tag exists** - ready to build
✅ **GitHub Actions workflow configured** - will build and release the EXE
✅ **LICENSE file created** - MIT License

## Next Steps

1. **Push the v0.6.0 tag** to trigger the first build:
   ```bash
   git tag -a v0.6.0 -f -m "Release v0.6.0: production-ready desktop app"
   git push origin v0.6.0 --force
   ```

2. **Wait ~5 minutes** for GitHub Actions to complete

3. **Check the release**: https://github.com/iAMv1/opencode-pet/releases/tag/v0.6.0

4. **Share the download link**:
   ```
   https://github.com/iAMv1/opencode-pet/releases/latest/download/OpenCodePet.exe
   ```

## Files in This Release

```
Release v0.6.0/
└── OpenCodePet.exe    # Standalone executable (~50 MB)
```

---

**Current release**: https://github.com/iAMv1/opencode-pet/releases/tag/v0.6.0

**Ready to build**: Yes! Just push the tag.