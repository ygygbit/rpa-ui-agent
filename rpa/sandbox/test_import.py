#!/usr/bin/env python3
"""Test importing sandbox modules."""
import sys
print("Python version:", sys.version)
print("Platform:", sys.platform)
print()

print("Adding sandbox to path...")
sys.path.insert(0, '/app/rpa_agent/sandbox')

print("Importing screen_linux...")
try:
    from screen_linux import LinuxScreenCapture
    print("  Success:", LinuxScreenCapture)
except Exception as e:
    print("  Error:", e)
    import traceback
    traceback.print_exc()

print()
print("Importing controller_linux...")
try:
    from controller_linux import LinuxController
    print("  Success:", LinuxController)
except Exception as e:
    print("  Error:", e)
    import traceback
    traceback.print_exc()

print()
print("Testing FastAPI import...")
try:
    from fastapi import FastAPI
    print("  Success:", FastAPI)
except Exception as e:
    print("  Error:", e)

print()
print("All imports complete!")
