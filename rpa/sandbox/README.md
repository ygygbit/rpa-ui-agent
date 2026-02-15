# RPA Sandbox Environment

A Docker-based sandboxed desktop environment for running the RPA agent with:
- Fixed 1920x1080 resolution
- Chrome browser pre-installed
- VNC/noVNC preview access
- Fresh environment on every start

## Quick Start

```bash
# Start the sandbox
rpa-agent sandbox up

# Open preview in browser
rpa-agent sandbox preview

# Start Chrome with a URL
rpa-agent sandbox chrome https://www.google.com

# Run a task
rpa-agent sandbox run "Click the search button"

# Stop the sandbox
rpa-agent sandbox down
```

## Access Points

| Service | URL | Description |
|---------|-----|-------------|
| noVNC Web Preview | http://localhost:6080 | View/interact with desktop in browser |
| VNC | localhost:5900 | Classic VNC client access |
| API Server | http://localhost:8000 | REST API for control |
| Screenshot | http://localhost:8000/screenshot | Get current screenshot |

## CLI Commands

### `rpa-agent sandbox up`
Start the sandbox environment.

```bash
rpa-agent sandbox up           # Start in background
rpa-agent sandbox up --build   # Rebuild the container image
rpa-agent sandbox up --no-detach  # Run in foreground (see logs)
```

### `rpa-agent sandbox down`
Stop and remove the sandbox.

```bash
rpa-agent sandbox down         # Stop sandbox
rpa-agent sandbox down -v      # Also remove volumes
```

### `rpa-agent sandbox status`
Show current sandbox status.

### `rpa-agent sandbox preview`
Open noVNC preview in your default browser.

### `rpa-agent sandbox chrome [URL]`
Start Chrome in the sandbox with optional URL.

```bash
rpa-agent sandbox chrome
rpa-agent sandbox chrome https://example.com
```

### `rpa-agent sandbox screenshot`
Capture a screenshot from the sandbox.

```bash
rpa-agent sandbox screenshot                    # Save to sandbox_screenshot.png
rpa-agent sandbox screenshot -o myshot.png      # Custom output path
rpa-agent sandbox screenshot --open             # Open in browser
```

### `rpa-agent sandbox run <task>`
Run an RPA task in the sandbox.

```bash
rpa-agent sandbox run "Open Chrome and search for cats"
rpa-agent sandbox run "Click the submit button" --max-steps 10
rpa-agent sandbox run "Fill out the form" --dry-run
```

### `rpa-agent sandbox logs`
View container logs.

```bash
rpa-agent sandbox logs         # Show logs
rpa-agent sandbox logs -f      # Follow logs (live)
```

## API Endpoints

### Screenshots
- `GET /screenshot` - Get current screenshot (PNG/JPEG)
- `GET /screenshot/base64` - Get screenshot as base64

### Status
- `GET /status` - Get sandbox status
- `GET /health` - Health check

### Chrome Control
- `POST /chrome/start?url=<url>` - Start Chrome
- `POST /chrome/stop` - Stop Chrome
- `POST /chrome/navigate?url=<url>` - Navigate to URL

### Input Control
- `POST /mouse/move?x=<x>&y=<y>` - Move mouse
- `POST /mouse/click` - Click (body: `{x, y, button}`)
- `POST /keyboard/type` - Type text (body: `{text}`)
- `POST /keyboard/hotkey` - Press keys (body: `{keys: [...]}`)

### Task Execution
- `POST /task/run` - Run task (body: `{task, max_steps, dry_run}`)
- `GET /task/status` - Get task status
- `POST /task/stop` - Stop current task

## Development

The sandbox mounts your local `rpa_agent` directory as a volume, so code changes are reflected immediately without rebuilding.

```
docker-compose.yml
└── volumes:
    └── ./rpa_agent:/app/rpa_agent:ro  (your code - live)
```

To rebuild the container image (after changing Dockerfile):
```bash
rpa-agent sandbox up --build
```

## Architecture

```
┌─────────────────────────────────────────────┐
│  Docker Container                           │
│                                             │
│  ┌───────────────────────────────────────┐ │
│  │ Xvfb :99 (1920x1080 virtual display)  │ │
│  │ ┌───────────────────────────────────┐ │ │
│  │ │ Fluxbox (window manager)          │ │ │
│  │ │ ┌─────────────────────────────┐   │ │ │
│  │ │ │ Chrome / Apps               │   │ │ │
│  │ │ └─────────────────────────────┘   │ │ │
│  │ └───────────────────────────────────┘ │ │
│  └───────────────────────────────────────┘ │
│              │                              │
│  ┌───────────┴────────────┐                │
│  │ x11vnc → noVNC (6080)  │ ◀── Browser    │
│  └────────────────────────┘                │
│                                             │
│  ┌────────────────────────┐                │
│  │ API Server (8000)      │ ◀── CLI/REST   │
│  └────────────────────────┘                │
│                                             │
│  ┌────────────────────────┐                │
│  │ RPA Agent (Python)     │                │
│  └────────────────────────┘                │
└─────────────────────────────────────────────┘
```

## Troubleshooting

### Container won't start
```bash
# Check Docker is running
docker info

# Try rebuilding
rpa-agent sandbox up --build
```

### Can't connect to preview
```bash
# Check container status
rpa-agent sandbox status

# Check logs
rpa-agent sandbox logs
```

### VLM API not accessible
The container uses `host.docker.internal` to reach services on your host machine. Make sure your VLM API is accessible at `http://localhost:23333/api/anthropic`.
