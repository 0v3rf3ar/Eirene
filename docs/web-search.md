# Web research

[Documentation](README.md) / Web research

Eirene can search the web and read relevant pages when a task needs current facts,
documentation, or external sources. Ask for a specific question and request
source links when you need to verify the answer.

```text
Find the official documentation for this API's pagination behavior and link the relevant section.
```

## Search and read

Normal search uses DuckDuckGo. Eirene returns a bounded set of titles, URLs,
snippets, and sometimes relevant page passages, then reads selected sources as
needed. Repeated queries can use a short-lived in-memory cache. Search is separate
from rendering a page in a browser.

Network access follows your current permissions. Plan mode can perform permitted
read-only research, but does not start browser automation or imported MCP servers.
A page requiring JavaScript may need [browser inspection](browser.md) in a normal
mode.

## Optional Tavily fallback

```text
/search-api
```

Choose Tavily and enter the key in the hidden prompt. Do not pass a key as a
slash-command argument; `/search-api` accepts no arguments. Eirene validates the
key through the usage endpoint rather than charging a search for validation.

Tavily is a fallback when normal search cannot provide usable results, not a
replacement for every search. Eirene uses basic searches; a fallback search can
consume a Tavily credit. The Tavily account controls available credits and access.

Run `/search-api` again to keep, replace, or remove the saved key. Removing it
returns to normal search only. Key storage follows the selected credential store;
see [configuration](configuration.md).

## Limits and recovery

A challenge page, rate limit, missing result, or inaccessible source is not proof
that the requested information does not exist. Ask for a narrower query, an
official page, or a source you already know. Avoid repeating an identical blocked
query immediately.

Tavily rate and credit failures pause the fallback while normal search remains
available. Replacing the key resets its fallback state. Browser access may still
fail on authentication, bot protection, or network restrictions; Eirene cannot
read a page merely because a search result lists it.

For rendered-page inspection and screenshots, see [browser work](browser.md).
For audits against current interface guidance, see
[Web Design Guidelines](plugins/web-design-guidelines.md).

## Cache and request bounds

The search service accepts queries up to 1500 characters, bounds result counts
to 1–8, and bounds its formatted output to 12000 characters. Successful repeated
queries can use an in-memory cache for 600 seconds with at most 64 entries. This
cache is not a saved research database and does not survive process restart.

Normal search and selected-page fetches have separate download/text bounds.
Fetches extract readable text; they do not execute site JavaScript or maintain an
interactive authenticated browser session. Tavily basic search is a fallback
with independent credit/cooldown state, not the model provider's search mode.

The saved fallback object is `search_api`, distinct from `providers`. Its keyring
identity is `search:tavily`; generic provider API-key environment lookup does not
apply to it. See [search configuration](config-file.md#search-api).
