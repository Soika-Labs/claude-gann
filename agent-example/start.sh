#!/bin/bash
# Start the Robotics Supplier Agent in Claude Code CLI
#
# Usage:
#   ./start.sh <agent_id>
#
# Make sure to:
#   1. Set GANN_API_KEY in .claude/settings.json
#   2. Install the plugin: pip install claude-gann-plugin
#   3. Register your agent first using gann_register_agent in Claude Code

set -e

AGENT_ID="${1:?Usage: ./start.sh <agent_id>}"

cd "$(dirname "$0")"

echo "Starting Robotics Supplier Agent..."
echo "Agent ID: $AGENT_ID"
echo ""

claude -p "Connect to GANN with agent_id '$AGENT_ID'. Then monitor for incoming messages — check every 30 seconds using gann_receive_messages. When you receive a message, process it according to your role as a Robotics Supplier Agent and reply using gann_reply. Keep monitoring continuously."
