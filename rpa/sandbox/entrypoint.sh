#!/bin/bash
set -e

# Create log directory
mkdir -p /var/log/supervisor

# Set up environment
export DISPLAY=:99
export RESOLUTION=${RESOLUTION:-1920x1080x24}

echo "=========================================="
echo "  RPA Agent Sandbox Environment"
echo "=========================================="
echo "Resolution: $RESOLUTION"
echo "VNC Port: 5900"
echo "noVNC Web UI: http://localhost:6080"
echo "API Server: http://localhost:8000"
echo "=========================================="

# Start supervisor (manages all services)
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
