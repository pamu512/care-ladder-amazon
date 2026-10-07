# AgentCore Gateway

Alexa+ stays on self-hosted `/mcp` (Streamable HTTP, MCP spec 2025-11-25+) and `alexa_sim`. This gateway is the AWS Builder front door for the same tools. It does not replace either one.

## Auth wiring

1. Credential provider on the gateway (`CreateApiKeyCredentialProvider`). The value is `CARE_LADDER_API_TOKEN`. The dry-run print redacts it.
2. Gateway target forwards `Authorization` with prefix `Bearer` in the `HEADER` slot to the MCP URL.
3. The task that serves `/mcp` must set `CARE_LADDER_MCP_HOSTS` to that URL's hostname. Without it, DNS-rebinding protection returns 421. `localhost` and `testserver` stay allowed.

`/mcp` returns 401 when the bearer is missing, unless `CARE_LADDER_ALLOW_INSECURE_LOCAL=1`.

Default region is `us-east-1` (same region as the existing ALB). If the SDK region list does not include the region you pick, a URL target can still be used on purpose. The smoke print says which case you are in.

Do not use `care-ladder-demo-2017970097.us-east-1.elb.amazonaws.com` as the target until that service actually serves `/mcp`. As of `docs/friction-log.md` (2026-09-29) that host returns 404 for `/mcp`.

## Judge sequence

Against the care-ladder API (local or the dedicated task), with the bearer set:

1. `initialize` with `protocolVersion` `2025-11-25`
2. `tools/list`
3. `tools/call` `how_is_household`

```bash
python scripts/agentcore_gateway_smoke.py
```

The script also prints the control-plane JSON and `gateway id: deferred`. It does not call AWS unless you pass `--deploy` and `CARE_LADDER_AGENTCORE_DEPLOY=1`.

Live create also needs `CARE_LADDER_API_TOKEN`, `CARE_LADDER_AGENTCORE_ROLE_ARN`, and `CARE_LADDER_GATEWAY_MCP_URL`.

```bash
export CARE_LADDER_AGENTCORE_DEPLOY=1
export CARE_LADDER_AGENTCORE_ROLE_ARN=arn:aws:iam::ACCOUNT:role/CareLadderAgentCoreGateway
export CARE_LADDER_GATEWAY_MCP_URL=https://YOUR_CARE_LADDER_HOST/mcp/
export CARE_LADDER_AGENTCORE_REGION=us-east-1
python scripts/agentcore_gateway_smoke.py --deploy
```

Then set `CARE_LADDER_MCP_HOSTS` on the target task to the hostname in that URL and redeploy the task. The gateway outbound call must send the bearer the API already checks.

Pinned boto3 must expose `CreateGateway`, `CreateGatewayTarget`, `SynchronizeGatewayTargets`, and `CreateApiKeyCredentialProvider`. `tests/test_agentcore_gateway.py` fails if the lockfile SDK does not.
