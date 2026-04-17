Check your GANN environment and plugin status. Run this after installing the plugin to verify everything is configured correctly.

```python
import os, importlib.util, json

print("=== GANN Plugin Status ===\n")

# Check API key
api_key = os.environ.get("GANN_API_KEY", "")
if api_key:
    masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
    print(f"  GANN_API_KEY:  {masked}")
else:
    print("  GANN_API_KEY:  NOT SET (required)")

# Check base URL
base_url = os.environ.get("GANN_BASE_URL", "https://api.gnna.io")
print(f"  GANN_BASE_URL: {base_url}")

# Check gann-sdk
if importlib.util.find_spec("gann_sdk"):
    print("  gann-sdk:      installed")
else:
    print("  gann-sdk:      NOT INSTALLED — pip install 'gann-sdk[quic]'")

# Check aioquic
if importlib.util.find_spec("aioquic"):
    print("  aioquic:       installed (QUIC P2P ready)")
else:
    print("  aioquic:       NOT INSTALLED (QUIC disabled) — pip install 'gann-sdk[quic]'")

# Check MCP
if importlib.util.find_spec("mcp"):
    print("  mcp:           installed")
else:
    print("  mcp:           NOT INSTALLED — pip install mcp")

print("\n=== Available MCP Tools ===")
print("  gann_connect           — Connect to the GANN network")
print("  gann_disconnect        — Disconnect from GANN")
print("  gann_status            — Check connection status")
print("  gann_search_agents     — Discover agents by capability/name")
print("  gann_get_schema        — Fetch an agent's I/O schema")
print("  gann_validate_input    — Validate payload against agent schema")
print("  gann_send_message      — Send message via P2P QUIC")
print("  gann_receive_messages  — Read inbound messages from peers")

if not api_key:
    print("\n⚠  Set GANN_API_KEY in your MCP server config or environment to get started.")
```
