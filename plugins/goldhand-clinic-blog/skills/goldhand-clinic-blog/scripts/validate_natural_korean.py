#!/usr/bin/env python3
"""Block known Goldhand Korean word-choice and collocation regressions.

This is deliberately a regression guard, not a claim that a mechanical pass
proves natural Korean. The independent spoken editor and the user approval gate
remain mandatory.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = SKILL_DIR / "assets" / "natural-korean-regression-contract.json"


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).replace("\u200b", "").strip()


def contract_errors(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    principles = contract.get("generationPrinciples", [])
    principle_ids = {
        str(item.get("id", "")).strip()
        for item in principles
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }
    if not principle_ids:
        errors.append("generationPrinciples가 비어 있습니다.")
    for item in principles:
        if not isinstance(item, dict):
            errors.append("generationPrinciples 항목은 객체여야 합니다.")
            continue
        principle_id = str(item.get("id", "")).strip() or "<missing-id>"
        if not str(item.get("failureMechanism", "")).strip():
            errors.append(f"{principle_id}: failureMechanism이 필요합니다.")
        steps = item.get("generationSteps")
        if not isinstance(steps, list) or not all(isinstance(step, str) and step.strip() for step in steps):
            errors.append(f"{principle_id}: generationSteps가 필요합니다.")

    for rule in contract.get("failurePatterns", []):
        if not isinstance(rule, dict):
            errors.append("failurePatterns 항목은 객체여야 합니다.")
            continue
        code = str(rule.get("code", "")).strip() or "<missing-code>"
        for field in ("failedExample", "approvedExample", "failureMechanism", "reason"):
            if not str(rule.get(field, "")).strip():
                errors.append(f"{code}: {field}이 필요합니다.")
        rule_principles = rule.get("generationPrincipleIds")
        if not isinstance(rule_principles, list) or not rule_principles:
            errors.append(f"{code}: generationPrincipleIds가 필요합니다.")
            continue
        unknown = [value for value in rule_principles if value not in principle_ids]
        if unknown:
            errors.append(f"{code}: 알 수 없는 생성 원리 {unknown}")

    for correction in contract.get("contextualUserCorrections", []):
        if not isinstance(correction, dict):
            errors.append("contextualUserCorrections 항목은 객체여야 합니다.")
            continue
        correction_id = str(correction.get("id", "")).strip() or "<missing-id>"
        if correction.get("userCorrected") is not True:
            errors.append(f"{correction_id}: userCorrected=true가 필요합니다.")
        for field in ("failedContext", "approvedDirection", "failureMechanism"):
            if not str(correction.get(field, "")).strip():
                errors.append(f"{correction_id}: {field}이 필요합니다.")
        correction_principles = correction.get("generationPrincipleIds")
        if not isinstance(correction_principles, list) or not correction_principles:
            errors.append(f"{correction_id}: generationPrincipleIds가 필요합니다.")
            continue
        unknown = [value for value in correction_principles if value not in principle_ids]
        if unknown:
            errors.append(f"{correction_id}: 알 수 없는 생성 원리 {unknown}")

    gate = contract.get("forwardTestGate")
    if not isinstance(gate, dict):
        errors.append("forwardTestGate가 필요합니다.")
    else:
        if int(gate.get("minimumDistinctExistingManuscripts", 0)) < 3:
            errors.append("forwardTestGate는 기존 원고 3편 이상을 요구해야 합니다.")
        if gate.get("draftAndReviewRolesSeparated") is not True:
            errors.append("forwardTestGate는 초안과 검수 역할을 분리해야 합니다.")
        if str(gate.get("statusBeforeUserApproval", "")) != "pending-user-reading":
            errors.append("사용자 승인 전 상태는 pending-user-reading이어야 합니다.")
    findings = contract.get("forwardTestFindings")
    if not isinstance(findings, dict):
        errors.append("forwardTestFindings가 필요합니다.")
    else:
        if str(findings.get("status", "")) != "pending-user-reading":
            errors.append("전진 검증 결과는 사용자 승인 전 pending-user-reading이어야 합니다.")
        manuscripts = findings.get("manuscripts")
        if not isinstance(manuscripts, list) or len(manuscripts) < 3:
            errors.append("전진 검증 결과에는 서로 다른 기존 원고 3편 이상이 필요합니다.")
        else:
            titles: set[str] = set()
            for index, item in enumerate(manuscripts, start=1):
                if not isinstance(item, dict):
                    errors.append(f"전진 검증 원고 {index}은 객체여야 합니다.")
                    continue
                title = str(item.get("title", "")).strip()
                if not title:
                    errors.append(f"전진 검증 원고 {index}: title이 필요합니다.")
                elif title in titles:
                    errors.append(f"전진 검증 원고 {index}: 서로 다른 제목이어야 합니다.")
                titles.add(title)
                if not str(item.get("reviewReceipt", "")).strip().endswith(".json"):
                    errors.append(f"전진 검증 원고 {index}: 독립 검수 영수증 경로가 필요합니다.")
                for field in ("beforeSha256", "finalSha256"):
                    if re.fullmatch(r"[0-9a-f]{64}", str(item.get(field, ""))) is None:
                        errors.append(f"전진 검증 원고 {index}: {field}가 필요합니다.")
                if int(item.get("concreteFindingCount", 0)) <= 0:
                    errors.append(f"전진 검증 원고 {index}: 실제 전·후 문장 수정 기록이 필요합니다.")
                if int(item.get("flowCheckCount", 0)) < 2:
                    errors.append(f"전진 검증 원고 {index}: 문단과 글 전체 흐름 증거가 2건 이상 필요합니다.")
                if str(item.get("reviewerRole", "")) != "independent-natural-korean-spoken-editor":
                    errors.append(f"전진 검증 원고 {index}: 독립 생활어 검수 역할이 필요합니다.")
        for item in findings.get("observedFailureFamilies", []):
            if not isinstance(item, dict):
                errors.append("observedFailureFamilies 항목은 객체여야 합니다.")
                continue
            principle_id = str(item.get("generationPrincipleId", "")).strip()
            if principle_id not in principle_ids:
                errors.append(f"전진 검증 결과에 알 수 없는 생성 원리 {principle_id}")
            for field in ("failedExcerpt", "revisedExcerpt", "why"):
                if not str(item.get(field, "")).strip():
                    errors.append(f"전진 검증 {principle_id}: {field}이 필요합니다.")
    if contract.get("userApprovalRequiredToCallUpdateSuccessful") is not True:
        errors.append("자연스러움 업데이트 성공에는 사용자 승인이 필요합니다.")
    return errors


def validate_text(title: str, body: str, contract: dict[str, Any]) -> dict[str, Any]:
    visible = normalize(f"{title}\n{body}")
    issues: list[dict[str, str]] = []
    for rule in contract.get("failurePatterns", []):
        if not isinstance(rule, dict):
            continue
        pattern = str(rule.get("pattern", "")).strip()
        if not pattern:
            continue
        match = re.search(pattern, visible)
        if match is None:
            continue
        issues.append(
            {
                "severity": "error",
                "code": str(rule.get("code", "natural-korean-regression")),
                "detail": (
                    f"생활어 회귀 표현이 남았습니다: {match.group(0)} / "
                    f"{str(rule.get('reason', '')).strip()}"
                ),
            }
        )
    return {
        "status": "fail" if issues else "pass",
        "contractId": str(contract.get("contractId", "")),
        "scope": str(contract.get("scope", "known-regression-guard-only")),
        "mechanicalPassDoesNotProveNaturalness": bool(
            contract.get("mechanicalPassDoesNotProveNaturalness", True)
        ),
        "userApprovalRequiredToCallUpdateSuccessful": bool(
            contract.get("userApprovalRequiredToCallUpdateSuccessful", True)
        ),
        "metrics": {
            "knownRegressionCount": len(issues),
            "checkedPatternCount": len(contract.get("failurePatterns", [])),
            "generationPrincipleCount": len(contract.get("generationPrinciples", [])),
            "minimumForwardTestManuscripts": int(
                contract.get("forwardTestGate", {}).get("minimumDistinctExistingManuscripts", 0)
            ),
            "observedForwardTestManuscripts": len(
                contract.get("forwardTestFindings", {}).get("manuscripts", [])
            ),
        },
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="제목과 평문이 든 UTF-8 텍스트 파일")
    parser.add_argument("--title", default="")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        body = args.input.read_text(encoding="utf-8")
        contract = json.loads(args.contract.read_text(encoding="utf-8"))
        if not isinstance(contract, dict):
            raise ValueError("회귀검사 계약의 최상위 값은 객체여야 합니다.")
        invalid = contract_errors(contract)
        if invalid:
            raise ValueError("회귀검사 계약 오류: " + " / ".join(invalid))
        result = validate_text(args.title, body, contract)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, re.error) as exc:
        print(f"생활어 회귀검사 입력을 읽지 못했습니다: {exc}", file=sys.stderr)
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
