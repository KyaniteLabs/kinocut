# Directory status board

Public discovery surfaces for Kinocut. **Update this file when a directory changes.**  
Detailed history: [DIRECTORY_REBRAND_STATUS.md](DIRECTORY_REBRAND_STATUS.md).

Canonical facts: [`public_claims.json`](public_claims.json).

## Live board

| Surface | Role | Status (maintain) | Link |
| --- | --- | --- | --- |
| Product site | Marketing + GEO | Live | https://kinocut.dev/ |
| PyPI | Package | Live `kinocut` | https://pypi.org/project/kinocut/ |
| MCP Registry | Official MCP listing | Live id `io.github.KyaniteLabs/kinocut` | https://registry.modelcontextprotocol.io/v0/servers/io.github.KyaniteLabs%2Fkinocut/versions/latest |
| GitHub | Public mirror | Live | https://github.com/KyaniteLabs/kinocut |
| Forgejo | Canonical source | Live | https://git.kyanitelabs.tech/KyaniteLabs/kinocut |
| Glama | Directory / score | Recrawl / stale metadata risk | Track in rebrand ledger |
| Awesome MCP Servers | Curated list | Correction PR process | Track in rebrand ledger |
| Docker MCP Catalog | Catalog | PR / review as applicable | Track in rebrand ledger |
| Smithery | MCPB-style | Blocked on native runtime gates | See MCPB.md |
| MCP.so / others | Aggregators | Submission / recrawl | Track in rebrand ledger |

## Release-time checklist

After every public package release:

1. Confirm PyPI version == `public_claims.json` → `published_version`  
2. Confirm Registry entry shows new version  
3. Update `published_*` counts in `public_claims.json` if the surface changed  
4. Run `pytest tests/test_public_claims.py`  
5. Spot-check kinocut.dev version language  
6. File or close directory tickets (Glama, Awesome, etc.)

## Agent instruction

When asked “is Kinocut listed on X?”, read this board and the rebrand ledger; do not invent “listed” without a live URL.
