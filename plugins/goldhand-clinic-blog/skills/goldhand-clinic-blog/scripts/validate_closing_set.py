#!/usr/bin/env python3
"""Validate closing variation across multiple Goldhand plain-text manuscripts."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import unicodedata
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
STRUCTURE_VALIDATOR = SCRIPT_DIR / "validate_information_article_structure.py"


def load_structure_validator():
    spec = importlib.util.spec_from_file_location(
        "goldhand_information_structure_for_closing_set",
        STRUCTURE_VALIDATOR,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(STRUCTURE_VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STRUCTURE = load_structure_validator()


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def closing_text(value: str) -> str:
    blocks = STRUCTURE.paragraph_blocks(value)
    return "\n".join(blocks[-2:]) if len(blocks) >= 2 else normalize(value)


def gratitude_sentence(value: str) -> str | None:
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", normalize(value)):
        if STRUCTURE.THANKS_CUE.search(sentence):
            return sentence.strip()
    return None


def validate_manuscripts(paths: list[Path]) -> dict:
    issues: list[dict[str, object]] = []
    gratitude_by_path: dict[str, str] = {}
    phrase_paths: dict[str, list[str]] = {}

    for path in paths:
        text = path.read_text(encoding="utf-8")
        ending = closing_text(text)
        branded = STRUCTURE.BRANDED_CLOSING_CUE.search(ending)
        if branded:
            issues.append(
                {
                    "severity": "error",
                    "code": "branded-closing-cta",
                    "path": str(path),
                    "detail": f"마무리에 특정 병원명이나 지역 한의원 키워드가 있습니다: {branded.group(0)}",
                }
            )
        sales = STRUCTURE.DIRECT_SALES_CLOSING_CUE.search(ending)
        if sales:
            issues.append(
                {
                    "severity": "error",
                    "code": "sales-closing-cta",
                    "path": str(path),
                    "detail": f"마무리에 예약·문의·전화·내원 유도가 있습니다: {sales.group(0)}",
                }
            )
        phrase = gratitude_sentence(ending)
        if phrase is None:
            issues.append(
                {
                    "severity": "error",
                    "code": "closing-gratitude-missing",
                    "path": str(path),
                    "detail": "마무리에서 읽어 준 데 대한 감사의 뜻을 찾지 못했습니다.",
                }
            )
            continue
        normalized_phrase = normalize(phrase)
        gratitude_by_path[str(path)] = normalized_phrase
        phrase_paths.setdefault(normalized_phrase, []).append(str(path))

    for phrase, reused_paths in phrase_paths.items():
        if len(reused_paths) < 2:
            continue
        issues.append(
            {
                "severity": "error",
                "code": "exact-gratitude-reused-across-manuscripts",
                "paths": reused_paths,
                "detail": f"같은 감사 문장을 여러 원고에 반복했습니다: {phrase}",
            }
        )

    return {
        "status": "fail" if issues else "pass",
        "scope": "cross-manuscript-closing-variation-and-neutrality",
        "metrics": {
            "manuscriptCount": len(paths),
            "gratitudeSentenceCount": len(gratitude_by_path),
            "uniqueGratitudeSentenceCount": len(set(gratitude_by_path.values())),
        },
        "gratitudeByPath": gratitude_by_path,
        "issues": issues,
        "mechanicalPassDoesNotProveNaturalness": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", nargs="+", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if len(args.input) < 2:
            raise ValueError("서로 다른 원고 2편 이상이 필요합니다.")
        result = validate_manuscripts(args.input)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"마무리 묶음 검증 입력을 읽지 못했습니다: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status: {result['status']}")
        for issue in result["issues"]:
            print(f"[ERROR] {issue['code']}: {issue['detail']}")
    return 1 if result["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
