# MCP JSON compatibility examples

Reviewed 2026-10-20. These are import examples and regression fixtures, not built-in provider presets. Slack appears once because it was listed twice.

Run `/mcp add` and paste an example, or `/mcp import docs/mcp-examples/NAME.json`. Eirene prompts for unresolved values and offers a connection test. Supply your own credentials; a JSON file cannot grant account access or install a running database, licensed service, or tenant consent.

**Validation boundary:** all examples are tested for import and runtime configuration. HTTP/SSE, OAuth, and stdio are exercised against local test servers. The published Playwright, Chrome DevTools, and archived Puppeteer packages also passed actual browser tool calls against about:blank on Linux using installed Chromium and Node.js; Puppeteer used its documented headless option. This does not certify live account access, deployments, every advertised tool, or other platforms.

| Integration / JSON | Maintainer documentation | External requirements |
| --- | --- | --- |
| [Cloudflare](cloudflare.json) | [Source](https://github.com/cloudflare/mcp) | Cloudflare account and browser consent. |
| [Burp Suite](burpsuite.json) | [Source](https://github.com/PortSwigger/mcp-server) | Running Burp MCP extension; use the endpoint and transport shown by your installed extension. |
| [Google Workspace](google-workspace.json) | [Source](https://developers.google.com/workspace/guides/configure-mcp-servers) | Google Workspace developer preview, enabled APIs, agent-enabled OAuth client, registered callback, and organization consent. This example connects Gmail; products have separate URLs. |
| [Ahrefs](ahrefs.json) | [Source](https://docs.ahrefs.com/en/mcp/docs/introduction) | Paid Ahrefs plan and OAuth consent. The former @ahrefs/mcp package is archived and uses different API keys. |
| [Redis](redis.json) | [Source](https://github.com/redis/mcp-redis) | uv and a reachable Redis URL; credentials/TLS settings where required. |
| [MongoDB](mongodb.json) | [Source](https://www.mongodb.com/docs/mcp-server/local-mcp/configuration/options/) | Node.js and a reachable MongoDB deployment with appropriate database credentials. |
| [Elasticsearch](elasticsearch.json) | [Source](https://github.com/elastic/mcp-server-elasticsearch) | Docker daemon access and Elasticsearch URL/API key. |
| [Puppeteer](puppeteer.json) | [Source](https://github.com/modelcontextprotocol/servers-archived/tree/main/src/puppeteer) | Archived reference implementation; Node.js, compatible Chrome/Chromium, and browser system libraries. Prefer a maintained browser server for new deployments. |
| [Webflow](webflow.json) | [Source](https://github.com/webflow/mcp-server) | Webflow account and OAuth consent; Designer operations also require its bridge app in the open site. |
| [Microsoft 365](microsoft365.json) | [Source](https://github.com/microsoft/work-iq) | Node.js, Microsoft 365 Copilot access, tenant administrator consent, and Work IQ sign-in. This is Work IQ access, not a promise of every Graph operation. |
| [X (Twitter)](x-twitter.json) | [Source](https://github.com/isteamhq/mcp-servers) | Community implementation; Node.js and an X developer app with API access and OAuth 1.0a keys/tokens. No official X MCP endpoint was verified. |
| [GitHub](github.json) | [Source](https://github.com/github/github-mcp-server) | GitHub PAT with required permissions and organization approval where applicable. |
| [Docker MCP Gateway](docker.json) | [Source](https://docs.docker.com/ai/mcp-catalog-and-toolkit/get-started/) | Installed Docker MCP CLI plugin, running Docker daemon, and a configured gateway profile. The gateway exposes the servers in that profile. |
| [Google Drive](google-drive.json) | [Source](https://developers.google.com/workspace/drive/api/guides/configure-mcp-server) | Workspace developer preview, enabled Drive API, agent-enabled OAuth client and consent. Register this callback with the OAuth client. |
| [Terraform](terraform.json) | [Source](https://developer.hashicorp.com/terraform/mcp-server/deploy/local) | Docker daemon. A token and address are needed for private HCP Terraform/Enterprise operations. |
| [Kubernetes](kubernetes.json) | [Source](https://github.com/containers/kubernetes-mcp-server) | Node.js and valid kubeconfig/cluster credentials. External exec credential helpers must be installed and accessible. |
| [Sentry](sentry.json) | [Source](https://mcp.sentry.dev/) | Sentry account and OAuth consent; optionally scope the URL to your organization/project. |
| [Chrome DevTools](chrome-devtools.json) | [Source](https://github.com/ChromeDevTools/chrome-devtools-mcp) | Supported Node.js LTS, Chrome/Chromium and its OS dependencies. Browser startup is separate from MCP discovery. |
| [Context7](context7.json) | [Source](https://github.com/upstash/context7) | Context7 API key for the documented authenticated endpoint. |
| [Figma](figma.json) | [Source](https://developers.figma.com/docs/figma-mcp-server/remote-server-installation/) | Figma account, OAuth consent, file access and applicable plan/rate limits. |
| [Notion](notion.json) | [Source](https://developers.notion.com/guides/mcp/get-started-with-mcp) | Notion OAuth consent and access to the chosen workspace/pages. |
| [Slack](slack.json) | [Source](https://docs.slack.dev/ai/slack-mcp-server/) | Registered internal or Marketplace Slack app; matching callback, app credentials, user scopes, and workspace approval. Slack does not support dynamic client registration. |
| [PostgreSQL](postgresql.json) | [Source](https://github.com/crystaldba/postgres-mcp) | Community Postgres MCP Pro; uv and reachable PostgreSQL credentials. Restricted mode is read-only. The old reference server is archived. |
| [Playwright](playwright.json) | [Source](https://github.com/microsoft/playwright-mcp) | Supported Node.js and a working browser with OS dependencies; browser_install may be needed on first use. |

Examples with `${input:...}` request values in Eirene. Existing environment variables referenced by `${VAR}` or `${env:VAR}` are resolved; missing values are requested securely. OAuth app credentials are supported through an `oauth` object. Google and Slack examples adapt the providers’ documented endpoint/auth requirements into JSON because those services require an app registered outside Eirene.

Archived reference servers remain importable for compatibility, but archival is recorded above. X and Postgres MCP Pro are community implementations; they are not represented as vendor-official servers. Burp extension versions can expose different endpoints/transports: paste the configuration exported by the installed extension when its URL differs from this example.
