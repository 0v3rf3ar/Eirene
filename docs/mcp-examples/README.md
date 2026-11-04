# MCP examples

[Documentation](../README.md) / [MCP servers](../extending/mcp.md) / Examples

These are ready-to-import definitions for popular MCP servers, reviewed on 2026-10-20. Copy an example's contents into `/mcp add`, or import a downloaded copy:

```text
/mcp import /path/to/NAME.json
```

Eirene asks for any missing values and offers a connection test. Supply your own credentials: a JSON file cannot grant account access, or install a database or licensed service.

**How far these are tested.** All examples are tested for import and configuration. HTTP, SSE, OAuth and stdio connections are exercised against local test servers. The Playwright, Chrome DevTools and Puppeteer packages also passed real browser tool calls on Linux. Live accounts, deployments, every advertised tool, and other platforms were not tested.

## Developer tools

| Server | Documentation | You need |
| --- | --- | --- |
| [GitHub](github.json) | [Docs](https://github.com/github/github-mcp-server) | A GitHub personal access token with the required permissions, and organization approval where applicable. |
| [Sentry](sentry.json) | [Docs](https://mcp.sentry.dev/) | A Sentry account and OAuth consent. You can scope the URL to your organization or project. |
| [Context7](context7.json) | [Docs](https://github.com/upstash/context7) | A Context7 API key. |
| [Figma](figma.json) | [Docs](https://developers.figma.com/docs/figma-mcp-server/remote-server-installation/) | A Figma account, OAuth consent, file access, and your plan's rate limits. |
| [Webflow](webflow.json) | [Docs](https://github.com/webflow/mcp-server) | A Webflow account and OAuth consent. Designer operations also need its bridge app in the open site. |

## Browsers

| Server | Documentation | You need |
| --- | --- | --- |
| [Playwright](playwright.json) | [Docs](https://github.com/microsoft/playwright-mcp) | Node.js and a working browser with its system libraries. `browser_install` may be needed on first use. |
| [Chrome DevTools](chrome-devtools.json) | [Docs](https://github.com/ChromeDevTools/chrome-devtools-mcp) | A supported Node.js LTS, Chrome or Chromium, and its system libraries. |
| [Puppeteer](puppeteer.json) | [Docs](https://github.com/modelcontextprotocol/servers-archived/tree/main/src/puppeteer) | Node.js and Chrome or Chromium. This reference server is archived, so prefer a maintained one for new setups. |

## Infrastructure

| Server | Documentation | You need |
| --- | --- | --- |
| [Cloudflare](cloudflare.json) | [Docs](https://github.com/cloudflare/mcp) | A Cloudflare account and browser consent. |
| [Docker MCP Gateway](docker.json) | [Docs](https://docs.docker.com/ai/mcp-catalog-and-toolkit/get-started/) | The Docker MCP CLI plugin, a running daemon, and a configured gateway profile. |
| [Kubernetes](kubernetes.json) | [Docs](https://github.com/containers/kubernetes-mcp-server) | Node.js and a valid kubeconfig. Credential helpers must be installed and reachable. |
| [Terraform](terraform.json) | [Docs](https://developer.hashicorp.com/terraform/mcp-server/deploy/local) | A Docker daemon. A token and address for private HCP Terraform or Enterprise operations. |

## Databases and search

| Server | Documentation | You need |
| --- | --- | --- |
| [PostgreSQL](postgresql.json) | [Docs](https://github.com/crystaldba/postgres-mcp) | `uv` and reachable credentials. This is the community Postgres MCP Pro, and its restricted mode is read-only. |
| [MongoDB](mongodb.json) | [Docs](https://www.mongodb.com/docs/mcp-server/local-mcp/configuration/options/) | Node.js and a reachable deployment with credentials. |
| [Redis](redis.json) | [Docs](https://github.com/redis/mcp-redis) | `uv` and a reachable Redis URL. |
| [Elasticsearch](elasticsearch.json) | [Docs](https://github.com/elastic/mcp-server-elasticsearch) | Docker access, and an Elasticsearch URL and API key. |

## Productivity and collaboration

| Server | Documentation | You need |
| --- | --- | --- |
| [Notion](notion.json) | [Docs](https://developers.notion.com/guides/mcp/get-started-with-mcp) | OAuth consent and access to the workspace or pages. |
| [Slack](slack.json) | [Docs](https://docs.slack.dev/ai/slack-mcp-server/) | A registered Slack app with a matching callback, user scopes and workspace approval. Slack does not support dynamic client registration. |
| [Google Workspace](google-workspace.json) | [Docs](https://developers.google.com/workspace/guides/configure-mcp-servers) | The developer preview, enabled APIs, an agent-enabled OAuth client, a registered callback and organization consent. This example connects Gmail; other products have separate URLs. |
| [Google Drive](google-drive.json) | [Docs](https://developers.google.com/workspace/drive/api/guides/configure-mcp-server) | The developer preview, the Drive API, an agent-enabled OAuth client, and this callback registered with it. |
| [Microsoft 365](microsoft365.json) | [Docs](https://github.com/microsoft/work-iq) | Node.js, Microsoft 365 Copilot access, tenant administrator consent and Work IQ sign-in. This covers Work IQ, not every Graph operation. |

## Other services

| Server | Documentation | You need |
| --- | --- | --- |
| [Ahrefs](ahrefs.json) | [Docs](https://docs.ahrefs.com/en/mcp/docs/introduction) | A paid Ahrefs plan and OAuth consent. |
| [Burp Suite](burpsuite.json) | [Docs](https://github.com/PortSwigger/mcp-server) | The Burp MCP extension running. If your version shows a different address or transport, paste the configuration it exports instead. |
| [X (Twitter)](x-twitter.json) | [Docs](https://github.com/isteamhq/mcp-servers) | Node.js and an X developer app with OAuth 1.0a keys. This is a community server. |

## Notes

- `${input:...}` placeholders are requested when you import. `${VAR}` and `${env:VAR}` use your environment, and missing values are requested securely. See [Accepted formats](../extending/mcp.md#accepted-formats).
- The Google and Slack examples adapt those services' documented requirements into JSON, because they need an app registered outside Eirene. Enter that app's credentials in the `oauth` object.
