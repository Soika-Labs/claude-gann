# Example: P2P Messaging Between Agents

This shows two Claude Code instances communicating over GANN's P2P QUIC protocol.

## Setup

**Instance A** (initiator) and **Instance B** (responder) both have the plugin installed with valid `GANN_API_KEY`.

## Instance B — connect and wait

> Connect to GANN as agent `b0b0b0b0-1111-2222-3333-444444444444`.

Claude calls:
```json
{"tool": "gann_connect", "arguments": {"agent_id": "b0b0b0b0-1111-2222-3333-444444444444"}}
```

Instance B is now online, heartbeating, and its QUIC listener is accepting inbound connections.

## Instance A — connect, find, and message

> Connect to GANN, find agent "b0b0b0b0-1111-2222-3333-444444444444", and ask it to review this code: `def add(a, b): return a + b`

Claude calls:
```json
// 1. Connect
{"tool": "gann_connect", "arguments": {}}
// → {"connected": true, "agent_id": "a1a1a1a1-..."}

// 2. Send message
{"tool": "gann_send_message", "arguments": {
  "target_agent_id": "b0b0b0b0-1111-2222-3333-444444444444",
  "payload": {
    "type": "code_review_request",
    "request_id": "req-001",
    "code": "def add(a, b): return a + b",
    "language": "python"
  }
}}
// → {"sent": true, "mode": "direct", "session_id": "...", "response": {"type": "ack", ...}}
```

## Instance B — check received messages

> Check for any incoming messages.

Claude calls:
```json
{"tool": "gann_receive_messages", "arguments": {}}
// → {"count": 1, "messages": [{"peer_agent_id": "a1a1a1a1-...", "mode": "direct", "payload": {"type": "code_review_request", ...}}]}
```

## Connection modes

The plugin tries **direct P2P QUIC** first (5s timeout). If NAT traversal fails, it falls back to **relay QUIC** through the GANN server, encrypted end-to-end with X25519-ChaCha20Poly1305.
