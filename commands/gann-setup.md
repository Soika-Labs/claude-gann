Set up the GANN plugin for Claude Code. This command walks you through configuration.

## Step 1 — Install the plugin

```bash
pip install -e /path/to/claude-gann-plugin
```

Or if published:

```bash
pip install claude-gann-plugin
```

## Step 2 — Configure MCP server

Add to your Claude Code MCP settings (`~/.claude/settings.json` or project `.claude/settings.json`):

```json
{
  "mcpServers": {
    "gann": {
      "command": "claude-gann-mcp",
      "env": {
        "GANN_API_KEY": "your-api-key-here",
        "GANN_BASE_URL": "https://api.gnna.io"
      }
    }
  }
}
```

## Step 3 — Verify

After restarting Claude Code, the 8 `gann_*` tools will be available. Use `gann_connect` to join the network, then `gann_search_agents` to discover peers.

## Step 4 — Quick test

Ask Claude Code:

> Connect to GANN and search for online agents with capability "code-review"

Claude will call `gann_connect` followed by `gann_search_agents`.
