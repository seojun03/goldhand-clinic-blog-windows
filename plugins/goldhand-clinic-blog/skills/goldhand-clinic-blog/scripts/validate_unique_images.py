#!/usr/bin/env python3
"""Reject repeated source photos across an entire article, without network writes."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, unquote

SKILL_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_KEYS = {"w", "h", "width", "height", "q", "quality", "format", "fm", "fit", "crop", "auto", "timestamp", "cache", "cb"}


def canonical_url(value: str) -> str:
    url = urlsplit(value)
    if url.scheme not in {"https", "http"}:
        return value
    # Keep identity-bearing query values (e.g. id, file, path); discard only
    # known rendering/cache parameters. Different image IDs remain distinct.
    query = sorted((key, val) for key, val in parse_qsl(url.query, keep_blank_values=True)
                   if key.lower() not in TRANSFORM_KEYS and not key.lower().startswith("utm_")
                   and not (key.lower() == "type" and re.fullmatch(r"(?:w|f)\d+(?:_\d+)?", val)))
    return urlunsplit((url.scheme.lower(), url.netloc.lower(), unquote(url.path), urlencode(query), ""))


def file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        digest = hashlib.sha256()
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def asset_keys(asset: dict) -> set[str]:
    keys = set()
    for field, prefix in (("id", "id"), ("sha256", "sha"), ("url", "url")):
        value = str(asset.get(field, "")).strip()
        if value:
            keys.add(prefix + ":" + (canonical_url(value) if prefix == "url" else value.lower() if prefix == "sha" else value))
    relative = str(asset.get("bundledPath", ""))
    if relative:
        path = (SKILL_DIR / relative).resolve()
        if path.is_file():
            keys.add("sha:" + file_hash(path))
    return keys


class Images(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "img":
            self.images.append(dict(attrs))

    handle_startendtag = handle_starttag


def validate(raw: str, library: dict | None = None) -> dict:
    parser = Images()
    parser.feed(raw)
    if library is None:
        payload = json.loads((SKILL_DIR / "assets/media-library.json").read_text(encoding="utf-8"))
        library = {str(a["id"]): a for a in payload.get("assets", []) if isinstance(a, dict) and a.get("id")}
    seen, issues = {}, []
    for index, attrs in enumerate(parser.images, 1):
        keys = set()
        asset_id = attrs.get("data-goldhand-media", "")
        if asset_id:
            keys.add("id:" + asset_id)
            if asset_id in library:
                keys.update(asset_keys(library[asset_id]))
        for field in ("src", "data-reference-source-url", "data-image-origin"):
            value = attrs.get(field)
            if value:
                keys.add("url:" + canonical_url(value))
        if attrs.get("data-media-sha256"):
            keys.add("sha:" + attrs["data-media-sha256"].lower())
        if attrs.get("data-local-image"):
            path = Path(attrs["data-local-image"]).expanduser().resolve()
            keys.add("path:" + str(path))
            if path.is_file():
                keys.add("sha:" + file_hash(path))
        previous = sorted({seen[key] for key in keys if key in seen})
        if previous:
            issues.append({"severity": "error", "code": "duplicate-article-image",
                           "detail": f"사진 {index}은 이미 사용한 사진 {previous}과 원본 ID·주소 또는 내용 해시가 같습니다. 중복을 제거하고 한 번만 사용하세요."})
        for key in keys:
            seen.setdefault(key, index)
    return {"status": "fail" if issues else "pass", "issues": issues,
            "metrics": {"imageCount": len(parser.images), "duplicateCount": len(issues)}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = validate(args.input.read_text(encoding="utf-8"))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
