# 🐾 OpenCode Pet

```
██████╗ ██████╗ ███████╗████████╗██████╗  ██████╗ ███████╗
██╔══██╗██╔══██╗██╔════╝╚══██╔══╝██╔══██╗██╔════╝██╔════╝
██████╔╝██████╔╝███████╗   ██║   ██████╔╝█████╗  ███████╗
██╔══██╗██╔═══╝ █══════╝   ██║   ██╔═══╝ ██╔══╝  ╚════██║
██████╔╝██║     ███████╗   ██║   ██║     ███████╗███████║
╚═════╝ ╚═╝     ╚══════╝   ╚═╝   ╚═╝     ╚══════╝╚══════╝
```

**Your pixel-perfect desktop companion for OpenCode**

[![Windows](https://img.shields.io/badge/Windows-10%2F11-0078D6?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/iAMv1/opencode-pet/releases/latest)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Release](https://img.shields.io/badge/Release-v0.6.0-brightgreen?style=for-the-badge)](https://github.com/iAMv1/opencode-pet/releases/tag/v0.6.0)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║   ██████╗ ██████╗ ███████╗████████╗██████╗  ██████╗ ███████╗              ║
║   ██╔══██╗██╔══██╗██╔════╝╚══██╔══╝██╔══██╗██╔════╝██╔════╝              ║
║   ██████╔╝██████╔╝███████╗   ██║   ██████╔╝█████╗  ███████╗              ║
║   ██╔══██╗██╔═══╝ █══════╝   ██║   ██╔═══╝ ██╔══╝  ╚════██║              ║
║   ██████╔╝██║     ███████╗   ██║   ██║     ███████╗███████║              ║
║   ╚═════╝ ╚═╝     ╚══════╝   ╚═╝   ╚═╝     ╚══════╝╚══════╝              ║
║                                                                              ║
║   ██╗   ██╗███████╗████████╗██████╗  ██████╗ ███████╗                    ║
║   ██║   ██║██╔════╝╚══██╔══╝██╔══██╗██╔════╝██╔════╝                    ║
║   ██║   ██║███████╗   ██║   ██████╔╝█████╗  ███████╗                    ║
║   ╚██╗ ██╔╝╚════██║   ██║   ██╔═══╝ ██╔══╝  ╚════██║                    ║
║    ╚████╔╝ ███████║   ██║   ██║     ███████╗███████║                    ║
║     ╚═══╝  ╚══════╝   ╚═╝   ╚═╝     ╚══════╝╚══════╝                    ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## 🎮 Features

### 🎨 Pixel Art Pets
Real sprite-sheet frame animation with 6 characters.

### ⚡ Event-Driven Updates
No polling overhead. Instant status changes with 3-second safety net.

### 🖱️ Interactive Controls
Click to jump, double-click to wave, hover for controls, drag to move.

### 🎯 Focus Sessions
Grow your pet through focused work - earn XP, level up, track streaks.

### 🪟 Transparent Window
Zero background, just the pet floating over your desktop at 30 FPS.

### 🌐 Works With ANY App
Not just OpenCode! Monitors any app on your system.

---

## 🚀 Installation

### Download Pre-built Executable (Recommended)

**No installation needed - just download and run!**

[![Download Latest](https://img.shields.io/badge/Download-OpenCodePet.exe-blue?style=for-the-badge&logo=windows&logoColor=white&labelColor=0078D6)](https://github.com/iAMv1/opencode-pet/releases/latest/download/OpenCodePet.exe)

**Direct download:** https://github.com/iAMv1/opencode-pet/releases/latest/download/OpenCodePet.exe

**File size:** ~50 MB | **Requirements:** Windows 10/11

### Alternative: Run from Source

```bash
git clone https://github.com/iAMv1/opencode-pet.git
cd opencode-pet
pip install -r desktop/requirements.txt
python desktop/main.py
```

---

## 🏗️ How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                    OpenCode Pet Architecture                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────┐ │
│  │ OpenCode     │──────▶│ Status Files │──────▶│  Pet     │ │
│  │ Sessions     │      │ (JSON)       │      │  Engine  │ │
│  └──────────────┘      └──────────────┘      └────┬─────┘ │
│         ▲                                            │      │
│         │                                            ▼      │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────┐ │
│  │ OS Activity  │──────▶│  Physics +   │◀─────│  GDI     │ │
│  │ (Any App)    │      │  Animation   │      │  Window  │ │
│  └──────────────┘      └──────────────┘      └──────────┘ │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎯 Pet States

The pet reacts to your activity in real-time:

| State | Trigger | Animation |
|-------|---------|----------|
| 💤 Idle | No activity | Calm breathing |
| 🏃 Running | Typing/working | Run animation |
| 🤔 Thinking | Processing | Review pose |
| ✅ Success | Task complete | Jump celebration |
| ❌ Failed | Error occurred | Sad pose |
| 🎉 Celebrate | Focus complete | Wave + jump |
| 😢 Wilt | Left during focus | Sad droop |

---

## 🛠️ Development

```bash
npm install
pip install -r desktop/requirements.txt
python desktop/main.py
# rebuild the exe:
desktop\build.bat
```

## 🧪 Testing

```bash
python tests/run_all.py
```

- 187 Python tests
- 67 UI checks
- 59 backend checks
- 21 validation tests

---

## 📝 License

MIT License. See LICENSE for details.

---

**Built with ❤️ by [iAMv1](https://github.com/iAMv1)**

⭐ Star this repo if you love having a pet while you code!
