# Release Package Contents

When you create a release, GitHub Actions automatically builds and packages the application.

## What Gets Downloaded

Users will see **2 files** in the release:

### 1. `OpenCodePet.exe` (Standalone Executable)
- **Size**: ~50 MB
- **What it is**: The complete desktop application in a single file
- **How to use**: Just double-click it - no installation needed!
- **Best for**: Users who just want the app

### 2. `OpenCodePet-v0.6.1-windows.zip` (Recommended Download)
- **Size**: ~50 MB (same exe + ~10 KB docs)
- **What it is**: ZIP package containing:
  ```
  OpenCodePet-v0.6.1-windows/
  ├── OpenCodePet.exe      # The application
  ├── README.txt           # Quick start guide
  ├── RELEASES.txt         # Release notes
  └── LICENSE.txt          # MIT License
  ```
- **How to use**: 
  1. Download and extract the ZIP
  2. Double-click `OpenCodePet.exe`
  3. Read README.txt for instructions
- **Best for**: All users (recommended)

## Which Should Users Download?

**Recommend the ZIP package** because it includes:
- Quick start instructions
- License information
- Release notes

## Example Release Page

When you visit https://github.com/iAMv1/opencode-pet/releases/tag/v0.6.1, users will see:

```
## OpenCode Pet v0.6.1

### Desktop Application

**Download `OpenCodePet-v0.6.1-windows.zip` below** - no installation required!

#### Installation
1. Download the ZIP file
2. Extract it
3. Double-click OpenCodePet.exe

#### What's Changed
- Bug fixes
- Performance improvements
- etc.

---
**Built with**: PyInstaller + Python 3.11/3.12

### Assets
- [OpenCodePet.exe](link) - Standalone executable
- [OpenCodePet-v0.6.1-windows.zip](link) - **Recommended** - ZIP package with docs
```

## Creating a Release

To create a new release with these packages:

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
1. Build the EXE (~5 minutes)
2. Create the ZIP package
3. Create the GitHub Release
4. Attach both files

## Direct Download Links

You can share these direct links:

**Latest version (always points to newest):**
```
https://github.com/iAMv1/opencode-pet/releases/latest/download/OpenCodePet-v0.6.1-windows.zip
```

**Specific version:**
```
https://github.com/iAMv1/opencode-pet/releases/download/v0.6.1/OpenCodePet-v0.6.1-windows.zip
```

## Current Status

✅ **v0.6.0 tag exists** - ready to build
✅ **GitHub Actions workflow configured** - will build both EXE and ZIP
✅ **LICENSE file created** - MIT License
✅ **Documentation ready** - README.txt, RELEASES.txt, LICENSE.txt

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
   https://github.com/iAMv1/opencode-pet/releases/latest/download/OpenCodePet-v0.6.0-windows.zip
   ```

## Package Comparison

| Feature | EXE Only | ZIP Package (Recommended) |
|---------|----------|---------------------------|
| Size | ~50 MB | ~50 MB |
| Installation | None | Extract and run |
| Documentation | ❌ No | ✅ Yes (README.txt) |
| License | ❌ No | ✅ Yes (LICENSE.txt) |
| Release Notes | GitHub only | ✅ Included (RELEASES.txt) |
| User Experience | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

## Files in This Release

```
Release v0.6.0/
├── OpenCodePet.exe                          # Standalone executable
└── OpenCodePet-v0.6.0-windows.zip           # Complete package
    └── OpenCodePet-v0.6.0-windows/
        ├── OpenCodePet.exe                  # The application
        ├── README.txt                       # Quick start guide
        ├── RELEASES.txt                     # Release notes
        └── LICENSE.txt                      # MIT License
```

---

**Current release**: https://github.com/iAMv1/opencode-pet/releases/tag/v0.6.0

**Ready to build**: Yes! Just push the tag.