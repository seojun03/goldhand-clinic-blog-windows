#!/usr/bin/env python3
"""Validate curated user references before they can supply general information atoms."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY = SKILL_DIR / "assets" / "user-general-information-references.json"
REQUIRED_SOURCE_FLAGS = (
    "generalInformationOnly",
    "sourceClinicFactsBlocked",
    "sourceSentencesBlocked",
    "sourceCasesAndResultsBlocked",
)
REQUIRED_ATOM_LISTS = ("observables", "meaning")
REQUIRED_DOCTOR_FLAGS = (
    "oneTimeLearning",
    "rawSourceProseStored",
    "structureMasterMutationBlocked",
    "duplicateUrlAndHashSkip",
    "explicitRefreshRequiredWhenHashChanges",
)
RAW_PROSE_KEYS = {"body", "html", "paragraphs", "rawText", "sourceProse", "sourceSentences"}
FORBIDDEN_GENERIC_ENTITIES = (
    "위석부부한의원",
    "위석 원장",
    "박경화",
    "송정동",
    "광산구",
    "광주송정역",
)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def compact(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", clean(value)).lower()


def add(issues: list[dict[str, str]], code: str, detail: str) -> None:
    issues.append({"severity": "error", "code": code, "detail": detail})


def validate_library(data: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    if data.get("schemaVersion") != 1:
        add(issues, "schema-version", "schemaVersion은 1이어야 합니다.")
    policy = data.get("sourcePolicy")
    if not isinstance(policy, dict):
        add(issues, "source-policy", "sourcePolicy 객체가 필요합니다.")
    else:
        for flag in (
            "generalInformationOnly",
            "sourceClinicFactsBlocked",
            "sourceSentencesBlocked",
            "sourceCasesAndResultsBlocked",
            "goldhandFactsOnlyForClinicInformation",
        ):
            if policy.get(flag) is not True:
                add(issues, f"policy-{flag}", f"sourcePolicy.{flag}는 true여야 합니다.")

    doctor = data.get("knowledgeDoctor")
    doctor_enabled = isinstance(doctor, dict)
    if not doctor_enabled:
        add(issues, "knowledge-doctor", "knowledgeDoctor 객체가 필요합니다.")
        doctor = {}
    else:
        if clean(doctor.get("id", "")) != "goldhand-information-doctor-v1":
            add(issues, "knowledge-doctor-id", "knowledgeDoctor.id가 올바르지 않습니다.")
        for flag in REQUIRED_DOCTOR_FLAGS:
            expected = False if flag == "rawSourceProseStored" else True
            if doctor.get(flag) is not expected:
                add(issues, f"knowledge-doctor-{flag}", f"knowledgeDoctor.{flag}는 {str(expected).lower()}여야 합니다.")
        stages = doctor.get("queryStages")
        if not isinstance(stages, list) or set(stages) != {"title", "article"}:
            add(issues, "knowledge-doctor-stages", "queryStages는 title과 article이어야 합니다.")

    sources = data.get("sources")
    if not isinstance(sources, list):
        add(issues, "sources-type", "sources는 배열이어야 합니다.")
        sources = []
    if doctor_enabled and doctor.get("storedSourceCount") != len(sources):
        add(
            issues,
            "knowledge-doctor-source-count",
            f"knowledgeDoctor.storedSourceCount는 실제 sources 수 {len(sources)}와 같아야 합니다.",
        )
    source_ids: set[str] = set()
    atom_ids: set[str] = set()
    source_urls: set[str] = set()
    content_hashes: set[str] = set()
    for index, source in enumerate(sources):
        label = f"sources[{index}]"
        if not isinstance(source, dict):
            add(issues, "source-type", f"{label}는 객체여야 합니다.")
            continue
        source_id = clean(source.get("id", ""))
        if not source_id:
            add(issues, "source-id", f"{label}.id가 필요합니다.")
        elif source_id in source_ids:
            add(issues, "source-id-duplicate", f"중복 source id: {source_id}")
        source_ids.add(source_id)
        for field in ("sourceTitle", "sourceUrl", "sourceType", "reviewStatus"):
            if not clean(source.get(field, "")):
                add(issues, f"source-{field}", f"{label}.{field}가 필요합니다.")
        source_url = clean(source.get("sourceUrl", ""))
        if source_url in source_urls:
            add(issues, "source-url-duplicate", f"중복 sourceUrl: {source_url}")
        elif source_url:
            source_urls.add(source_url)
        raw_fields = sorted(key for key in RAW_PROSE_KEYS if key in source)
        if raw_fields:
            add(issues, "source-raw-prose", f"{label}에 원문 보관 필드가 있습니다: {', '.join(raw_fields)}")
        if doctor_enabled:
            for field in ("sourceBlogId", "contentHash", "learnedAt"):
                if not clean(source.get(field, "")):
                    add(issues, f"source-{field}", f"{label}.{field}가 필요합니다.")
            content_hash = clean(source.get("contentHash", ""))
            if content_hash and re.fullmatch(r"[0-9a-f]{64}", content_hash) is None:
                add(issues, "source-content-hash-format", f"{label}.contentHash는 SHA-256 64자리여야 합니다.")
            if content_hash in content_hashes:
                add(issues, "source-content-hash-duplicate", f"중복 contentHash: {content_hash}")
            elif content_hash:
                content_hashes.add(content_hash)
            questions = source.get("readerQuestions")
            if not isinstance(questions, list) or not any(clean(value) for value in questions):
                add(issues, "source-reader-questions", f"{label}.readerQuestions가 하나 이상 필요합니다.")
                questions = []
            title_angles = source.get("titleAngles")
            if not isinstance(title_angles, list) or not title_angles:
                add(issues, "source-title-angles", f"{label}.titleAngles가 하나 이상 필요합니다.")
                title_angles = []
            for angle_index, angle in enumerate(title_angles):
                angle_label = f"{label}.titleAngles[{angle_index}]"
                if not isinstance(angle, dict) or not clean(angle.get("angle", "")):
                    add(issues, "source-title-angle", f"{angle_label}.angle이 필요합니다.")
                    continue
                count = angle.get("supportedAnswerCount")
                if count is not None and (not isinstance(count, int) or count not in {1, 2, 3}):
                    add(issues, "source-title-angle-count", f"{angle_label}.supportedAnswerCount는 1~3이어야 합니다.")
            if source.get("sourceProgramsProductsEquipmentBlocked") is not True:
                add(issues, "source-programs-products-equipment-blocked", f"{label}.sourceProgramsProductsEquipmentBlocked는 true여야 합니다.")
            if source.get("officialKoreanMedicalSupportRequiredAtDraftTime") is not True:
                add(issues, "source-official-support-at-draft", f"{label}.officialKoreanMedicalSupportRequiredAtDraftTime는 true여야 합니다.")
        tags = source.get("topicTags")
        if not isinstance(tags, list) or not any(clean(value) for value in tags):
            add(issues, "source-topic-tags", f"{label}.topicTags에 주제어가 하나 이상 필요합니다.")
        for flag in REQUIRED_SOURCE_FLAGS:
            if source.get(flag) is not True:
                add(issues, f"source-{flag}", f"{label}.{flag}는 true여야 합니다.")
        blocked = source.get("blockedEntities")
        if not isinstance(blocked, list) or not any(clean(value) for value in blocked):
            add(issues, "blocked-entities", f"{label}.blockedEntities에 출처 업체명·인명을 기록해야 합니다.")
            blocked = []
        source_clinic = clean(source.get("sourceClinicName", ""))
        if source.get("sourceType") == "clinic-blog" and not source_clinic:
            add(issues, "source-clinic-name", f"{label}.sourceClinicName이 필요합니다.")
        entities = [*FORBIDDEN_GENERIC_ENTITIES, source_clinic, *[clean(value) for value in blocked]]
        entity_signatures = {compact(value) for value in entities if compact(value)}

        compact_knowledge_parts: list[str] = []
        if isinstance(source.get("readerQuestions"), list):
            compact_knowledge_parts.extend(clean(value) for value in source["readerQuestions"])
        if isinstance(source.get("titleAngles"), list):
            for angle in source["titleAngles"]:
                if isinstance(angle, dict):
                    compact_knowledge_parts.append(clean(angle.get("angle", "")))
        compact_knowledge_signature = compact(" ".join(compact_knowledge_parts))
        for entity in entity_signatures:
            if entity and entity in compact_knowledge_signature:
                add(issues, "source-entity-in-compact-knowledge", f"{label}의 질문·제목 각도에 출처 업체 정보가 남아 있습니다.")
                break

        atoms = source.get("generalInformationAtoms")
        if not isinstance(atoms, list) or not atoms:
            add(issues, "source-atoms", f"{label}.generalInformationAtoms가 하나 이상 필요합니다.")
            continue
        for atom_index, atom in enumerate(atoms):
            atom_label = f"{label}.generalInformationAtoms[{atom_index}]"
            if not isinstance(atom, dict):
                add(issues, "atom-type", f"{atom_label}은 객체여야 합니다.")
                continue
            atom_id = clean(atom.get("id", ""))
            if not atom_id:
                add(issues, "atom-id", f"{atom_label}.id가 필요합니다.")
            elif atom_id in atom_ids:
                add(issues, "atom-id-duplicate", f"중복 atom id: {atom_id}")
            atom_ids.add(atom_id)
            if not clean(atom.get("role", "")):
                add(issues, "atom-role", f"{atom_label}.role이 필요합니다.")
            if atom.get("generalInformationOnly") is not True:
                add(issues, "atom-general-only", f"{atom_label}.generalInformationOnly는 true여야 합니다.")
            atom_text_parts: list[str] = []
            for field in REQUIRED_ATOM_LISTS:
                values = atom.get(field)
                if not isinstance(values, list) or not any(clean(value) for value in values):
                    add(issues, f"atom-{field}", f"{atom_label}.{field}에 값이 필요합니다.")
                    continue
                atom_text_parts.extend(clean(value) for value in values)
            atom_signature = compact(" ".join(atom_text_parts))
            for entity in entity_signatures:
                if entity and entity in atom_signature:
                    add(issues, "source-entity-in-atom", f"{atom_label}에 출처 업체 정보가 남아 있습니다.")
                    break

    errors = len(issues)
    return {
        "status": "fail" if errors else "pass",
        "metrics": {"sourceCount": len(sources), "atomCount": len(atom_ids), "errors": errors},
        "issues": issues,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("최상위 값은 JSON 객체여야 합니다.")
        result = validate_library(data)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"일반 정보 레퍼런스 검증 실패: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status: {result['status']}")
        for issue in result["issues"]:
            print(f"- {issue['code']}: {issue['detail']}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
