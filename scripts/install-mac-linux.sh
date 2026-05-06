#!/usr/bin/env bash
set -euo pipefail

OCLITE_REPO="${OCLITE_REPO:-https://github.com/StrategicoDev/strategico-oclite.git}"
OCLITE_BRANCH="${OCLITE_BRANCH:-main}"
OCLITE_SRC="${OCLITE_SRC:-$HOME/.oclite-src}"
OCLITE_HOME="${OCLITE_HOME:-$HOME/.oclite}"
OCLITE_BIN_DIR="${OCLITE_BIN_DIR:-$HOME/.local/bin}"
OCLITE_PORT="${OCLITE_PORT:-8787}"
OCLITE_HOST="${OCLITE_HOST:-127.0.0.1}"

info() {
  printf '==> %s\n' "$1"
}

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

ensure_path() {
  case ":$PATH:" in
    *":$OCLITE_BIN_DIR:"*) ;;
    *)
      export PATH="$OCLITE_BIN_DIR:$PATH"
      local profile=""
      if [ -n "${ZSH_VERSION:-}" ]; then
        profile="$HOME/.zshrc"
      elif [ -n "${BASH_VERSION:-}" ]; then
        profile="$HOME/.bashrc"
      elif [ -f "$HOME/.zshrc" ]; then
        profile="$HOME/.zshrc"
      elif [ -f "$HOME/.bashrc" ]; then
        profile="$HOME/.bashrc"
      fi

      if [ -n "$profile" ] && ! grep -qs "$OCLITE_BIN_DIR" "$profile"; then
        printf '\n# OCLite\nexport PATH="%s:$PATH"\n' "$OCLITE_BIN_DIR" >> "$profile"
        info "Added $OCLITE_BIN_DIR to $profile"
      fi
      ;;
  esac
}

need_cmd git
need_cmd python3

info "Installing OCLite from $OCLITE_REPO"

mkdir -p "$OCLITE_BIN_DIR"
ensure_path

if [ -d "$OCLITE_SRC/.git" ]; then
  info "Updating existing source at $OCLITE_SRC"
  git -C "$OCLITE_SRC" fetch --prune origin "$OCLITE_BRANCH"
  git -C "$OCLITE_SRC" checkout "$OCLITE_BRANCH"
  git -C "$OCLITE_SRC" pull --ff-only origin "$OCLITE_BRANCH"
else
  info "Cloning source to $OCLITE_SRC"
  rm -rf "$OCLITE_SRC"
  git clone --branch "$OCLITE_BRANCH" "$OCLITE_REPO" "$OCLITE_SRC"
fi

cat > "$OCLITE_BIN_DIR/oclite" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export OCLITE_HOME="\${OCLITE_HOME:-$OCLITE_HOME}"
exec python3 "$OCLITE_SRC/run.py" "\$@"
EOF

chmod +x "$OCLITE_BIN_DIR/oclite"

if ! printf '%s' "$PATH" | grep -q "$OCLITE_BIN_DIR"; then
  info "Add this to your shell profile if oclite is not found:"
  printf 'export PATH="$HOME/.local/bin:$PATH"\n'
fi

info "Initializing isolated runtime at $OCLITE_HOME"
"$OCLITE_BIN_DIR/oclite" setup

info "Install complete"
printf '\nRun the control UI:\n'
printf '  oclite run --host %s --port %s\n' "$OCLITE_HOST" "$OCLITE_PORT"
printf '\nWorks immediately in this terminal too:\n'
printf '  "%s/oclite" run --host %s --port %s\n' "$OCLITE_BIN_DIR" "$OCLITE_HOST" "$OCLITE_PORT"
printf '\nThen open:\n'
printf '  http://%s:%s\n' "$OCLITE_HOST" "$OCLITE_PORT"
