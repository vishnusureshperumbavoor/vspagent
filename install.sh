#!/usr/bin/env bash
# vspagent installer for Linux and macOS.
#
#   curl -fsSL https://github.com/vishnusureshperumbavoor/vspagent/releases/latest/download/install.sh | sh
#
# Environment:
#   VSPAGENT_VERSION   pinned version (default: 4.0.0), or "latest"
#   VSPAGENT_REPO      GitHub repo used for uv's bootstrap message
#   VSPAGENT_BIN_DIR   optional install directory hint
set -euo pipefail

REPO="${VSPAGENT_REPO:-vishnusureshperumbavoor/vspagent}"
VERSION="${VSPAGENT_VERSION:-4.0.0}"
BIN_DIR="${VSPAGENT_BIN_DIR:-$HOME/.local/bin}"

usage() {
    cat <<'EOF'
Usage: install.sh [--uninstall]

Installs the vspagent coding agent with uv, without root privileges.
Set VSPAGENT_VERSION to pin a release, e.g. VSPAGENT_VERSION=4.0.0.
EOF
}

uninstall() {
    if command -v uv >/dev/null 2>&1; then
        uv tool uninstall vspagent || true
        echo "Removed the vspagent uv tool."
    else
        echo "uv is not installed; nothing to uninstall." >&2
    fi
}

if [ "${1:-}" = "--uninstall" ]; then
    uninstall
    exit 0
fi
if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    usage
    exit 0
fi

case "$(uname -s)" in
    Linux|Darwin) ;;
    *)
        echo "vspagent currently supports Linux and macOS only." >&2
        exit 1
        ;;
esac

if ! command -v uv >/dev/null 2>&1; then
    echo "uv not found; installing it from https://astral.sh/uv ..."
    if ! command -v curl >/dev/null 2>&1; then
        echo "curl is required to bootstrap uv." >&2
        exit 1
    fi
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

if [ "$VERSION" = "latest" ]; then
    PACKAGE="vspagent"
else
    PACKAGE="vspagent==${VERSION}"
fi

echo "Installing ${PACKAGE} from PyPI with uv ..."
uv tool install --force "$PACKAGE"

mkdir -p "$BIN_DIR"
if ! printf '%s' "$PATH" | tr ':' '\n' | grep -qx "$BIN_DIR"; then
    echo
    echo "Add this to your shell profile so 'vspagent' is on PATH:"
    echo "  export PATH=\"$BIN_DIR:\$PATH\""
fi

echo
echo "Installed. Try:"
echo "  vspagent auth login kimi"
echo "  vspagent \"explain this repository\""
echo
echo "Repository: https://github.com/${REPO}"
