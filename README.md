# Repost Today Domain List

This repository package contains the public domain list for **Repost Today**, a candidate FIMI Information Manipulation Set (IMS) of WordPress-based news-style outlets.

The full report is available at [RRN.world/rt-1516](https://rrn.world/rt-1516).

## Contents

- `data/repost_today_sites.csv`  
  One-column domain list for the current report scope.

- `sources/README.md`  
  Source links used as external context.

- `tools/`  
  Python tooling for collecting public WordPress REST posts and finding exact cross-domain article matches.

- `sample-data/`  
  Lightweight article-match outputs and a curated AI/rewrite detection CSV used as supporting evidence in the report. The large raw article cache is omitted and can be regenerated with the tool.

## Current Scope

- 58 domains in `data/repost_today_sites.csv`
- 45 domains carried in the current hosted report snapshot
- 13 later CSV additions not yet folded into the hosted report text
- 40 REST-collected WordPress sites in the bundled article-match sample snapshot
- 21 Apache Cluster B sites in the report snapshot
- 19 LiteSpeed-side sites in the report snapshot
- 3 search-indexed expansion additions in the report snapshot
- 2 unavailable end-note domains in the report snapshot
- 9 reverse-WHOIS registration batches supplied during collection

## Attribution Boundary

This package is a data companion to the full report. The report supports operational clustering, not strategic attribution. It does not assess the Repost Today sites as John Mark Dougan-run.

## Data Format

The domain CSV is intentionally minimal:

```csv
domain
example.com
```

This makes it easy to feed into enrichment, DNS, screenshotting, or WordPress REST collection scripts.

## Tools

The included Python tool can reproduce exact-match article overlap checks from public WordPress REST data:

```bash
cd tools
python3 find_wordpress_article_matches.py \
  --no-default-domains \
  --domains-file ../data/repost_today_sites.csv \
  --out-dir ../matches
```

See [tools/README.md](tools/README.md) for outputs and options.

## Sample Data

The `sample-data/article-matches/` folder contains exact-match outputs from a WordPress REST collection snapshot:

- `summary.json`
- exact title, body, title+body, and slug match groups
- exact title, body, title+body, and slug match pairs

The top-level `sample-data/` folder also contains:

- `rewrite_detected.csv`, a manually curated AI/rewrite artifact detection CSV with article links, archive links, matched terms, artifact status, artifact reason, and snippets

These files are the compact evidence outputs; the raw `articles.jsonl` cache is not included because of size.
