"""
RPA Agent Sandbox Module

Provides sandboxed desktop environment for RPA automation with:
- Fixed 1080p resolution
- Chrome browser pre-installed
- VNC preview access
- Cross-platform screen/controller modules
"""

from .screen_linux import LinuxScreenCapture, get_screen_capture
from .controller_linux import LinuxController, get_controller

__all__ = [
    'LinuxScreenCapture',
    'LinuxController',
    'get_screen_capture',
    'get_controller',
]
