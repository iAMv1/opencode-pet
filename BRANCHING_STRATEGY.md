# Branching Strategy & Workflow

## Repository Structure

This repository follows a **Git Flow** inspired branching model with worktrees for parallel development.

## Branch Organization

### Main Branches

- **`main`** - Production-ready code, always deployable
- **`develop`** - Integration branch for features, next release base

### Feature Branches

Created from `develop`, merged back via Pull Requests:

- **`feature/desktop-app`** - Desktop application enhancements (pywebview, GDI, UI)
- **`feature/plugin-system`** - OpenCode plugin system and integration
- **`feature/sprite-animations`** - Sprite sheets, animations, pet rendering
- **`feature/tui-sidebar`** - TUI sidebar and terminal integration
- **`feature/watcher-optimization`** - File watcher and event system improvements

### Support Branches

- **`hotfix/*`** - Urgent production fixes (branched from `main`)
- **`release/*`** - Release preparation (branched from `develop`)

## Worktree Setup

Worktrees enable working on multiple branches simultaneously without switching:

```
C:\Users\ItzP\projects\
├── opencode-pet\                  # Main repo (main branch)
└── opencode-pet-worktrees\
    ├── desktop-app\               # feature/desktop-app
    ├── plugin-system\             # feature/plugin-system
    ├── sprite-animations\         # feature/sprite-animations
    ├── tui-sidebar\               # feature/tui-sidebar
    └── watcher\                   # feature/watcher-optimization
```

## Development Workflow

### 1. Starting New Feature Work

```powershell
# Navigate to appropriate worktree
cd C:\Users\ItzP\projects\opencode-pet-worktrees\desktop-app

# Create feature branch from develop
git checkout develop
git checkout -b feature/new-desktop-feature
git push -u origin feature/new-desktop-feature
```

### 2. Daily Development

```powershell
# Work in your worktree
cd C:\Users\ItzP\projects\opencode-pet-worktrees\desktop-app

# Make changes, commit frequently
git add .
git commit -m "feat: add new desktop feature"

# Push to remote
git push origin feature/desktop-app
```

### 3. Creating Pull Request

```powershell
# Via GitHub CLI
cd C:\Users\ItzP\projects\opencode-pet-worktrees\desktop-app
gh pr create --base develop --title "Feature: New desktop feature" --body "Description..."
```

### 4. Merging Features

```powershell
# After PR approval, merge to develop
cd C:\Users\ItzP\projects\opencode-pet-worktrees\desktop-app
git checkout develop
git merge feature/desktop-app
git push origin develop

# Clean up feature branch
git branch -d feature/desktop-app
git push origin --delete feature/desktop-app
```

### 5. Release to Production

```powershell
# Create release branch from develop
cd C:\Users\ItzP\projects\opencode-pet
git checkout develop
git checkout -b release/v1.0.0
git push -u origin release/v1.0.0

# After testing, merge to main
git checkout main
git merge release/v1.0.0
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin main --tags

# Also merge back to develop
git checkout develop
git merge release/v1.0.0
git push origin develop
```

## Branch Naming Convention

- **Features**: `feature/<short-description>` (e.g., `feature/desktop-app`)
- **Bugfixes**: `bugfix/<issue-number>-<description>` (e.g., `bugfix/42-watcher-crash`)
- **Hotfixes**: `hotfix/<issue-number>-<description>` (e.g., `hotfix/42-critical-fix`)
- **Releases**: `release/<version>` (e.g., `release/v1.0.0`)

## Commit Message Convention

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `perf`: Performance improvements
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

### Examples

```
feat(desktop): add pet animation speed control
fix(watcher): resolve file handle leak on session end
docs(readme): update installation instructions
perf(sprites): optimize sprite sheet loading
```

## Managing Worktrees

### List all worktrees

```powershell
cd C:\Users\ItzP\projects\opencode-pet
git worktree list
```

### Remove worktree

```powershell
cd C:\Users\ItzP\projects\opencode-pet
git worktree remove C:\Users\ItzP\projects\opencode-pet-worktrees\desktop-app
```

### Prune stale worktrees

```powershell
cd C:\Users\ItzP\projects\opencode-pet
git worktree prune
```

## Best Practices

1. **One feature per branch** - Keep branches focused and small
2. **Pull frequently** - Sync with `develop` daily to avoid merge conflicts
3. **Commit often** - Small, atomic commits are easier to review and revert
4. **Write descriptive messages** - Future you will thank present you
5. **Test before merging** - Don't break `develop` or `main`
6. **Delete merged branches** - Keep the repo clean
7. **Use worktrees** - Parallel development without constant branch switching

## Quick Reference

| Task | Command |
|------|---------|
| List branches | `git branch -a` |
| Switch branch | `git checkout <branch>` |
| Create branch | `git checkout -b <branch>` |
| Delete branch | `git branch -d <branch>` |
| Push branch | `git push -u origin <branch>` |
| Pull latest | `git pull origin <branch>` |
| Create PR | `gh pr create --base develop` |
| List worktrees | `git worktree list` |
