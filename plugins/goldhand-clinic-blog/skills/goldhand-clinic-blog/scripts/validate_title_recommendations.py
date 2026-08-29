#!/usr/bin/env python3
"""Validate five numbered-title recommendations for the single article structure."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = SKILL_DIR / "assets" / "title-recommendation-contract.json"
DEFAULT_EVIDENCE = SKILL_DIR / "references" / "clinic-facts.md"
TITLE_VALIDATOR_PATH = Path(__file__).with_name("validate_title.py")


def load_title_validator():
    spec = importlib.util.spec_from_file_location("goldhand_title_validator", TITLE_VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"제목 검증기를 불러올 수 없습니다: {TITLE_VALIDATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TITLE_VALIDATOR = load_title_validator()


def add(issues: list[dict[str, Any]], code: str, detail: str, index: int | None = None) -> None:
    issue: dict[str, Any] = {"severity": "error", "code": code, "detail": detail}
    if index is not None:
        issue["candidateIndex"] = index
    issues.append(issue)


def validate_recommendations(
    payload: dict[str, Any],
    *,
    contract: dict[str, Any],
    evidence: str,
    writing_intelligence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del writing_intelligence
    issues: list[dict[str, Any]] = []
    candidate_results: list[dict[str, Any]] = []
    topic = TITLE_VALIDATOR.normalize(str(payload.get("topic", "")))
    candidates = payload.get("candidates", [])
    expected_count = int(contract.get("candidateCount", 5))

    if not topic:
        add(issues, "topic-empty", "글 주제가 비어 있습니다.")

    doctor = payload.get("informationDoctor")
    if not isinstance(doctor, dict):
        add(issues, "information-doctor-missing", "제목 제안 전에 저장 정보 박사의 title 조회가 필요합니다.")
    else:
        if doctor.get("queried") is not True or str(doctor.get("stage", "")).strip() != "title":
            add(issues, "information-doctor-invalid", "informationDoctor는 queried=true, stage=title이어야 합니다.")
        if doctor.get("sourceProseLoaded") is not False:
            add(issues, "source-prose-loaded", "제목 단계에서는 출처 원문을 전달하지 않습니다.")
        if doctor.get("structureLoadedFromSources") is not False:
            add(issues, "source-structure-loaded", "정보 출처에서 글 구조를 불러오지 않습니다.")
        authority = str(doctor.get("singleStructureAuthority", "")).strip()
        if authority and authority != "references/information-delivery-structure.md":
            add(issues, "single-structure-authority", "글 구조 권한은 information-delivery-structure.md 하나뿐입니다.")

    if not isinstance(candidates, list):
        add(issues, "candidates-not-list", "candidates는 제목 후보 목록이어야 합니다.")
        candidates = []
    if len(candidates) != expected_count:
        add(issues, "candidate-count", f"제목 후보는 정확히 {expected_count}개여야 합니다.")

    seen: set[str] = set()
    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            add(issues, "candidate-not-object", "제목 후보는 객체여야 합니다.", index)
            continue
        title = TITLE_VALIDATOR.normalize(str(candidate.get("title", "")))
        answer_count = candidate.get("answerCount")
        if not isinstance(answer_count, int):
            add(issues, "answer-count-missing", "각 제목 후보에는 실제로 확보한 답 개수 answerCount가 필요합니다.", index)
            answer_count = None
        signature = TITLE_VALIDATOR.compact(title)
        if signature in seen:
            add(issues, "duplicate-title", "서로 다른 제목 5개를 제안해야 합니다.", index)
        elif signature:
            seen.add(signature)
        validation = TITLE_VALIDATOR.validate_title(
            title,
            evidence=evidence,
            answer_count=answer_count,
        )
        candidate_results.append({"candidateIndex": index, "title": title, "validation": validation})

    nested_errors = sum(
        item["severity"] == "error"
        for candidate in candidate_results
        for item in candidate["validation"]["issues"]
    )
    error_count = len(issues) + nested_errors
    return {
        "status": "fail" if error_count else "pass",
        "contractId": str(contract.get("contractId", "")),
        "metrics": {
            "candidateCount": len(candidates),
            "uniqueTitleCount": len(seen),
            "numberedCandidateCount": sum(
                bool(candidate["validation"]["metrics"]["answerPromises"])
                for candidate in candidate_results
            ),
            "singleStructureContractId": "goldhand-single-information-delivery-structure-v1",
            "errors": error_count,
            "warnings": 0,
        },
        "issues": issues,
        "candidateResults": candidate_results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        contract = json.loads(args.contract.read_text(encoding="utf-8"))
        evidence = args.evidence.read_text(encoding="utf-8")
        if not isinstance(payload, dict) or not isinstance(contract, dict):
            raise ValueError("입력 JSON의 최상위 값은 객체여야 합니다.")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"제목 추천 검증 입력을 읽지 못했습니다: {exc}", file=sys.stderr)
        return 2
    validation = validate_recommendations(payload, contract=contract, evidence=evidence)
    if args.json:
        print(json.dumps(validation, ensure_ascii=False, indent=2))
    else:
        print(f"status: {validation['status']}")
        for issue in validation["issues"]:
            print(f"[ERROR] {issue['code']}: {issue['detail']}")
    return 1 if validation["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
