# Official Python on Debian (no devcontainer base = fewer build layers)
FROM python:3.12-bookworm

# Avoid prompts in apt
ENV DEBIAN_FRONTEND=noninteractive

# Install basic dev tools
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl sudo ca-certificates \
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
