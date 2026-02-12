---
name: screenshot
description: Capture a screenshot of the current screen
disable-model-invocation: true
allowed-tools: Bash, Read
---

# Screenshot Skill

Capture a screenshot of the current screen.

## Usage
`/screenshot [filename]` - Capture and save screenshot

## Command
Run this from the rpa directory:
```bash
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py screenshot -o <filename>
```

If no filename given, use `screenshot.png`.

After capturing, use the Read tool to view the image if needed for analysis.
