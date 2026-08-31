#!/usr/bin/env python3
"""Recommend approved Goldhand clinical photos for numbered answer sections.

This selector runs after the internal plain-text review, without another user gate. It never creates an introduction, credential, closing, or CTA
photo block. Every selected photo is placed inside a numbered answer section.
"""

from __future__ import annotations

import argparse
import json
import importlib.util
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
    parser.add_argument("--used-media", type=Path, help="이 글에서 이미 선택한 추천 JSON; 중복 원본을 제외합니다.")
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
    used_media: list[dict[str, Any]] | None = None,
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
    spec = importlib.util.spec_from_file_location("goldhand_unique_media", Path(__file__).with_name("validate_unique_images.py"))
    unique = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(unique)
    seen = set()
    for used in used_media or []:
        seen.update(unique.asset_keys(used))
    selected = []
    for score, _, _, asset in ranked:
        keys = unique.asset_keys(asset)
        if seen & keys:
            continue
        selected.append(public_item(asset, score))
        seen.update(keys)
        if len(selected) == count:
            break
    return {
        "status": "complete" if len(selected) == count else "partial" if selected else "no-matching-media",
        "placement": "numbered-section-body",
        "requested": count,
        "selectedCount": len(selected),
        "missing": max(0, count - len(selected)),
        "policy": "내부 평문 검수가 끝나면 주제와 맞는 시각 검수 진료 사진을 번호 소제목 설명 안에 자동 배치합니다. 적합한 사진이 없으면 이미지 없이 완성합니다.",
        "selected": selected,
        "used": [*(used_media or []), *selected],
    }


def main() -> int:
    args = parse_args()
    try:
        library = load_json(args.library, required=True)
        used_payload = load_json(args.used_media, required=True) if args.used_media else {}
        result = recommend(
            library,
            topic=args.topic,
            count=args.count,
            used_media=used_payload.get("used", used_payload.get("selected", [])),
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
