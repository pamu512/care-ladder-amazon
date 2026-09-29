# Amazon tools friction log

Honest record of what worked and what fought back, per Amazon surface touched.
(Submission requirement: product feedback notes on every tool/API/SDK used.)

## mcp Python SDK (v2.2.0) - 2026-09-26

**Worked:** `MCPServer` (the v2 rename of FastMCP) tool registration is clean -
plain functions with type hints become MCP tools with schemas automatically.
`streamable_http_app()` returns a Starlette ASGI app; stateless mode removes
session-id bookkeeping for simple demos. The client half
(`streamable_http_client` + `ClientSession`) drove our server over real HTTP
first try once mounted correctly.

**Fought back:**

1. **v1 -> v2 rename with a hard error.** `mcp.server.fastmcp` no longer
   exists in 2.x; importing it raises a helpful-enough ModuleNotFoundError
   pointing at the migration guide. Cost: one probe cycle. Docs should put
   the v2 import path (`mcp.server.mcpserver.MCPServer`) above the v1
   examples in search results.
2. **ASGI mounts do not propagate lifespan.** `streamable_http_app()` wires
   its `StreamableHTTPSessionManager.run()` as the app's lifespan - but a
   Starlette Mount never runs a sub-app's lifespan, so every request died
   with `RuntimeError: Task group is not initialized. Make sure to use
   run().` Fix: enter `mcp.session_manager.run()` from the PARENT app's
   lifespan (`app.router.lifespan_context` wrapper). The SDK's mounting
   docs assume you run the MCP app standalone; a "mounting inside another
   ASGI app" recipe would have saved an hour.
3. **Session-manager attribute name.** We looked for
   `server._session_manager`; it is `server.session_manager` (public) and it
   only exists AFTER `streamable_http_app()` is called (lazy). An early
   access raises `RuntimeError: Session manager can only be accessed after
   calling streamable_http_app()`.
4. **DNS-rebinding protection defaults ON for localhost hosts** and returns
   HTTP 421 Misdirected Request for non-Host-header clients (including test
   transports). Behind an ALB/CloudFront the Host header differs from
   127.0.0.1, so we disabled it explicitly via
   `TransportSecuritySettings(enable_dns_rebinding_protection=False)`. The
   default is good security for standalone servers; confusing when mounted.
5. **Result shape:** tool dict returns arrive at the client both as
   `structuredContent` and a JSON text blob; tests must unwrap
   `structuredContent` for typed access.

**Verdict:** usable, modern; the rough edges are all at the "embed in a larger
app" seam, which is exactly our deployment shape.

## Streamable HTTP transport (MCP 2025-11-25+) - 2026-09-26

Negotiation worked against both our TestClient-based tests and the real
uvicorn server; SSE and JSON response modes both observed. No version
mismatch errors once the client and server both declared 2025-11-25.

## Pending surfaces (to be filled as touched)

- Fire TV / Silk browser launch + recording (slice 4)
- CloudFront/ALB routing for /mcp (deploy check, slice 6)
