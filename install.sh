#!/usr/bin/env sh
# vspagent installer for Linux and macOS.
#
#   curl -fsSL https://github.com/vishnusureshperumbavoor/vspagent/releases/latest/download/install.sh | sh
#
# Environment:
#   VSPAGENT_VERSION   pinned version (default: 4.0.0), or "latest"
#   VSPAGENT_GIT_REF   GitHub tag/branch fallback (default: v<version>)
#   VSPAGENT_REPO      GitHub repo used for the source fallback
#   VSPAGENT_BIN_DIR   optional install directory hint
set -eu

REPO="${VSPAGENT_REPO:-vishnusureshperumbavoor/vspagent}"
VERSION="${VSPAGENT_VERSION:-4.0.0}"
BIN_DIR="${VSPAGENT_BIN_DIR:-$HOME/.local/bin}"
GIT_REF="${VSPAGENT_GIT_REF:-v${VERSION}}"
if [ "$VERSION" = "latest" ]; then
    GIT_REF="${VSPAGENT_GIT_REF:-master}"
fi

# POSIX sh has no $'...' strings; build ANSI escapes with printf instead.
if [ -t 1 ]; then
    BOLD="$(printf '\033[1m')"
    DIM="$(printf '\033[2m')"
    GREEN="$(printf '\033[32m')"
    CYAN="$(printf '\033[36m')"
    MAGENTA="$(printf '\033[35m')"
    YELLOW="$(printf '\033[33m')"
    RESET="$(printf '\033[0m')"
else
    BOLD=""
    DIM=""
    GREEN=""
    CYAN=""
    MAGENTA=""
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
        printf "  %s✓%s %svspagent%s removed\n" "$GREEN" "$RESET" "$BOLD" "$RESET"
    else
        printf "  %suv is not installed; nothing to uninstall.%s\n" "$YELLOW" "$RESET" >&2
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
        printf "  %svspagent currently supports Linux and macOS only.%s\n" \
            "$YELLOW" "$RESET" >&2
        exit 1
        ;;
esac

if ! command -v uv >/dev/null 2>&1; then
    printf "  %suv not found; installing it from astral.sh ...%s\n" "$DIM" "$RESET"
    if ! command -v curl >/dev/null 2>&1; then
        printf "  %scurl is required to bootstrap uv.%s\n" "$YELLOW" "$RESET" >&2
        exit 1
    fi
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

install_pypi() {
    uv tool install --force --quiet "$PACKAGE"
}

install_github() {
    REF="$1"
    uv tool install --force --quiet "vspagent @ git+https://github.com/${REPO}.git@${REF}"
}

pypi_has_version() {
    command -v curl >/dev/null 2>&1 || return 1
    curl -fsS -o /dev/null "https://pypi.org/pypi/vspagent/${VERSION}/json" 2>/dev/null
}

if [ "$VERSION" = "latest" ]; then
    printf "  %sInstalling vspagent from GitHub (%s) ...%s\n" "$DIM" "$GIT_REF" "$RESET"
    install_github "$GIT_REF"
    PACKAGE="vspagent"
else
    PACKAGE="vspagent==${VERSION}"
    if pypi_has_version; then
        printf "  %sInstalling %s from PyPI ...%s\n" "$DIM" "$PACKAGE" "$RESET"
        if ! install_pypi; then
            printf "  %sPyPI install failed; using GitHub (%s) ...%s\n" \
                "$DIM" "$GIT_REF" "$RESET"
            install_github "$GIT_REF" || install_github master
        fi
    else
        printf "  %sInstalling %s from GitHub (%s) ...%s\n" "$DIM" "$PACKAGE" "$GIT_REF" "$RESET"
        if ! install_github "$GIT_REF"; then
            printf "  %sTag %s not found; using master ...%s\n" "$DIM" "$GIT_REF" "$RESET"
            install_github master
        fi
    fi
fi

ACTUAL_BIN="$(uv tool dir --bin 2>/dev/null || printf '%s' "$BIN_DIR")"
INSTALLED_VERSION="$("$ACTUAL_BIN/vspagent" --version 2>/dev/null | awk '{print $NF}' || true)"
[ -n "$INSTALLED_VERSION" ] || INSTALLED_VERSION="$VERSION"

WIDTH="${COLUMNS:-}"
if [ -z "$WIDTH" ] && command -v tput >/dev/null 2>&1; then
    WIDTH="$(tput cols 2>/dev/null || true)"
fi
case "$WIDTH" in
    ''|*[!0-9]*) WIDTH=80 ;;
esac

printf "\n"
if [ "$WIDTH" -ge 80 ]; then
    printf "  %s%s%s\n" "$CYAN" "██╗   ██╗███████╗██████╗      █████╗  ██████╗ ███████╗███╗   ██╗████████╗" "$RESET"
    printf "  %s%s%s\n" "$CYAN" "██║   ██║██╔════╝██╔══██╗    ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝" "$RESET"
    printf "  %s%s%s\n" "$CYAN" "██║   ██║███████╗██████╔╝    ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║" "$RESET"
    printf "  %s%s%s\n" "$CYAN" "╚██╗ ██╔╝╚════██║██╔═══╝     ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║" "$RESET"
    printf "  %s%s%s\n" "$CYAN" " ╚████╔╝ ███████║██║         ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║" "$RESET"
    printf "  %s%s%s\n" "$CYAN" "  ╚═══╝  ╚══════╝╚═╝         ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝" "$RESET"
else
    printf "  %sVSP AGENT%s\n" "$BOLD$CYAN" "$RESET"
fi
printf "  %sterminal coding agent · v%s%s\n" "$DIM" "$INSTALLED_VERSION" "$RESET"
printf "  %s──────────────────────────────────────────────────────────────%s\n" "$DIM" "$RESET"
printf "\n"
printf "  %s✓%s %sInstalled successfully%s\n" "$GREEN" "$RESET" "$BOLD" "$RESET"
printf "\n"
printf "  %sbinary%s    %s\n" "$DIM" "$RESET" "$ACTUAL_BIN/vspagent"
printf "  %salias%s     %s\n" "$DIM" "$RESET" "$ACTUAL_BIN/vsp"
printf "  %sprovider%s  Kimi (default, OpenAI-compatible)\n" "$DIM" "$RESET"
printf "  %sconfig%s    ~/.config/vspagent/config.toml\n" "$DIM" "$RESET"
printf "\n"
printf "  %sGet started%s\n" "$BOLD" "$RESET"
printf "    %svspagent auth login kimi%s\n" "$MAGENTA" "$RESET"
printf "    %svspagent%s\n" "$MAGENTA" "$RESET"
printf "\n"
printf "  %sdocs%s      https://github.com/%s\n" "$DIM" "$RESET" "$REPO"

if ! printf '%s' "$PATH" | tr ':' '\n' | grep -qx "$ACTUAL_BIN"; then
    printf "\n"
    printf "  %sAdd %s to PATH%s\n" "$YELLOW" "$ACTUAL_BIN" "$RESET"
    printf "    export PATH=\"%s:\$PATH\"\n" "$ACTUAL_BIN"
fi
printf "\n"
