---
name: type-text
description: Type text using keyboard
disable-model-invocation: true
allowed-tools: Bash
---

# Type Text Skill

Type text into focused input.

## Usage
- `/type-text <text>` - Type text
- `/type-text <text> --enter` - Type and press Enter

## Command
```bash
# Type text
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py type "<text>"

# Type and press Enter
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py type "<text>" --enter
```

## Press Keys
```bash
# Single key
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py key enter
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py key tab
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py key escape

# Hotkey combo
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py hotkey ctrl c
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py hotkey ctrl v
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py hotkey alt f4
```
