# Czech tabloid & clickbait blocklists

Blocklists that block Czech tabloid, celebrity-gossip, clickbait and low-value
lifestyle websites on your network.

- **Basic** (10 sites) — conservative
- **Aggressive** (37 sites) — superset of Basic; subscribe to only one

Each list ships in three formats, generated from the same domain list:

| Format | Line | Works with |
|--------|------|------------|
| [`basic.txt`](lists/basic.txt) | `super.cz` | Pi-hole (recommended), Unbound, pfBlockerNG |
| [`basic.abp`](lists/basic.abp) | `\|\|super.cz^` | Pi-hole ≥5.16, AdGuard Home, uBlock |
| [`basic.hosts`](lists/basic.hosts) | `0.0.0.0 super.cz` | /etc/hosts, dnsmasq, routers |

Swap `basic` for `aggressive` for the other scope.

## Pi-hole (recommended: `.txt`)

Paste a raw URL into Pi-hole → **Lists** → **Add a new subscribed list**, then
run `pihole -g`:

```text
https://raw.githubusercontent.com/smykalk/cz-tabloid-blocklists/master/lists/basic.txt
https://raw.githubusercontent.com/smykalk/cz-tabloid-blocklists/master/lists/aggressive.txt
```

These are exact hostnames, not wildcards: `super.cz` and `www.super.cz` do not
block `*.super.cz`.

## Wildcards (`.abp`)

`||super.cz^` blocks the domain and every subdomain. Current Pi-hole (≥ 5.16)
parses this natively from a normal adlist; older versions ignore it. AdGuard
Home and uBlock Origin understand it too. Use the same URLs with `.abp` instead
of `.txt`.

## Development

`lists/*.txt` are the source of truth; `.hosts` and `.abp` are generated:

```bash
python3 scripts/validate.py --write   # regenerate derived formats
python3 scripts/validate.py           # check everything
python3 -m unittest discover -s tests
```

Public domain — released under the [Unlicense](LICENSE); the lists are provided
as-is.
