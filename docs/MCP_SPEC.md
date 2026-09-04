# Model Context Protocol (MCP) Integration Specification

The CONVO Agent Platform natively supports the **Model Context Protocol (MCP)** specification (JSON-RPC 2.0).

---

## 1. Exposing Convo Tools to External MCP Clients

External LLM agents, Claude Desktop, or Cursor can interact with the Convo platform using the standard endpoint:

`POST /api/v1/tools/mcp/rpc`

### Listing Available Tools (`tools/list`)

**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "tools/list"
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "result": {
    "tools": [
      {
        "name": "get_cluster_metrics",
        "description": "Retrieves real-time CPU, memory, and error rates for a Kubernetes cluster.",
        "inputSchema": {
          "type": "object",
          "properties": {
            "cluster": { "type": "string", "description": "Target cluster name" },
            "metric": { "type": "string", "description": "Metric name to inspect" }
          },
          "required": ["cluster", "metric"]
        }
      }
    ]
  }
}
```

---

### Executing an MCP Tool (`tools/call`)

**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": "2",
  "method": "tools/call",
  "params": {
    "name": "get_cluster_metrics",
    "arguments": {
      "cluster": "prod-east",
      "metric": "cpu_utilization"
    }
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": "2",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\n  \"cluster\": \"prod-east\",\n  \"metric\": \"cpu_utilization\",\n  \"value\": 94.8,\n  \"status\": \"CRITICAL\"\n}"
      }
    ],
    "isError": false
  }
}
```

---

## 2. Ingesting External MCP Tool Servers

The platform also provides `ExternalMCPClientAdapter` in `convo_registry.mcp_adapter` allowing the shared runtime to connect to external MCP servers (via stdio or HTTP/SSE), discover their tools, and dynamically mount them into the Convo registry.
