---
name: click
description: Click the mouse at specific coordinates
disable-model-invocation: true
allowed-tools: Bash
---

# Click Skill

Click at screen coordinates.

## Usage
- `/click <x> <y>` - Left click
- `/click <x> <y> right` - Right click
- `/click <x> <y> double` - Double click

## Commands
```bash
# Left click
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py click <x> <y>

# Right click
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py click <x> <y> --right

# Double click
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py click <x> <y> --double
```
