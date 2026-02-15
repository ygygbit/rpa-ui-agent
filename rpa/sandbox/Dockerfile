# RPA Agent Sandbox Environment
# Ubuntu + Xvfb + VNC + noVNC + Chrome + Python
# Resolution: 1920x1080 (fixed)

FROM ubuntu:22.04

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
ENV RESOLUTION=1920x1080x24

# Install base dependencies
RUN apt-get update && apt-get install -y \
    # X11 and virtual framebuffer
    xvfb \
    x11vnc \
    # Lightweight window manager
    fluxbox \
    # VNC web client
    novnc \
    websockify \
    # Python
    python3.11 \
    python3.11-venv \
    python3-pip \
    python3-tk \
    python3-dev \
    # X11 utilities for automation
    xdotool \
    xclip \
    scrot \
    imagemagick \
    # Fonts (important for proper rendering)
    fonts-liberation \
    fonts-noto \
    fonts-noto-cjk \
    fonts-dejavu \
    # Other utilities
    curl \
    wget \
    gnupg \
    ca-certificates \
    supervisor \
    procps \
    # GUI file manager (optional, useful for testing)
    pcmanfm \
    # Terminal
    xterm \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Install Python dependencies for RPA agent
RUN pip3 install --no-cache-dir \
    pillow \
    pyautogui \
    pyscreenshot \
    python-xlib \
    mss \
    httpx \
    click \
    fastapi \
    uvicorn \
    websockets \
    rich \
    typer \
    anthropic

# Create startup scripts directory
RUN mkdir -p /app/scripts

# Copy supervisor config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Copy entrypoint script
COPY entrypoint.sh /app/scripts/entrypoint.sh
RUN chmod +x /app/scripts/entrypoint.sh

# Create fluxbox config for a clean desktop
RUN mkdir -p /root/.fluxbox
COPY fluxbox-init /root/.fluxbox/init
COPY fluxbox-menu /root/.fluxbox/menu

# Expose ports
# 5900 - VNC
# 6080 - noVNC web interface
# 8000 - API server
EXPOSE 5900 6080 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:6080/ || exit 1

# Start via supervisor
CMD ["/app/scripts/entrypoint.sh"]
