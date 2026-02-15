"""
RPA Sandbox API Server

Provides HTTP endpoints for:
- Screenshot capture
- Status monitoring
- Task submission
- Chrome control

Runs inside the Docker container alongside the RPA agent.
"""

import os
import sys
import io
import base64
import asyncio
import subprocess
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add sandbox directory to path FIRST, then import modules directly
# This avoids loading the parent rpa_agent/__init__.py which has Windows-specific imports
sys.path.insert(0, '/app/rpa_agent/sandbox')
sys.path.insert(0, '/app')

from screen_linux import LinuxScreenCapture
from controller_linux import LinuxController


# Global state
class AppState:
    screen: Optional[LinuxScreenCapture] = None
    controller: Optional[LinuxController] = None
    current_task: Optional[str] = None
    task_running: bool = False
    task_result: Optional[str] = None
    chrome_pid: Optional[int] = None


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize resources on startup."""
    state.screen = LinuxScreenCapture()
    state.controller = LinuxController()
    print("RPA Sandbox API Server started")
    print(f"Screen size: {state.screen.screen_size}")
    yield
    print("RPA Sandbox API Server shutting down")


app = FastAPI(
    title="RPA Sandbox API",
    description="Control and monitor the RPA sandbox environment",
    version="1.0.0",
    lifespan=lifespan
)

# Allow CORS for web preview
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== Models ====================

class TaskRequest(BaseModel):
    task: str
    max_steps: int = 50
    dry_run: bool = False


class ClickRequest(BaseModel):
    x: int
    y: int
    button: str = "left"


class TypeRequest(BaseModel):
    text: str


class KeyRequest(BaseModel):
    keys: list[str]


# ==================== Screenshot Endpoints ====================

@app.get("/screenshot")
async def get_screenshot(
    scale: float = 1.0,
    format: str = "png",
    draw_cursor: bool = True
):
    """
    Get current screenshot.

    Args:
        scale: Scale factor (0.1 to 1.0).
        format: Image format ('png' or 'jpeg').
        draw_cursor: Whether to draw cursor indicator.

    Returns:
        PNG or JPEG image.
    """
    if state.screen is None:
        raise HTTPException(status_code=500, detail="Screen capture not initialized")

    scale = max(0.1, min(1.0, scale))

    if draw_cursor:
        img = state.screen.capture_with_cursor(scale=scale)
    else:
        img = state.screen.capture(scale=scale)

    buffer = io.BytesIO()
    if format.lower() == "jpeg":
        img.save(buffer, format="JPEG", quality=85)
        media_type = "image/jpeg"
    else:
        img.save(buffer, format="PNG")
        media_type = "image/png"

    buffer.seek(0)
    return Response(content=buffer.read(), media_type=media_type)


@app.get("/screenshot/base64")
async def get_screenshot_base64(scale: float = 1.0, draw_cursor: bool = True):
    """Get screenshot as base64 string."""
    if state.screen is None:
        raise HTTPException(status_code=500, detail="Screen capture not initialized")

    scale = max(0.1, min(1.0, scale))

    if draw_cursor:
        img = state.screen.capture_with_cursor(scale=scale)
    else:
        img = state.screen.capture(scale=scale)

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    b64 = base64.b64encode(buffer.read()).decode('utf-8')
    return {"image": b64, "format": "png", "width": img.width, "height": img.height}


# ==================== Status Endpoints ====================

@app.get("/status")
async def get_status():
    """Get current sandbox status."""
    cursor_pos = state.controller.get_cursor_position() if state.controller else (0, 0)
    screen_size = state.screen.screen_size if state.screen else (0, 0)

    return {
        "status": "running",
        "screen_size": {"width": screen_size[0], "height": screen_size[1]},
        "cursor_position": {"x": cursor_pos[0], "y": cursor_pos[1]},
        "chrome_running": state.chrome_pid is not None,
        "task_running": state.task_running,
        "current_task": state.current_task,
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# ==================== Chrome Control ====================

@app.post("/chrome/start")
async def start_chrome(url: str = "about:blank"):
    """
    Start Chrome browser.

    Args:
        url: Initial URL to open.
    """
    if state.chrome_pid is not None:
        return {"status": "already_running", "pid": state.chrome_pid}

    env = os.environ.copy()
    env['DISPLAY'] = ':99'

    # Start Chrome with sandbox-safe flags
    process = subprocess.Popen(
        [
            'google-chrome',
            '--no-sandbox',
            '--disable-gpu',
            '--disable-dev-shm-usage',
            '--window-size=1920,1040',  # Leave room for taskbar
            '--window-position=0,0',
            url
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    state.chrome_pid = process.pid

    # Wait for Chrome to start
    await asyncio.sleep(2)

    return {"status": "started", "pid": process.pid, "url": url}


@app.post("/chrome/stop")
async def stop_chrome():
    """Stop Chrome browser."""
    if state.chrome_pid is None:
        return {"status": "not_running"}

    try:
        subprocess.run(['kill', str(state.chrome_pid)], capture_output=True)
        state.chrome_pid = None
        return {"status": "stopped"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/chrome/navigate")
async def navigate_chrome(url: str):
    """Navigate Chrome to URL (opens in new tab if Chrome is running)."""
    env = os.environ.copy()
    env['DISPLAY'] = ':99'

    subprocess.Popen(
        ['google-chrome', '--no-sandbox', url],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    return {"status": "navigating", "url": url}


# ==================== Input Control ====================

@app.post("/mouse/move")
async def mouse_move(x: int, y: int, duration: float = 0.0):
    """Move mouse to position."""
    if state.controller is None:
        raise HTTPException(status_code=500, detail="Controller not initialized")

    state.controller.move_to(x, y, duration)
    return {"status": "moved", "x": x, "y": y}


@app.post("/mouse/click")
async def mouse_click(request: ClickRequest):
    """Click at position."""
    if state.controller is None:
        raise HTTPException(status_code=500, detail="Controller not initialized")

    state.controller.click(request.x, request.y, request.button)
    return {"status": "clicked", "x": request.x, "y": request.y, "button": request.button}


@app.post("/keyboard/type")
async def keyboard_type(request: TypeRequest):
    """Type text."""
    if state.controller is None:
        raise HTTPException(status_code=500, detail="Controller not initialized")

    state.controller.type_text(request.text)
    return {"status": "typed", "text": request.text}


@app.post("/keyboard/hotkey")
async def keyboard_hotkey(request: KeyRequest):
    """Press key combination."""
    if state.controller is None:
        raise HTTPException(status_code=500, detail="Controller not initialized")

    state.controller.hotkey(*request.keys)
    return {"status": "pressed", "keys": request.keys}


# ==================== Task Execution ====================

async def run_task_background(task: str, max_steps: int, dry_run: bool):
    """Run RPA task in background."""
    state.task_running = True
    state.current_task = task
    state.task_result = None

    try:
        env = os.environ.copy()
        env['DISPLAY'] = ':99'
        env['PYTHONPATH'] = '/app'

        cmd = [
            'python3', '-m', 'rpa_agent.cli',
            'run', task,
            '--max-steps', str(max_steps),
        ]
        if dry_run:
            cmd.append('--dry-run')

        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()
        state.task_result = stdout.decode() if stdout else stderr.decode()

    except Exception as e:
        state.task_result = f"Error: {str(e)}"

    finally:
        state.task_running = False
        state.current_task = None


@app.post("/task/run")
async def run_task(request: TaskRequest, background_tasks: BackgroundTasks):
    """
    Submit a task to run.

    Args:
        task: Task description.
        max_steps: Maximum steps to execute.
        dry_run: If true, don't execute actions.
    """
    if state.task_running:
        raise HTTPException(status_code=409, detail="A task is already running")

    background_tasks.add_task(
        run_task_background,
        request.task,
        request.max_steps,
        request.dry_run
    )

    return {"status": "started", "task": request.task}


@app.get("/task/status")
async def get_task_status():
    """Get current task status."""
    return {
        "running": state.task_running,
        "current_task": state.current_task,
        "result": state.task_result
    }


@app.post("/task/stop")
async def stop_task():
    """Stop current task (not fully implemented - requires task cancellation logic)."""
    # TODO: Implement proper task cancellation
    return {"status": "stop_requested"}


# ==================== Main ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
