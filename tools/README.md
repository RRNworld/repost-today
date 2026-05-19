# Tools

This folder contains lightweight Python tooling used during Repost Today triage.

## `find_wordpress_article_matches.py`

Fetches public WordPress REST posts from a set of domains and looks for exact cross-domain overlaps.

It writes:

- `articles.jsonl` — normalized article cache from public `/wp-json/wp/v2/posts`
- `exact_title_groups.csv` and `exact_title_pairs.csv`
- `exact_body_groups.csv` and `exact_body_pairs.csv`
- `exact_title_body_groups.csv` and `exact_title_body_pairs.csv`
- `exact_slug_groups.csv` and `exact_slug_pairs.csv`
- `new_domain_hits.csv`
- `summary.json`

The matcher canonicalizes article text by stripping HTML, normalizing Unicode, lowercasing, removing punctuation, and compacting whitespace. It is intended for exact `1=1` matches after normalization, not fuzzy similarity.

## Usage

From this `tools/` directory:

```bash
python3 find_wordpress_article_matches.py \
  --no-default-domains \
  --domains-file ../data/repost_today_sites.csv \
  --out-dir ../matches
```

To reuse a cached collection without refetching:

```bash
python3 find_wordpress_article_matches.py \
  --from-json ../matches/articles.jsonl \
  --out-dir ../matches_reanalysis
```

Useful options:

- `--max-posts 500` limits collection per domain.
- `--delay 0.5` slows paging between WordPress REST requests.
- `--include-same-domain` includes duplicate matches that occur only within one site.
- `--insecure` disables TLS verification for OSINT collection against broken certificate chains.

## Notes

The script only uses public WordPress REST endpoints. Some domains may be unavailable, block REST, or return no posts at collection time; those collection gaps should be handled in analysis rather than written up as evidence by themselves.
