#!/usr/bin/env python3
"""
Pull public WordPress articles and find 1=1 matches across sites.

By default this uses the Repost Today seed domains from the public domain list.
You can add more candidate domains with --domains-file or --domain. The script
fetches posts through the public WordPress REST API, writes a JSONL cache, then
produces CSV reports for exact body, title+body, title, and slug overlaps.

Examples:
  python3 find_wordpress_article_matches.py
  python3 find_wordpress_article_matches.py --max-posts 500 --out-dir matches_500
  python3 find_wordpress_article_matches.py --domains-file ../data/repost_today_sites.csv
  python3 find_wordpress_article_matches.py --no-default-domains --domains-file candidates.txt
  python3 find_wordpress_article_matches.py --from-json matches/articles.jsonl
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
from html.parser import HTMLParser
import json
import re
import ssl
import sys
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


DEFAULT_DOMAINS = [
    "hilldaily.com",
    "hypernewsnow.com",
    "unitedrightamerica.com",
    "civilvoicepress.com",
    "allstatesnews.com",
    "truenorthconservative.com",
    "allsidesreport.com",
    "breakingdesk.com",
    "indyupdate.com",
    "guardiansoftradition.com",
    "roguenewsusa.com",
    "northernnotices.com",
    "maineupdate.com",
    "summitupdate.us",
    "eaglechronicle.us",
    "noonreport.us",
    "streamstates.com",
    "boldlyconservative.com",
    "metrocurrent.com",
    "nevadainsight.com",
    "24hourupdate.us",
    "quickwire.us",
    "republicreport.us",
    "swiftupdate.us",
    "centralbulletin.us",
    "civicjournal.us",
    "starherald.us",
    "libertygazette.us",
    "livechronicle.us",
    "realitywire.us",
    "dailysurge.us",
    "actionreport.us",
    "morningrecord.us",
    "peoplereport.us",
    "unionherald.us",
    "truechronicle.us",
    "horizonpress.us",
    "pulsereport.us",
    "alertdesk.us",
    "newssprint.us",
    "starsandstripesnews.us",
    "solidnews.us",
    "infostreamnow.us",
    "theconstitutionalview.com",
    "desmoineswire.com",
]

DEFAULT_DOMAIN_SET = set(DEFAULT_DOMAINS)

POST_FIELDS = [
    "id",
    "date",
    "date_gmt",
    "modified",
    "modified_gmt",
    "link",
    "slug",
    "title",
    "content",
    "excerpt",
    "author",
    "categories",
]

USER_AGENT = (
    "Mozilla/5.0 (compatible; WPArticleMatchFinder/1.0; "
    "+https://example.invalid/research)"
)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.skip_depth += 1
        elif tag in {"p", "br", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.skip_depth:
            self.skip_depth -= 1
        elif tag in {"p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        return " ".join(self.parts)


@dataclass(frozen=True)
class Article:
    domain: str
    post_id: str
    date_gmt: str
    modified_gmt: str
    link: str
    slug: str
    title: str
    excerpt: str
    body: str
    title_key: str
    body_key: str
    title_body_key: str
    slug_key: str
    body_hash: str
    title_body_hash: str
    title_hash: str
    source_kind: str

    @classmethod
    def from_wp_post(cls, domain: str, post: dict[str, Any]) -> "Article":
        title = rendered_text(post.get("title"))
        body = rendered_text(post.get("content"))
        excerpt = rendered_text(post.get("excerpt"))
        slug = str(post.get("slug") or "")
        title_key = canonical_text(title)
        body_key = canonical_text(body)
        title_body_key = f"{title_key}\n{body_key}".strip()
        slug_key = canonical_slug(slug)
        return cls(
            domain=domain,
            post_id=str(post.get("id") or ""),
            date_gmt=str(post.get("date_gmt") or post.get("date") or ""),
            modified_gmt=str(post.get("modified_gmt") or post.get("modified") or ""),
            link=str(post.get("link") or ""),
            slug=slug,
            title=title,
            excerpt=excerpt,
            body=body,
            title_key=title_key,
            body_key=body_key,
            title_body_key=title_body_key,
            slug_key=slug_key,
            body_hash=sha256_text(body_key),
            title_body_hash=sha256_text(title_body_key),
            title_hash=sha256_text(title_key),
            source_kind="wp-rest",
        )

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Article":
        values = {field.name: data.get(field.name, "") for field in cls.__dataclass_fields__.values()}
        return cls(**values)

    def to_json(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "post_id": self.post_id,
            "date_gmt": self.date_gmt,
            "modified_gmt": self.modified_gmt,
            "link": self.link,
            "slug": self.slug,
            "title": self.title,
            "excerpt": self.excerpt,
            "body": self.body,
            "title_key": self.title_key,
            "body_key": self.body_key,
            "title_body_key": self.title_body_key,
            "slug_key": self.slug_key,
            "body_hash": self.body_hash,
            "title_body_hash": self.title_body_hash,
            "title_hash": self.title_hash,
            "source_kind": self.source_kind,
        }


def rendered_text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("rendered", "")
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    parser = _HTMLTextExtractor()
    try:
        parser.feed(text)
        text = parser.text()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", text)
    return compact_whitespace(html.unescape(text))


def compact_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def canonical_text(text: str) -> str:
    """Canonical form for 1=1 matching after HTML/entity/spacing cleanup."""
    text = html.unescape(text or "")
    text = unicodedata.normalize("NFKC", text)
    text = text.casefold()
    text = text.replace("'", "")
    text = text.replace("`", "")
    text = text.replace("’", "")
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^0-9a-z]+", " ", text)
    return compact_whitespace(text)


def canonical_slug(slug: str) -> str:
    slug = unicodedata.normalize("NFKC", slug or "").casefold()
    slug = re.sub(r"[^0-9a-z]+", "-", slug)
    return slug.strip("-")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_domain(raw: str) -> str | None:
    raw = raw.strip()
    if not raw or raw.startswith("#"):
        return None
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    domain = (parsed.netloc or parsed.path).split("/")[0].strip().lower()
    domain = domain.split("@")[-1].split(":")[0]
    if domain.startswith("www."):
        domain = domain[4:]
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", domain):
        return None
    return domain


def extract_domains_from_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")

    path_tokens = re.findall(r"\\path\{([^}]+)\}", text)
    if path_tokens:
        return unique_domains([token for token in path_tokens if "@" not in token])

    candidates: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        direct = normalize_domain(stripped)
        if direct:
            candidates.append(direct)
    candidates.extend(
        match.group(1).lower()
        for match in re.finditer(r"(?<!@)\b(?:https?://)?(?:www\.)?([a-z0-9.-]+\.[a-z]{2,})\b", text, re.I)
    )
    return unique_domains(candidates)


def unique_domains(domains: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in domains:
        domain = normalize_domain(raw)
        if domain and domain not in seen:
            seen.add(domain)
            result.append(domain)
    return result


def fetch_json(url: str, timeout: float, retries: int, ssl_context: ssl.SSLContext | None) -> tuple[Any, dict[str, str]]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urlopen(request, timeout=timeout, context=ssl_context) as response:
                headers = {key.lower(): value for key, value in response.headers.items()}
                payload = response.read()
                return json.loads(payload.decode("utf-8", errors="replace")), headers
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(str(last_error))


def fetch_posts_for_domain(
    domain: str,
    *,
    max_posts: int,
    per_page: int,
    timeout: float,
    retries: int,
    delay: float,
    insecure_tls: bool,
) -> list[Article]:
    articles: list[Article] = []
    base_urls = [
        f"http://{domain}",
        f"https://{domain}",
        f"https://www.{domain}",
        f"http://www.{domain}",
    ]
    last_error = ""
    ssl_context = ssl._create_unverified_context() if insecure_tls else None

    for base_url in base_urls:
        page = 1
        while len(articles) < max_posts:
            limit = min(per_page, max_posts - len(articles))
            query = urlencode(
                {
                    "per_page": limit,
                    "page": page,
                    "_fields": ",".join(POST_FIELDS),
                    "orderby": "date",
                    "order": "desc",
                }
            )
            url = f"{base_url}/wp-json/wp/v2/posts?{query}"
            try:
                payload, headers = fetch_json(url, timeout=timeout, retries=retries, ssl_context=ssl_context)
            except RuntimeError as exc:
                last_error = str(exc)
                if page == 1:
                    break
                print(f"[warn] {domain}: stopped at page {page}: {exc}", file=sys.stderr)
                return articles

            if not isinstance(payload, list):
                last_error = f"unexpected REST payload: {type(payload).__name__}"
                break
            if not payload:
                return articles

            for post in payload:
                if isinstance(post, dict):
                    articles.append(Article.from_wp_post(domain, post))

            total_pages = int(headers.get("x-wp-totalpages", "0") or "0")
            if total_pages and page >= total_pages:
                return articles
            if len(payload) < limit:
                return articles
            page += 1
            if delay:
                time.sleep(delay)

        if articles:
            return articles

    if last_error:
        print(f"[warn] {domain}: no posts fetched: {last_error}", file=sys.stderr)
    return articles


def write_jsonl(path: Path, articles: list[Article]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for article in articles:
            handle.write(json.dumps(article.to_json(), ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def read_jsonl(path: Path) -> list[Article]:
    articles: list[Article] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                articles.append(Article.from_json(json.loads(line)))
            except json.JSONDecodeError as exc:
                print(f"[warn] {path}:{line_number}: skipped bad JSON: {exc}", file=sys.stderr)
    return articles


def group_articles(
    articles: list[Article],
    key_attr: str,
    *,
    min_chars: int,
    include_same_domain: bool,
) -> dict[str, list[Article]]:
    groups: dict[str, list[Article]] = defaultdict(list)
    for article in articles:
        key = getattr(article, key_attr)
        if not key or len(key) < min_chars:
            continue
        groups[key].append(article)

    matched: dict[str, list[Article]] = {}
    for key, items in groups.items():
        distinct_domains = {item.domain for item in items}
        if len(items) < 2:
            continue
        if not include_same_domain and len(distinct_domains) < 2:
            continue
        matched[key] = sorted(items, key=lambda item: (item.domain, item.date_gmt, item.post_id))
    return matched


def short_preview(text: str, length: int = 180) -> str:
    text = compact_whitespace(text)
    if len(text) <= length:
        return text
    return text[: length - 1].rstrip() + "..."


def write_group_csv(path: Path, match_type: str, groups: dict[str, list[Article]]) -> None:
    rows: list[dict[str, Any]] = []
    for index, (key, items) in enumerate(sorted(groups.items(), key=lambda pair: (-len(pair[1]), pair[0])), start=1):
        domains = sorted({item.domain for item in items})
        rows.append(
            {
                "match_type": match_type,
                "group_id": f"{match_type}-{index:05d}",
                "article_count": len(items),
                "domain_count": len(domains),
                "domains": ";".join(domains),
                "key_hash": sha256_text(key),
                "sample_title": items[0].title,
                "sample_preview": short_preview(items[0].body or items[0].excerpt or items[0].title),
                "urls": ";".join(item.link for item in items),
            }
        )
    write_csv(path, rows)


def write_pair_csv(path: Path, match_type: str, groups: dict[str, list[Article]]) -> None:
    rows: list[dict[str, Any]] = []
    for index, (key, items) in enumerate(sorted(groups.items(), key=lambda pair: (-len(pair[1]), pair[0])), start=1):
        group_id = f"{match_type}-{index:05d}"
        for left, right in combinations(items, 2):
            if left.domain == right.domain:
                continue
            rows.append(
                {
                    "match_type": match_type,
                    "group_id": group_id,
                    "key_hash": sha256_text(key),
                    "domain_a": left.domain,
                    "date_a": left.date_gmt,
                    "title_a": left.title,
                    "url_a": left.link,
                    "domain_b": right.domain,
                    "date_b": right.date_gmt,
                    "title_b": right.title,
                    "url_b": right.link,
                    "body_chars_a": len(left.body),
                    "body_chars_b": len(right.body),
                }
            )
    write_csv(path, rows)


def write_new_domain_hits_csv(path: Path, all_groups: dict[str, dict[str, list[Article]]]) -> None:
    rows: list[dict[str, Any]] = []
    for match_type, groups in all_groups.items():
        for key, items in groups.items():
            seeds = [item for item in items if item.domain in DEFAULT_DOMAIN_SET]
            candidates = [item for item in items if item.domain not in DEFAULT_DOMAIN_SET]
            if not seeds or not candidates:
                continue
            for candidate in candidates:
                for seed in seeds:
                    rows.append(
                        {
                            "candidate_domain": candidate.domain,
                            "match_type": match_type,
                            "key_hash": sha256_text(key),
                            "seed_domain": seed.domain,
                            "candidate_title": candidate.title,
                            "seed_title": seed.title,
                            "candidate_url": candidate.link,
                            "seed_url": seed.link,
                            "candidate_date_gmt": candidate.date_gmt,
                            "seed_date_gmt": seed.date_gmt,
                        }
                    )
    write_csv(path, rows)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if rows:
        fieldnames = list(rows[0].keys())
    else:
        fieldnames = ["empty"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, articles: list[Article], groups_by_type: dict[str, dict[str, list[Article]]]) -> None:
    by_domain: dict[str, int] = defaultdict(int)
    for article in articles:
        by_domain[article.domain] += 1

    summary = {
        "articles_total": len(articles),
        "domains_total": len(by_domain),
        "articles_by_domain": dict(sorted(by_domain.items())),
        "match_groups": {
            match_type: {
                "groups": len(groups),
                "article_memberships": sum(len(items) for items in groups.values()),
                "domains": sorted({article.domain for items in groups.values() for article in items}),
            }
            for match_type, groups in groups_by_type.items()
        },
    }
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch public WordPress posts and find exact 1=1 article matches across domains."
    )
    parser.add_argument(
        "--domain",
        action="append",
        default=[],
        help="Add one domain to fetch. Can be repeated.",
    )
    parser.add_argument(
        "--domains-file",
        action="append",
        default=[],
        type=Path,
        help="Text/CSV/LaTeX file containing domains or URLs to add.",
    )
    parser.add_argument(
        "--no-default-domains",
        action="store_true",
        help="Do not include the built-in Repost Today seed domains.",
    )
    parser.add_argument(
        "--max-posts",
        type=int,
        default=1000,
        help="Maximum posts to fetch per domain. Default: 1000.",
    )
    parser.add_argument(
        "--per-page",
        type=int,
        default=100,
        help="WordPress REST page size. WordPress usually caps this at 100. Default: 100.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="HTTP timeout in seconds. Default: 20.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="HTTP retries per page. Default: 2.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.2,
        help="Delay between REST pages for the same domain. Default: 0.2 seconds.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("wp_article_matches"),
        help="Directory for articles JSONL and CSV reports. Default: wp_article_matches.",
    )
    parser.add_argument(
        "--from-json",
        type=Path,
        help="Analyze an existing articles JSONL file instead of fetching.",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification for sites with broken chains. Use only for OSINT collection.",
    )
    parser.add_argument(
        "--include-same-domain",
        action="store_true",
        help="Include duplicate matches that occur only within one domain.",
    )
    parser.add_argument(
        "--min-body-chars",
        type=int,
        default=250,
        help="Minimum canonical body length for exact body matching. Default: 250.",
    )
    parser.add_argument(
        "--min-title-chars",
        type=int,
        default=18,
        help="Minimum canonical title length for exact title matching. Default: 18.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.from_json:
        articles = read_jsonl(args.from_json)
        print(f"[info] loaded {len(articles)} articles from {args.from_json}")
    else:
        domains: list[str] = []
        if not args.no_default_domains:
            domains.extend(DEFAULT_DOMAINS)
        domains.extend(args.domain)
        for domains_file in args.domains_file:
            if not domains_file.exists():
                print(f"[warn] missing domains file: {domains_file}", file=sys.stderr)
                continue
            domains.extend(extract_domains_from_file(domains_file))
        domains = unique_domains(domains)

        if not domains:
            parser.error("no domains to fetch; add --domain, --domains-file, or omit --no-default-domains")

        articles = []
        for index, domain in enumerate(domains, start=1):
            print(f"[info] {index}/{len(domains)} fetching {domain}", file=sys.stderr)
            fetched = fetch_posts_for_domain(
                domain,
                max_posts=max(1, args.max_posts),
                per_page=min(max(1, args.per_page), 100),
                timeout=args.timeout,
                retries=max(0, args.retries),
                delay=max(0.0, args.delay),
                insecure_tls=args.insecure,
            )
            print(f"[info] {domain}: {len(fetched)} posts", file=sys.stderr)
            articles.extend(fetched)

        articles_jsonl = args.out_dir / "articles.jsonl"
        write_jsonl(articles_jsonl, articles)
        print(f"[info] wrote {articles_jsonl}")

    groups_by_type = {
        "exact_title_body": group_articles(
            articles,
            "title_body_key",
            min_chars=args.min_title_chars + args.min_body_chars,
            include_same_domain=args.include_same_domain,
        ),
        "exact_body": group_articles(
            articles,
            "body_key",
            min_chars=args.min_body_chars,
            include_same_domain=args.include_same_domain,
        ),
        "exact_title": group_articles(
            articles,
            "title_key",
            min_chars=args.min_title_chars,
            include_same_domain=args.include_same_domain,
        ),
        "exact_slug": group_articles(
            articles,
            "slug_key",
            min_chars=args.min_title_chars,
            include_same_domain=args.include_same_domain,
        ),
    }

    for match_type, groups in groups_by_type.items():
        write_group_csv(args.out_dir / f"{match_type}_groups.csv", match_type, groups)
        write_pair_csv(args.out_dir / f"{match_type}_pairs.csv", match_type, groups)
        print(f"[info] {match_type}: {len(groups)} cross-domain groups")

    write_new_domain_hits_csv(args.out_dir / "new_domain_hits.csv", groups_by_type)
    write_summary(args.out_dir / "summary.json", articles, groups_by_type)
    print(f"[info] wrote reports to {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
