#!/usr/bin/env python3
"""Build a printable, concatenated edition of a slide-like MkDocs site.

The normal order is determined by following data-next attributes from index.md.
The resulting chain is cross-checked against mkdocs.yml, and inconsistencies are
reported. Interactive Kobo forms and iframes are replaced by printable notices.

Outputs:
  combined_print.md    Editable concatenated Markdown
  combined_print.html  Standalone print-friendly HTML (when mistune is installed)
  assets/              Local images and other linked files used by the pages
  build_report.txt     Navigation/order/missing-file diagnostics

Typical usage:
  python build_printable_markdown_site.py /path/to/repository
  python build_printable_markdown_site.py . --output print_build
  python build_printable_markdown_site.py . --include-orphans

Optional packages:
  pip install pyyaml mistune
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable
from urllib.parse import unquote, urlparse

SLIDE_CONFIG_RE = re.compile(
    r"<div\b[^>]*\bid=[\"']slide-config[\"'][^>]*>\s*</div>",
    re.IGNORECASE | re.DOTALL,
)
ATTR_RE = re.compile(r"([:\w-]+)\s*=\s*([\"'])(.*?)\2", re.DOTALL)
IFRAME_RE = re.compile(r"<iframe\b.*?</iframe>", re.IGNORECASE | re.DOTALL)
IFRAME_SRC_RE = re.compile(r"\bsrc\s*=\s*([\"'])(.*?)\1", re.IGNORECASE | re.DOTALL)
MD_IMAGE_RE = re.compile(r"(!\[[^\]]*\]\()([^\s)]+)([^)]*\))")
HTML_IMAGE_RE = re.compile(r"(<img\b[^>]*?\bsrc\s*=\s*['\"])([^'\"]+)(['\"])", re.IGNORECASE)
MD_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")


@dataclass
class PageInfo:
    path: Path
    attrs: dict[str, str]
    next_path: Path | None


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def parse_attrs(tag: str) -> dict[str, str]:
    return {m.group(1).lower(): html.unescape(m.group(3).strip()) for m in ATTR_RE.finditer(tag)}


def find_slide_config(text: str) -> tuple[str | None, dict[str, str]]:
    match = SLIDE_CONFIG_RE.search(text)
    if not match:
        return None, {}
    tag = match.group(0)
    return tag, parse_attrs(tag)


def resolve_next(current: Path, raw_next: str | None, docs_dir: Path) -> Path | None:
    if not raw_next:
        return None
    value = unquote(raw_next.strip())
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return None
    value = parsed.path.rstrip("/")
    if not value:
        return None

    # data-next URLs describe the generated site, where ../name/ maps to docs/name.md.
    bits = [part for part in PurePosixPath(value).parts if part not in (".", "..", "/")]
    if not bits:
        return None
    candidate = docs_dir.joinpath(*bits)
    if candidate.suffix.lower() != ".md":
        candidate = candidate.with_suffix(".md")
    return candidate.resolve()


def follow_chain(start: Path, docs_dir: Path) -> tuple[list[PageInfo], list[str]]:
    chain: list[PageInfo] = []
    warnings: list[str] = []
    seen: set[Path] = set()
    current = start.resolve()

    while True:
        if current in seen:
            warnings.append(f"Navigation loop detected at: {current.relative_to(docs_dir)}")
            break
        if not current.exists():
            warnings.append(f"Missing page in data-next chain: {current}")
            break
        seen.add(current)
        text = read_text(current)
        _tag, attrs = find_slide_config(text)
        next_path = resolve_next(current, attrs.get("data-next"), docs_dir)
        chain.append(PageInfo(current, attrs, next_path))
        if next_path is None:
            break
        current = next_path

    return chain, warnings


def flatten_nav(node: object) -> list[str]:
    results: list[str] = []
    if isinstance(node, str):
        if node.lower().endswith(".md"):
            results.append(node)
    elif isinstance(node, list):
        for item in node:
            results.extend(flatten_nav(item))
    elif isinstance(node, dict):
        for value in node.values():
            results.extend(flatten_nav(value))
    return results


def read_mkdocs_nav(mkdocs_path: Path) -> tuple[list[Path], str | None]:
    if not mkdocs_path.exists():
        return [], "mkdocs.yml not found"
    try:
        import yaml  # type: ignore
    except ImportError:
        return [], "PyYAML not installed; mkdocs.yml cross-check skipped"
    try:
        data = yaml.safe_load(read_text(mkdocs_path)) or {}
        names = flatten_nav(data.get("nav", []))
        return [(mkdocs_path.parent / "docs" / name).resolve() for name in names], None
    except Exception as exc:
        return [], f"Could not parse mkdocs.yml: {exc}"


def title_from_markdown(text: str, fallback: str) -> str:
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return re.sub(r"[*_`]+", "", match.group(1)).strip()
    return fallback


def local_target(raw: str) -> str | None:
    value = html.unescape(raw.strip().strip("<>"))
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or value.startswith(("#", "data:", "mailto:")):
        return None
    return unquote(parsed.path)


def copy_asset(raw: str, source_page: Path, docs_dir: Path, assets_dir: Path, warnings: list[str]) -> str:
    local = local_target(raw)
    if local is None:
        return raw
    source = (source_page.parent / local).resolve()
    try:
        relative = source.relative_to(docs_dir.resolve())
    except ValueError:
        warnings.append(f"Asset outside docs directory left unchanged: {raw} (in {source_page.name})")
        return raw
    if not source.exists() or not source.is_file():
        warnings.append(f"Missing local asset: {relative} (referenced by {source_page.name})")
        return raw
    destination = assets_dir / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return (Path("assets") / relative).as_posix()


def rewrite_assets(text: str, source_page: Path, docs_dir: Path, assets_dir: Path, warnings: list[str]) -> str:
    def md_image(match: re.Match[str]) -> str:
        new = copy_asset(match.group(2), source_page, docs_dir, assets_dir, warnings)
        return match.group(1) + new + match.group(3)

    def html_image(match: re.Match[str]) -> str:
        new = copy_asset(match.group(2), source_page, docs_dir, assets_dir, warnings)
        return match.group(1) + new + match.group(3)

    return HTML_IMAGE_RE.sub(html_image, MD_IMAGE_RE.sub(md_image, text))


def iframe_notice(match: re.Match[str]) -> str:
    iframe = match.group(0)
    src_match = IFRAME_SRC_RE.search(iframe)
    if src_match:
        url = html.unescape(src_match.group(2).strip())
        return (
            '\n<div class="interactive-placeholder">\n'
            '<strong>Interactive embedded content</strong><br>\n'
            f'This printable edition cannot reproduce the interactive dashboard.<br>\n'
            f'<a href="{html.escape(url, quote=True)}">{html.escape(url)}</a>\n'
            '</div>\n'
        )
    return '\n<div class="interactive-placeholder"><strong>Interactive embedded content omitted from print.</strong></div>\n'


def replace_slide_config(text: str, attrs: dict[str, str]) -> str:
    kind = attrs.get("data-type", "unknown").lower()
    kobo_id = attrs.get("data-kobo-id")
    if kind in {"kobo", "start"}:
        details = ["Interactive form omitted from printable edition."]
        if kobo_id:
            details.append(f"Kobo form ID: <code>{html.escape(kobo_id)}</code>")
        replacement = (
            '\n<div class="interactive-placeholder kobo-placeholder">'
            '<strong>Interactive response form</strong><br>' + "<br>".join(details) + '</div>\n'
        )
    else:
        replacement = "\n"
    return SLIDE_CONFIG_RE.sub(replacement, text, count=1)


def prepare_page(text: str, page: PageInfo, docs_dir: Path, assets_dir: Path, warnings: list[str]) -> str:
    text = replace_slide_config(text, page.attrs)
    text = IFRAME_RE.sub(iframe_notice, text)
    text = rewrite_assets(text, page.path, docs_dir, assets_dir, warnings)
    return text.strip()


def build_markdown(pages: list[PageInfo], docs_dir: Path, assets_dir: Path, warnings: list[str], site_title: str) -> str:
    sections = [
        f"# {site_title}: Printable Edition",
        "",
        "*Generated by following the repository's `data-next` navigation chain.*",
        "",
    ]
    total = len(pages)
    for number, page in enumerate(pages, start=1):
        raw = read_text(page.path)
        title = title_from_markdown(raw, page.path.stem)
        body = prepare_page(raw, page, docs_dir, assets_dir, warnings)
        sections.extend([
            '<div class="source-page">',
            f'<div class="page-meta">Page {number} of {total} · Source: <code>{html.escape(page.path.relative_to(docs_dir).as_posix())}</code></div>',
            "",
            body,
            "",
            '</div>',
        ])
        if number != total:
            sections.extend(["", '<div class="page-break"></div>', ""])
    return "\n".join(sections).rstrip() + "\n"


def markdown_to_html(markdown_text: str, title: str) -> str | None:
    try:
        import mistune  # type: ignore
    except ImportError:
        return None
    renderer = mistune.create_markdown(renderer=mistune.HTMLRenderer(escape=False), plugins=["table", "strikethrough", "task_lists", "url"])
    body = renderer(markdown_text)
    css = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { max-width: 8.1in; margin: 0 auto; padding: 0.35in; color: #111; background: white;
       font-family: Arial, Helvetica, sans-serif; font-size: 11pt; line-height: 1.38; }
h1 { font-size: 24pt; margin: 0.2em 0 0.45em; }
h2 { font-size: 17pt; margin-top: 1em; }
h3 { font-size: 13pt; }
img { display: block; max-width: 100%; max-height: 8.1in; height: auto; margin: 0.18in auto; object-fit: contain; }
table { width: 100%; border-collapse: collapse; margin: 0.18in 0; }
th, td { border: 1px solid #777; padding: 0.06in; text-align: left; vertical-align: top; }
a { color: #0645ad; overflow-wrap: anywhere; }
pre, code { font-family: Menlo, Consolas, monospace; font-size: 9.5pt; }
.page-meta { margin-bottom: 0.18in; padding-bottom: 0.06in; border-bottom: 1px solid #bbb; color: #666; font-size: 8.5pt; }
.interactive-placeholder { border: 2px dashed #888; padding: 0.16in; margin: 0.2in 0; background: #f5f5f5; }
.page-break { break-after: page; page-break-after: always; height: 0; }
.source-page { break-inside: auto; }
@page { size: auto; margin: 0.55in; }
@media print {
  body { max-width: none; margin: 0; padding: 0; font-size: 10.5pt; }
  a { color: black; text-decoration: none; }
  .source-page { break-before: page; page-break-before: always; }
  .source-page:first-of-type { break-before: auto; page-break-before: auto; }
  .page-break { display: block; }
  h1, h2, h3, img, table, .interactive-placeholder { break-inside: avoid; page-break-inside: avoid; }
}
"""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{css}</style>
</head>
<body>
{body}
</body>
</html>
"""


def compare_orders(chain: list[Path], nav: list[Path], docs_dir: Path) -> list[str]:
    messages: list[str] = []
    chain_set, nav_set = set(chain), set(nav)
    only_chain = [p for p in chain if p not in nav_set]
    only_nav = [p for p in nav if p not in chain_set]
    if only_chain:
        messages.append("Pages in data-next chain but not mkdocs nav: " + ", ".join(p.relative_to(docs_dir).as_posix() for p in only_chain))
    if only_nav:
        messages.append("Pages in mkdocs nav but not data-next chain: " + ", ".join(p.relative_to(docs_dir).as_posix() for p in only_nav))
    common_chain = [p for p in chain if p in nav_set]
    common_nav = [p for p in nav if p in chain_set]
    if common_chain != common_nav:
        messages.append("The shared pages appear in a different order in data-next and mkdocs nav.")
    if not messages:
        messages.append("data-next chain and mkdocs nav agree.")
    return messages


def site_name_from_mkdocs(path: Path) -> str:
    if not path.exists():
        return path.parent.name
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(read_text(path)) or {}
        return str(data.get("site_name") or path.parent.name)
    except Exception:
        return path.parent.name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repository", nargs="?", default=".", help="MkDocs repository root (default: current directory)")
    parser.add_argument("--docs-dir", default="docs", help="Docs directory relative to repository (default: docs)")
    parser.add_argument("--start", default="index.md", help="Starting Markdown page relative to docs directory")
    parser.add_argument("--output", default="print_build", help="Output directory relative to repository, or absolute path")
    parser.add_argument("--include-orphans", action="store_true", help="Append Markdown files not reachable from index.md")
    args = parser.parse_args()

    repo = Path(args.repository).expanduser().resolve()
    docs_dir = (repo / args.docs_dir).resolve()
    start = (docs_dir / args.start).resolve()
    output = Path(args.output).expanduser()
    if not output.is_absolute():
        output = repo / output
    output = output.resolve()
    assets_dir = output / "assets"

    if not docs_dir.is_dir():
        print(f"ERROR: docs directory not found: {docs_dir}", file=sys.stderr)
        return 2
    if not start.is_file():
        print(f"ERROR: start page not found: {start}", file=sys.stderr)
        return 2

    if output.exists():
        shutil.rmtree(output)
    assets_dir.mkdir(parents=True, exist_ok=True)

    pages, warnings = follow_chain(start, docs_dir)
    chain_paths = [p.path for p in pages]
    all_md = sorted(p.resolve() for p in docs_dir.rglob("*.md"))
    orphans = [p for p in all_md if p not in set(chain_paths)]

    if args.include_orphans:
        pages.extend(PageInfo(path=p, attrs=find_slide_config(read_text(p))[1], next_path=None) for p in orphans)

    mkdocs_path = repo / "mkdocs.yml"
    nav_paths, nav_error = read_mkdocs_nav(mkdocs_path)
    report: list[str] = []
    report.append(f"Repository: {repo}")
    report.append(f"Start page: {start.relative_to(docs_dir)}")
    report.append(f"Pages followed: {len(chain_paths)}")
    report.append("")
    report.append("DATA-NEXT ORDER")
    report.extend(f"{i:02d}. {p.relative_to(docs_dir).as_posix()}" for i, p in enumerate(chain_paths, 1))
    report.append("")
    report.append("MKDOCS CROSS-CHECK")
    if nav_error:
        report.append(nav_error)
    else:
        report.extend(compare_orders(chain_paths, nav_paths, docs_dir))
    report.append("")
    report.append("UNREACHABLE MARKDOWN FILES")
    if orphans:
        report.extend(p.relative_to(docs_dir).as_posix() for p in orphans)
    else:
        report.append("None")

    site_title = site_name_from_mkdocs(mkdocs_path)
    combined_md = build_markdown(pages, docs_dir, assets_dir, warnings, site_title)
    md_path = output / "combined_print.md"
    md_path.write_text(combined_md, encoding="utf-8")

    html_text = markdown_to_html(combined_md, f"{site_title}: Printable Edition")
    html_path = output / "combined_print.html"
    if html_text is not None:
        html_path.write_text(html_text, encoding="utf-8")
    else:
        warnings.append("mistune is not installed; combined_print.html was not generated")

    report.append("")
    report.append("WARNINGS")
    report.extend(warnings or ["None"])
    report.append("")
    report.append("OUTPUTS")
    report.append(str(md_path))
    if html_text is not None:
        report.append(str(html_path))
    report_path = output / "build_report.txt"
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"Created: {md_path}")
    if html_text is not None:
        print(f"Created: {html_path}")
    print(f"Created: {report_path}")
    if orphans:
        print("Unreachable Markdown files: " + ", ".join(p.relative_to(docs_dir).as_posix() for p in orphans))
    if warnings:
        print(f"Warnings: {len(warnings)} (see build_report.txt)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
