---
name: ui-action
description: All UI automation actions - mouse, keyboard, scroll, drag
disable-model-invocation: true
allowed-tools: Bash
---

# UI Action Skill

Comprehensive UI automation.

## Usage
`/ui-action <action> [params]`

## Available Actions

### Mouse
```bash
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py move <x> <y>
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py click <x> <y>
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py click <x> <y> --right
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py click <x> <y> --double
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py drag <x1> <y1> <x2> <y2>
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py scroll <amount>  # positive=up
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py position  # get current position
```

### Keyboard
```bash
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py type "<text>"
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py type "<text>" --enter
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py key <keyname>
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py hotkey <key1> <key2> ...
```

### Keys
enter, tab, escape, backspace, delete, space, up, down, left, right, home, end, pageup, pagedown, f1-f12

### Hotkey Examples
- `hotkey ctrl c` - Copy
- `hotkey ctrl v` - Paste
- `hotkey ctrl a` - Select all
- `hotkey alt f4` - Close window
- `hotkey ctrl shift n` - New (varies by app)
