# Sample Data

This folder contains lightweight article-match outputs used as supporting evidence for the Repost Today report.

## `article-matches/`

Generated with `tools/find_wordpress_article_matches.py` from public WordPress REST posts. The files are exact-match outputs after text normalization, not fuzzy similarity results.

Included:

- `summary.json` — run-level counts by domain and match type
- `exact_title_groups.csv` / `exact_title_pairs.csv`
- `exact_body_groups.csv` / `exact_body_pairs.csv`
- `exact_title_body_groups.csv` / `exact_title_body_pairs.csv`
- `exact_slug_groups.csv` / `exact_slug_pairs.csv`
- `new_domain_hits.csv`

Not included:

- `articles.jsonl`, the raw normalized article cache, because it is large. It can be regenerated with the included tool.

## AI Detection

- `rewrite_detected.csv` — manually curated AI/rewrite artifact detections, including article links, archive links, matched terms, artifact status, artifact reason, and supporting snippets.

## Reproduce

From the repository root:

```bash
cd tools
python3 find_wordpress_article_matches.py \
  --no-default-domains \
  --domains-file ../data/repost_today_sites.csv \
  --out-dir ../matches
```

The sample data is a collection snapshot. Some sites may become unavailable or return different post totals over time.
