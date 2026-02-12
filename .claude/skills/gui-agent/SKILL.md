---
name: gui-agent
description: Autonomous GUI agent - observes screen, plans, and executes UI actions to complete tasks
disable-model-invocation: true
allowed-tools: Bash, Read
---

# GUI Agent Skill

Autonomous agent for complex GUI tasks.

## Usage
`/gui-agent <task description>`

## Examples
- `/gui-agent open notepad and type hello world`
- `/gui-agent open paint and draw a rectangle`
- `/gui-agent search for weather in the start menu`

## Execution Process

For the given task, follow this loop:

### 1. Observe - See what's on screen
```bash
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py analyze -p "Task: <TASK>. What action should I take? Options: click at (x,y), type text, press key, scroll, or done if complete."
```

### 2. Act - Execute the suggested action

Based on the vision model response, use the appropriate command:

```bash
# Click
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py click <x> <y>

# Type
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py type "<text>"

# Key
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py key <keyname>

# Hotkey (e.g., Win key to open start)
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py hotkey ctrl escape

# Drag
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py drag <x1> <y1> <x2> <y2>
```

### 3. Wait - Let UI update
Wait ~500ms between actions.

### 4. Repeat until done

Continue observing and acting until:
- Task appears complete
- Maximum 15 steps reached
- User interrupts

## Quick Commands

### Open Start Menu
```bash
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py hotkey ctrl escape
```

### Open Run Dialog
```bash
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py hotkey win r
```
Note: For Win+R, you may need to click Start then type the app name instead.

### Type and Enter
```bash
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py type "notepad" --enter
```
