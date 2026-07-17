from __future__ import annotations

import argparse
import csv
import json
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


BASE_URL = "https://www.givemeoc.com/"
DEFAULT_CSV = Path("data/givemeoc_apply_links.csv")
DEFAULT_JSON = Path("data/givemeoc_apply_links.json")
FIELDS = [
    "source_id",
    "page",
    "company",
    "company_type",
    "industry",
    "recruitment_type",
    "target_candidates",
    "location",
    "position",
    "status",
    "updated_at",
    "deadline",
    "apply_url",
    "notice_url",
]


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)

    def text(self) -> str:
        chunks = list(self.text_parts)
        for child in self.children:
            chunks.append(child.text())
        return normalize_text(" ".join(chunks))

    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())


class TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag=tag, attrs={key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.stack[-1].text_parts.append(data)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_html(html: str) -> Node:
    parser = TreeParser()
    parser.feed(html)
    return parser.root


def walk(node: Node) -> Iterable[Node]:
    yield node
    for child in node.children:
        yield from walk(child)


def has_class(node: Node, class_name: str) -> bool:
    return class_name in node.classes()


def find_by_class(node: Node, class_name: str) -> list[Node]:
    return [child for child in walk(node) if has_class(child, class_name)]


def first_by_class(node: Node, class_name: str) -> Node | None:
    matches = find_by_class(node, class_name)
    return matches[0] if matches else None


def extract_max_page(html: str) -> int:
    pages = [1]
    for match in re.finditer(r"[?&]paged=(\d+)", html):
        pages.append(int(match.group(1)))
    return max(pages)


def extract_jobs(html: str, page: int, base_url: str = BASE_URL) -> list[dict[str, str | int]]:
    root = parse_html(html)
    jobs = []

    for row in walk(root):
        if row.tag != "tr" or "data-id" not in row.attrs:
            continue

        company_cells = find_by_class(row, "crt-col-company")
        apply_link = first_link(find_by_class(row, "crt-col-links"))
        notice_link = first_link(find_by_class(row, "crt-col-notice"))

        jobs.append(
            {
                "source_id": row.attrs.get("data-id", ""),
                "page": page,
                "company": node_text_at(company_cells, 0),
                "company_type": class_text(row, "crt-col-type"),
                "industry": node_text_at(company_cells, 1),
                "recruitment_type": class_text(row, "crt-col-recruitment-type"),
                "target_candidates": class_text(row, "crt-col-target"),
                "location": class_text(row, "crt-col-location"),
                "position": class_text(row, "crt-col-position"),
                "status": class_text(row, "crt-col-status"),
                "updated_at": class_text(row, "crt-col-update-time"),
                "deadline": class_text(row, "crt-col-deadline"),
                "apply_url": normalize_href(apply_link, base_url),
                "notice_url": normalize_href(notice_link, base_url),
            }
        )

    return [job for job in jobs if job["apply_url"]]


def node_text_at(nodes: list[Node], index: int) -> str:
    if index >= len(nodes):
        return ""
    return nodes[index].text()


def class_text(node: Node, class_name: str) -> str:
    match = first_by_class(node, class_name)
    return match.text() if match else ""


def first_link(nodes: list[Node]) -> str:
    for node in nodes:
        for child in walk(node):
            if child.tag == "a" and child.attrs.get("href"):
                return child.attrs["href"]
    return ""


def normalize_href(href: str, base_url: str) -> str:
    href = normalize_text(href)
    if not href:
        return ""
    try:
        parsed = urlsplit(href)
    except ValueError:
        return href
    if parsed.scheme in {"http", "https", "mailto"}:
        return href
    if href.startswith(("/", "?", "#")):
        return urljoin(base_url, href)
    return href


def dedupe_jobs(jobs: Iterable[dict[str, str | int]]) -> list[dict[str, str | int]]:
    seen = set()
    unique = []
    for job in jobs:
        key = (job.get("company", ""), job.get("apply_url", ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def fetch(url: str, timeout: int = 30) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; givemeoc-public-link-exporter/1.0)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_with_retries(url: str, retries: int, timeout: int) -> str:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return fetch(url, timeout=timeout)
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt < retries:
                time.sleep(1 + attempt)
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def scrape(max_pages: int | None, delay: float, retries: int, timeout: int) -> tuple[list[dict[str, str | int]], list[int]]:
    first_html = fetch_with_retries(BASE_URL, retries=retries, timeout=timeout)
    detected_pages = extract_max_page(first_html)
    page_count = min(max_pages, detected_pages) if max_pages else detected_pages

    all_jobs = extract_jobs(first_html, page=1)
    failed_pages = []

    for page in range(2, page_count + 1):
        url = f"{BASE_URL}?paged={page}"
        try:
            html = fetch_with_retries(url, retries=retries, timeout=timeout)
            all_jobs.extend(extract_jobs(html, page=page))
        except RuntimeError:
            failed_pages.append(page)
        time.sleep(delay)

    return dedupe_jobs(all_jobs), failed_pages


def write_csv(path: Path, jobs: list[dict[str, str | int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(jobs)


def write_json(path: Path, jobs: list[dict[str, str | int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export public GiveMeOC application links from paginated HTML.")
    parser.add_argument("--max-pages", type=int, help="Limit pages for a test run.")
    parser.add_argument("--delay", type=float, default=1.5, help="Seconds to wait between page requests.")
    parser.add_argument("--retries", type=int, default=2, help="Retries per page after a failed request.")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds.")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="CSV output path.")
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON, help="JSON output path.")
    args = parser.parse_args()

    jobs, failed_pages = scrape(args.max_pages, args.delay, args.retries, args.timeout)
    write_csv(args.csv, jobs)
    write_json(args.json, jobs)

    print(f"Exported {len(jobs)} unique application links.")
    print(f"CSV: {args.csv}")
    print(f"JSON: {args.json}")
    if failed_pages:
        print(f"Failed pages: {', '.join(str(page) for page in failed_pages)}")
    return 1 if failed_pages else 0


if __name__ == "__main__":
    raise SystemExit(main())
