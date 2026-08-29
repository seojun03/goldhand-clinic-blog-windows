#!/usr/bin/env python3
"""Recommend approved Goldhand clinical photos for numbered answer sections.

This selector runs only after the user approves the plain text and separately
requests images. It never creates an introduction, credential, closing, or CTA
photo block. Every selected photo is placed inside a numbered answer section.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY = SKILL_DIR / "assets" / "media-library.json"
TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣][0-9A-Za-z가-힣+·._-]{1,}")
STOPWORDS = {
    "광주", "금손한의원", "한의원", "병원", "클리닉", "관련", "대한", "위한",
    "하는", "있는", "없는", "방법", "이유", "기준", "정보", "블로그", "환자",
    "박준희", "원장", "진료", "치료", "상담", "검사", "장면",
}
FORBIDDEN_DESCRIPTOR = re.compile(
    r"(?:로고|logo|건물\s*외관|건물\s*외부|환제|제품\s*포장|장비|원내\s*공간)",
    re.I,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def load_json(path: Path, *, required: bool = False) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 최상위는 객체여야 합니다: {path}")
    return value


def tokens(value: str) -> set[str]:
    return {
        token.strip("._-")
        for token in TOKEN_RE.findall(value.lower())
        if len(token.strip("._-")) >= 2 and token.strip("._-") not in STOPWORDS
    }


def bundled_file(asset: dict[str, Any]) -> Path | None:
    raw = str(asset.get("bundledPath", "")).strip()
    if not raw:
        return None
    candidate = (SKILL_DIR / raw).resolve()
    try:
        candidate.relative_to(SKILL_DIR.resolve())
    except ValueError:
        return None
    return candidate


def is_safe_candidate(asset: dict[str, Any]) -> bool:
    descriptor = " ".join(str(asset.get(field, "")) for field in ("filename", "caption", "sceneType"))
    local_path = bundled_file(asset)
    return (
        asset.get("safeAuto") is True
        and asset.get("requiresReview") is False
        and asset.get("personInteraction") is True
        and asset.get("directorVisible") is True
        and str(asset.get("sceneType", "")).startswith("director-patient-")
        and FORBIDDEN_DESCRIPTOR.search(descriptor) is None
        and str(asset.get("url", "")).startswith("https://")
        and bool(str(asset.get("id", "")).strip())
        and bool(str(asset.get("sha256", "")).strip())
        and bool(str(asset.get("approvedAlt", "")).strip())
        and local_path is not None
        and local_path.is_file()
    )


def relevance(asset: dict[str, Any], query: set[str]) -> int:
    searchable = " ".join(
        [
            str(asset.get("sourceTitle", "")),
            str(asset.get("caption", "")),
            str(asset.get("context", "")),
            " ".join(str(term) for term in asset.get("placementTerms", [])),
        ]
    )
    return len(query & tokens(searchable))


def public_item(asset: dict[str, Any], score: int) -> dict[str, Any]:
    url = str(asset.get("url", ""))
    local_path = bundled_file(asset)
    return {
        "id": str(asset.get("id", "")),
        "score": score,
        "sceneType": str(asset.get("sceneType", "")),
        "approvedAlt": str(asset.get("approvedAlt", "")),
        "sha256": str(asset.get("sha256", "")),
        "sourcePostUrl": str(asset.get("sourcePostUrl", "")),
        "url": url,
        "bundledPath": str(asset.get("bundledPath", "")),
        "bundledFile": str(local_path) if local_path else "",
        "htmlAttributes": {
            "data-real-photo": "true",
            "data-goldhand-media": str(asset.get("id", "")),
            "data-media-sha256": str(asset.get("sha256", "")),
            "data-reference-source-url": url,
            "src": url,
            "referrerpolicy": "no-referrer",
            "alt": str(asset.get("approvedAlt", "")),
        },
        "figureAttributes": {
            "data-real-photo": "true",
            "data-real-photo-slot": "numbered-section",
            "data-image-placement": "numbered-section-body",
        },
    }


def recommend(
    library: dict[str, Any],
    *,
    topic: str,
    count: int,
) -> dict[str, Any]:
    if count < 1:
        raise ValueError("사진 수는 1 이상이어야 합니다.")
    query = tokens(topic)
    ranked: list[tuple[int, int, int, dict[str, Any]]] = []
    for raw in library.get("assets", []):
        if not isinstance(raw, dict) or not is_safe_candidate(raw):
            continue
        score = relevance(raw, query)
        if score < 1:
            continue
        ranked.append((score, int(raw.get("trustPriority", 0) or 0), -int(raw.get("postOrder", 0) or 0), raw))
    ranked.sort(key=lambda item: (item[0], item[1], item[2], str(item[3].get("id", ""))), reverse=True)
    selected = [public_item(item[3], item[0]) for item in ranked[:count]]
    return {
        "status": "complete" if len(selected) == count else "decision-required",
        "placement": "numbered-section-body",
        "requested": count,
        "selectedCount": len(selected),
        "missing": max(0, count - len(selected)),
        "policy": "평문 승인 뒤 사용자가 이미지를 요청한 경우에만, 주제와 맞는 승인 진료 사진을 번호 소제목 설명 안에 배치합니다.",
        "selected": selected,
    }


def main() -> int:
    args = parse_args()
    try:
        library = load_json(args.library, required=True)
        result = recommend(
            library,
            topic=args.topic,
            count=args.count,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"미디어 추천 실패: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status: {result['status']} ({result['selectedCount']}/{result['requested']})")
        for item in result["selected"]:
            print(f"{item['id']}\t{item['approvedAlt']}\t{item['bundledFile'] or item['url']}")
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
