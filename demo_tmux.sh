#!/usr/bin/env bash
# ZeroWall tmux UI launcher
# Run this from inside any tmux session.
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="python3"
SCRIPT="$DIR/demo_ui.py"
WIN="zerowall-demo"

# ── create a new window in the current session ───────────────────────────────
tmux new-window -n "$WIN"

# ── split into 4 panes (2x2 grid) ────────────────────────────────────────────
#
#  ┌──────────────────────┬──────────────────────┐
#  │  STATUS (top-left)   │  ATTACKS (top-right) │
#  ├──────────────────────┼──────────────────────┤
#  │  DEFENSE (bot-left)  │ TELEMETRY (bot-right)│
#  └──────────────────────┴──────────────────────┘

# Split the initial pane horizontally (top-left | top-right)
tmux split-window -h -t "$WIN"

# Split top-left vertically → top-left + bot-left
tmux split-window -v -t "${WIN}.0"

# Split top-right vertically → top-right + bot-right
tmux split-window -v -t "${WIN}.1"

# ── launch each panel ────────────────────────────────────────────────────────
tmux send-keys -t "${WIN}.0" "clear && $PY $SCRIPT --panel status"    Enter
tmux send-keys -t "${WIN}.1" "clear && $PY $SCRIPT --panel attacks"   Enter
tmux send-keys -t "${WIN}.2" "clear && $PY $SCRIPT --panel defense"   Enter
tmux send-keys -t "${WIN}.3" "clear && $PY $SCRIPT --panel telemetry" Enter

# ── select pane 0 so the user sees the top-left first ────────────────────────
tmux select-pane -t "${WIN}.0"

echo "ZeroWall demo UI launched in tmux window '$WIN'"
echo "Switch to it: tmux select-window -t '$WIN'"
echo "Kill it:      tmux kill-window -t '$WIN'"
