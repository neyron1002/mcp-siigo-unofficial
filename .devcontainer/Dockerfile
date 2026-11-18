# Development image for MCP Siigo Unofficial.
# Ubuntu 22.04 matches the Linux release target (glibc baseline for the portable build).
FROM mcr.microsoft.com/devcontainers/base:ubuntu-22.04

# uv: Python and dependency manager (pinned).
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /uvx /usr/local/bin/

# Runtime libraries for PySide6 widgets (xcb/EGL/xkb/D-Bus), a virtual screen for
# headless UI tests, a Secret Service keyring for vault tests, and binutils for
# PyInstaller --strip.
RUN apt-get update \
    && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install -y --no-install-recommends \
        binutils xz-utils zstd \
        libgl1 libegl1 libfontconfig1 libfreetype6 libglib2.0-0 libdbus-1-3 \
        libxkbcommon0 libxkbcommon-x11-0 \
        libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
        libxcb-render-util0 libxcb-shape0 libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1 \
        xvfb xauth dbus-x11 gnome-keyring libsecret-1-0 \
    && rm -rf /var/lib/apt/lists/*

# Python 3.12 managed by uv, shared by every user of the image.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_PYTHON=3.12 \
    UV_LINK_MODE=copy
RUN uv python install 3.12 && chmod -R a+rX /opt/uv-python

USER vscode
# Claude Code CLI (native installer). The owner signs in inside the container;
# no host credentials are mounted.
RUN curl -fsSL https://claude.ai/install.sh | bash
ENV PATH="/home/vscode/.local/bin:${PATH}"
