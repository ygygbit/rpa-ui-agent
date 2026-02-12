---
name: analyze-screen
description: Capture screenshot and analyze with vision model to describe screen or find elements
disable-model-invocation: true
allowed-tools: Bash, Read
---

# Analyze Screen Skill

Use vision model to understand what's on screen.

## Usage
- `/analyze-screen` - Describe current screen
- `/analyze-screen find <element>` - Find element coordinates

## Commands

### Describe Screen
```bash
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py analyze
```

### Custom Analysis
```bash
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py analyze -p "Your question about the screen"
```

### Find Element (returns coordinates)
```bash
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py find "element description"
```

Returns JSON: `{"found": true, "x": 100, "y": 200, "element": "..."}`

## Workflow Example

1. Find the element:
```bash
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py find "Submit button"
```

2. Click the returned coordinates:
```bash
cd C:\Users\guangyang\Documents\rpa && uv run python ui_helper.py click 100 200
```
