#!/usr/bin/env bash
# vspagent installer for Linux and macOS.
#
#   curl -fsSL https://github.com/vishnusureshperumbavoor/vspagent/releases/latest/download/install.sh | sh
#
# Environment:
#   VSPAGENT_VERSION   pinned version (default: 4.0.0), or "latest"
#   VSPAGENT_GIT_REF   GitHub tag/branch fallback (default: v<version>)
#   VSPAGENT_REPO      GitHub repo used for the source fallback
#   VSPAGENT_BIN_DIR   optional install directory hint
set -euo pipefail

REPO="${VSPAGENT_REPO:-vishnusureshperumbavoor/vspagent}"
VERSION="${VSPAGENT_VERSION:-4.0.0}"
BIN_DIR="${VSPAGENT_BIN_DIR:-$HOME/.local/bin}"
GIT_REF="${VSPAGENT_GIT_REF:-v${VERSION}}"
if [ "$VERSION" = "latest" ]; then
    GIT_REF="${VSPAGENT_GIT_REF:-master}"
fi

if [ -t 1 ]; then
    BOLD=$'\033[1m'
    DIM=$'\033[2m'
    GREEN=$'\033[32m'
    CYAN=$'\033[36m'
    YELLOW=$'\033[33m'
    RESET=$'\033[0m'
else
    BOLD=""
    DIM=""
    GREEN=""
    CYAN=""
    YELLOW=""
    RESET=""
fi

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
        printf "  ${GREEN}✓${RESET} %s removed\n" "vspagent"
    else
        printf "  %s uv is not installed; nothing to uninstall.%s\n" "$YELLOW" "$RESET" >&2
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
        printf "  %s vspagent currently supports Linux and macOS only.%s\n" "$YELLOW" "$RESET" >&2
        exit 1
        ;;
esac

if ! command -v uv >/dev/null 2>&1; then
    printf "  ${DIM}uv not found; installing it from astral.sh ...${RESET}\n"
    if ! command -v curl >/dev/null 2>&1; then
        printf "  %s curl is required to bootstrap uv.%s\n" "$YELLOW" "$RESET" >&2
        exit 1
    fi
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

install_pypi() {
    uv tool install --force --quiet "$PACKAGE"
}

install_github() {
    local ref="$1"
    uv tool install --force --quiet "vspagent @ git+https://github.com/${REPO}.git@${ref}"
}

pypi_has_version() {
    command -v curl >/dev/null 2>&1 || return 1
    curl -fsS -o /dev/null "https://pypi.org/pypi/vspagent/${VERSION}/json" 2>/dev/null
}

if [ "$VERSION" = "latest" ]; then
    printf "  ${DIM}Installing vspagent from GitHub (${GIT_REF}) ...${RESET}\n"
    install_github "$GIT_REF"
    PACKAGE="vspagent"
else
    PACKAGE="vspagent==${VERSION}"
    if pypi_has_version; then
        printf "  ${DIM}Installing ${PACKAGE} from PyPI ...${RESET}\n"
        if ! install_pypi; then
            printf "  ${DIM}PyPI install failed; using GitHub (${GIT_REF}) ...${RESET}\n"
            install_github "$GIT_REF" || install_github master
        fi
    else
        printf "  ${DIM}Installing ${PACKAGE} from GitHub (${GIT_REF}) ...${RESET}\n"
        if ! install_github "$GIT_REF"; then
            printf "  ${DIM}Tag ${GIT_REF} not found; using master ...${RESET}\n"
            install_github master
        fi
    fi
fi

ACTUAL_BIN="$(uv tool dir --bin 2>/dev/null || printf '%s' "$BIN_DIR")"
INSTALLED_VERSION="$("$ACTUAL_BIN/vspagent" --version 2>/dev/null | awk '{print $NF}' || true)"
[ -n "$INSTALLED_VERSION" ] || INSTALLED_VERSION="$VERSION"

printf "\n"
printf "  ${GREEN}✓${RESET} ${BOLD}vspagent ${INSTALLED_VERSION}${RESET} is installed\n"
printf "  ${DIM}──────────────────────────────────────────────${RESET}\n"
printf "  ${DIM}binary${RESET}    %s\n" "$ACTUAL_BIN/vspagent"
printf "  ${DIM}alias${RESET}     %s\n" "$ACTUAL_BIN/vsp"
printf "  ${DIM}provider${RESET}  Kimi (default, OpenAI-compatible)\n"
printf "  ${DIM}config${RESET}    ~/.config/vspagent/config.toml\n"
printf "\n"
printf "  ${BOLD}Get started${RESET}\n"
printf "    ${CYAN}vspagent auth login kimi${RESET}\n"
printf "    ${CYAN}vspagent${RESET}\n"
printf "\n"
printf "  ${DIM}docs${RESET}      https://github.com/${REPO}\n"

if ! printf '%s' "$PATH" | tr ':' '\n' | grep -qx "$ACTUAL_BIN"; then
    printf "\n"
    printf "  ${YELLOW}Add ${ACTUAL_BIN} to PATH:${RESET}\n"
    printf "    export PATH=\"%s:\$PATH\"\n" "$ACTUAL_BIN"
fi
printf "\n"
