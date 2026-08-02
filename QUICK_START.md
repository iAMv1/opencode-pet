# Quick Start Guide

## 🎉 Your Repository is Ready!

Repository: **https://github.com/iAMv1/opencode-pet**

## 📁 Project Structure

```
C:\Users\ItzP\projects\
├── opencode-pet\                          # Main repository (main branch)
│   ├── .git\
│   ├── desktop\                           # Desktop app source
│   ├── dist\                              # Distribution files
│   ├── BRANCHING_STRATEGY.md              # Detailed workflow guide
│   └── QUICK_START.md                     # This file
│
└── opencode-pet-worktrees\                # Worktrees for parallel development
    ├── desktop-app\                       # feature/desktop-app
    ├── plugin-system\                     # feature/plugin-system
    ├── sprite-animations\                 # feature/sprite-animations
    ├── tui-sidebar\                       # feature/tui-sidebar
    └── watcher\                           # feature/watcher-optimization
```

## 🚀 Getting Started

### 1. View Your Repository

```powershell
# Open in browser
start https://github.com/iAMv1/opencode-pet
```

### 2. Start Working on a Feature

```powershell
# Example: Work on desktop app features
cd C:\Users\ItzP\projects\opencode-pet-worktrees\desktop-app

# Make your changes, then commit
git add .
git commit -m "feat(desktop): add new feature"
git push origin feature/desktop-app
```

### 3. Create a Pull Request

```powershell
cd C:\Users\ItzP\projects\opencode-pet-worktrees\desktop-app
gh pr create --base develop --title "Feature: Desktop app improvements" --body "Description of changes"
```

## 🌿 Available Branches

| Branch | Purpose | Worktree Location |
|--------|---------|-------------------|
| `main` | Production-ready code | `C:\Users\ItzP\projects\opencode-pet` |
| `develop` | Integration branch | (use main worktree) |
| `feature/desktop-app` | Desktop UI/UX | `opencode-pet-worktrees\desktop-app` |
| `feature/plugin-system` | Plugin integration | `opencode-pet-worktrees\plugin-system` |
| `feature/sprite-animations` | Sprite & animation | `opencode-pet-worktrees\sprite-animations` |
| `feature/tui-sidebar` | TUI interface | `opencode-pet-worktrees\tui-sidebar` |
| `feature/watcher-optimization` | File watcher | `opencode-pet-worktrees\watcher` |

## 💡 Common Tasks

### Work on Multiple Features Simultaneously

```powershell
# Work on desktop app in one terminal
cd C:\Users\ItzP\projects\opencode-pet-worktrees\desktop-app

# Work on sprites in another terminal
cd C:\Users\ItzP\projects\opencode-pet-worktrees\sprite-animations
```

### Sync Your Worktree with Latest Develop

```powershell
cd C:\Users\ItzP\projects\opencode-pet-worktrees\desktop-app
git fetch origin
git rebase origin/develop
```

### Create New Feature Branch

```powershell
cd C:\Users\ItzP\projects\opencode-pet-worktrees\desktop-app
git checkout develop
git checkout -b feature/amazing-new-feature
git push -u origin feature/amazing-new-feature
```

### View All Worktrees

```powershell
cd C:\Users\ItzP\projects\opencode-pet
git worktree list
```

## 📖 Documentation

- **BRANCHING_STRATEGY.md** - Complete workflow guide with examples
- **README.md** - Project overview and development setup

## 🔧 Git Configuration

Your Git is configured with:
- **User**: Pratham
- **Email**: iam1nahata@gmail.com
- **Default Branch**: main

## ✅ Next Steps

1. ✅ Repository created and pushed to GitHub
2. ✅ Branching strategy implemented
3. ✅ Worktrees created for parallel development
4. ✅ Documentation added
5. **Now**: Start developing! Pick a worktree and start coding.

## 🆘 Need Help?

```powershell
# View all branches
git branch -a

# Check worktree status
git worktree list

# Get help on any command
git <command> --help
```

Happy coding! 🚀
