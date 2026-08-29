#!/usr/bin/env python3
"""Query the persistent Goldhand information-reference knowledge store.

The title stage returns compact reader questions and generalized title angles.
It intentionally omits source prose, source titles, clinic facts, and editorial
master data.  The article stage delegates to select_general_information.py and
returns the reviewed information atoms needed after a title is confirmed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_BRIEFS = SKILL_DIR / "assets" / "wipark-content-briefs.json"
DEFAULT_LIBRARY = SKILL_DIR / "assets" / "user-general-information-references.json"
SELECTOR_PATH = Path(__file__).with_name("select_general_information.py")


def load_selector():
    spec = importlib.util.spec_from_file_location("goldhand_information_selector", SELECTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"일반 정보 선택기를 불러올 수 없습니다: {SELECTOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SELECTOR = load_selector()


def clean(value: Any) -> str:
    return " ".join(str(value).split()).strip()


def unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = clean(value)
        signature = SELECTOR.compact(item)
        if item and signature not in seen:
            seen.add(signature)
            result.append(item)
    return result


def source_title_angles(source: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    raw = source.get("titleAngles", [])
    if isinstance(raw, list):
        for index, item in enumerate(raw, start=1):
            if isinstance(item, str):
                angle = clean(item)
                promised_count = SELECTOR.promised_answer_count(angle)
                if angle and promised_count != -1 and (promised_count is None or promised_count >= 1):
                    result.append(
                        {
                            "angleId": f"{source.get('id', 'SOURCE')}-T{index}",
                            "angle": angle,
                            "mechanism": "reviewed-information-angle",
                        }
                    )
                continue
            if not isinstance(item, dict):
                continue
            angle = clean(item.get("angle", ""))
            if not angle:
                continue
            promised_count = SELECTOR.promised_answer_count(angle)
            if promised_count == -1 or (promised_count is not None and promised_count < 1):
                continue
            normalized = {
                "angleId": clean(item.get("angleId", ""))
                or f"{source.get('id', 'SOURCE')}-T{index}",
                "angle": angle,
                "mechanism": clean(item.get("mechanism", "reviewed-information-angle")),
            }
            count = item.get("supportedAnswerCount")
            if isinstance(count, int):
                if count < 1:
                    continue
                normalized["supportedAnswerCount"] = count
            result.append(normalized)
    return result


def title_query(
    topic: str,
    briefs: dict[str, Any],
    library: dict[str, Any],
    *,
    maximum_sources: int = 12,
) -> dict[str, Any]:
    normalized_topic = SELECTOR.normalize(topic)
    anchors = SELECTOR.subject_anchor_terms(normalized_topic)
    sources = SELECTOR.built_in_sources(briefs) + SELECTOR.user_sources(library)
    matches: list[dict[str, Any]] = []

    for source in sources:
        if not SELECTOR.source_allowed(source, normalized_topic):
            continue
        anchor_haystack = " ".join(
            [
                str(source.get("sourceTitle", "")),
                str(source.get("topic", "")),
                *[str(value) for value in source.get("primaryTopicTags", []) if isinstance(value, str)],
            ]
        )
        score = SELECTOR.text_score(anchor_haystack, anchors)
        if score <= 0:
            continue
        atoms = SELECTOR.source_atoms(source)
        questions = unique(
            [
                *[str(value) for value in source.get("readerQuestions", []) if isinstance(value, str)],
                *[str(value) for value in source.get("readerConcerns", []) if isinstance(value, str)],
            ]
        )
        matches.append(
            {
                "sourceId": clean(source.get("id", "")),
                "score": score,
                "atomCount": len(atoms),
                "readerQuestions": questions,
                "titleAngles": source_title_angles(source),
            }
        )

    matches.sort(key=lambda item: (-int(item["score"]), str(item["sourceId"])))
    matches = matches[: max(1, maximum_sources)]
    questions = unique(
        [question for match in matches for question in match.get("readerQuestions", [])]
    )[:12]

    angles: list[dict[str, Any]] = []
    seen_angles: set[str] = set()
    for match in matches:
        for angle in match.get("titleAngles", []):
            signature = SELECTOR.compact(str(angle.get("angle", "")))
            if not signature or signature in seen_angles:
                continue
            seen_angles.add(signature)
            angles.append({**angle, "sourceIds": [match["sourceId"]]})
    angles = angles[:15]

    total_atoms = sum(int(match.get("atomCount", 0)) for match in matches)
    supported_counts = list(range(1, total_atoms + 1))
    status = "stored-match" if matches else "no-stored-match"
    return {
        "status": status,
        "stage": "title",
        "topic": normalized_topic,
        "matchedSourceIds": [match["sourceId"] for match in matches],
        "readerQuestions": questions,
        "titleAngles": angles,
        "coverage": {
            "matchedSourceCount": len(matches),
            "reviewedAtomCount": total_atoms,
            "supportedAnswerCounts": supported_counts,
        },
        "fallback": {
            "useTitleContractOnly": not bool(matches),
            "researchStillDeferredUntilTitleSelection": True,
        },
        "boundaries": {
            "sourceProseLoaded": False,
            "sourceTitlesReturned": False,
            "sourceClinicFactsReturned": False,
            "structureLoadedFromSources": False,
            "singleStructureAuthority": "references/information-delivery-structure.md",
            "sourceTitleCopyBlocked": True,
            "titleMustBeNewGoldhandWording": True,
        },
    }


def query(
    *,
    stage: str,
    topic: str,
    title: str,
    answer_count: int | None,
    briefs: dict[str, Any],
    library: dict[str, Any],
    maximum_sources: int,
) -> dict[str, Any]:
    if stage == "title":
        return title_query(topic, briefs, library, maximum_sources=maximum_sources)
    if not title:
        raise ValueError("article 단계에는 확정 제목이 필요합니다.")
    if answer_count is not None and answer_count < 1:
        raise ValueError("article 단계의 답 개수는 1개 이상이어야 합니다.")
    result = SELECTOR.select_information(
        topic,
        title,
        briefs,
        library,
        answer_count=answer_count,
    )
    return {
        **result,
        "stage": "article",
        "knowledgeDoctor": {
            "persistentStoreQueried": True,
            "sourceProseReloaded": False,
            "sourceStructureIgnored": True,
            "singleStructureId": "goldhand-single-information-delivery-structure-v1",
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("title", "article"), default="title")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--answer-count", type=int)
    parser.add_argument("--maximum-sources", type=int, default=12)
    parser.add_argument("--briefs", type=Path, default=DEFAULT_BRIEFS)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        briefs = json.loads(args.briefs.read_text(encoding="utf-8"))
        library = json.loads(args.library.read_text(encoding="utf-8"))
        result = query(
            stage=args.stage,
            topic=args.topic,
            title=args.title,
            answer_count=args.answer_count,
            briefs=briefs,
            library=library,
            maximum_sources=args.maximum_sources,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        print(f"정보 박사 조회 실패: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status: {result['status']}")
        print(f"stage: {result['stage']}")
        print(f"저장 레퍼런스: {result.get('coverage', {}).get('matchedSourceCount', 0)}편")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
