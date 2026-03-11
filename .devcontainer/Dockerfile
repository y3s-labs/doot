# Official Python on Debian (no devcontainer base = fewer build layers)
FROM python:3.12-bookworm

# Avoid prompts in apt
ENV DEBIAN_FRONTEND=noninteractive

# Install basic dev tools and Playwright browser deps (for browser agent)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git curl sudo ca-certificates \
        xvfb \
        libnspr4 libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
        libdbus-1-3 libxkbcommon0 libatspi2.0-0 libxcomposite1 libxdamage1 \
        libxfixes3 libxrandr2 libgbm1 libasound2 \
    && apt-get clean -y && rm -rf /var/lib/apt/lists/*

# Add non-root user for dev container (name expected by VS Code/Cursor)
ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID
RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
    && echo "$USERNAME ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME

USER $USERNAME
WORKDIR /workspace
