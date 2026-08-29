#!/usr/bin/env python3
"""Validate concrete evidence from an independent Korean plain-text review.

This validator does not decide whether prose sounds natural. It verifies that
the review was performed by a separate role, cites real before/after wording,
explains specific edits, rereads the whole draft, and hands the frozen wording
to automatic production. The final plain text must also satisfy the one allowed article
structure and the permanent user-correction regression guard.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import unicodedata
from pathlib import Path
from types import ModuleType
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
ASSETS = SKILL_DIR / "assets"
CONTRACT_ID = "goldhand-independent-natural-korean-review-v1"
REVIEWER_ROLE = "independent-natural-korean-spoken-editor"
INPUT_MODE = "title-and-draft-plain-text-only-no-seo-forbidden-list-or-validator-results"
GENERIC_REASON = re.compile(
    r"^(?:더\s*)?(?:자연스럽게|매끄럽게|읽기\s*쉽게|좋게|다듬었습니다|수정했습니다)[.!]?$"
)
HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
NUMBERED_HEADING = re.compile(r"^\s*\d+\s*[.．)\]]\s+\S")


def load_script(name: str) -> ModuleType:
    path = SKILL_DIR / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"goldhand_{name}_review", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"검사기를 불러올 수 없습니다: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STRUCTURE = load_script("validate_information_article_structure")
NATURAL = load_script("validate_natural_korean")


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def add(issues: list[dict[str, str]], code: str, detail: str) -> None:
    issues.append({"severity": "error", "code": code, "detail": detail})


def meaningful(value: Any, minimum: int) -> bool:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return len(text) >= minimum and GENERIC_REASON.fullmatch(text) is None


def local_text_path(receipt_path: Path, value: Any) -> Path:
    relative = Path(str(value or "").strip())
    if not str(relative) or relative.is_absolute():
        raise ValueError("평문 파일 경로는 검수 영수증과 같은 폴더 안의 상대 경로여야 합니다.")
    root = receipt_path.resolve().parent
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("평문 파일 경로가 검수 영수증 폴더 밖을 가리킵니다.") from exc
    return resolved


def read_local_text(receipt_path: Path, value: Any) -> str:
    return local_text_path(receipt_path, value).read_text(encoding="utf-8")


def reviewable_sentences(text: str, title: str, fixed_rows: list[str]) -> list[str]:
    """Return spoken sentences; fixed value-proof rows and headings are labels."""
    units: list[str] = []
    skip = {title, "[금손한의원 소개]", *fixed_rows}
    for raw_line in normalize(text).splitlines():
        line = raw_line.strip()
        if not line or line in skip or NUMBERED_HEADING.match(line):
            continue
        if line.startswith(">"):
            line = line[1:].strip()
        pieces = re.split(r"(?<=[.!?])\s+", line)
        units.extend(piece.strip() for piece in pieces if piece.strip())
    return units


def validate_receipt(receipt_path: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, str]] = []

    if receipt.get("schemaVersion") != 1:
        add(issues, "schema-version", "schemaVersion은 1이어야 합니다.")
    if receipt.get("contractId") != CONTRACT_ID:
        add(issues, "contract-id", f"contractId는 {CONTRACT_ID}여야 합니다.")

    title = str(receipt.get("title", "")).strip()
    if not title:
        add(issues, "title-missing", "확정 제목이 필요합니다.")

    try:
        before = read_local_text(receipt_path, receipt.get("beforePlainTextFile"))
        final = read_local_text(receipt_path, receipt.get("finalPlainTextFile"))
    except (OSError, UnicodeError, ValueError) as exc:
        add(issues, "plain-text-file", str(exc))
        before = ""
        final = ""

    for label, text in (("초안", before), ("최종 평문", final)):
        if not text:
            add(issues, "plain-text-empty", f"{label}이 비어 있습니다.")
            continue
        first = normalize(text).splitlines()[0]
        if first != title:
            add(issues, "confirmed-title-changed", f"{label}의 첫 줄이 확정 제목과 다릅니다.")
        if HTML_TAG.search(text) or MARKDOWN_IMAGE.search(text):
            add(issues, "production-format-in-plain-review", f"{label}에는 HTML이나 이미지 문법을 넣을 수 없습니다.")
        if re.search(r"(?m)^\s*\|.*\|\s*$", text):
            add(issues, "markdown-table-in-plain-review", f"{label}에는 마크다운 표를 넣을 수 없습니다.")

    if before and final and normalize(before) == normalize(final):
        add(issues, "no-independent-revision", "초안과 최종 평문이 같아 실제 독립 수정 증거가 없습니다.")
    if before and receipt.get("beforeDraftSha256") != sha256_text(before):
        add(issues, "before-hash-mismatch", "초안 SHA-256이 실제 파일과 다릅니다.")
    if final and receipt.get("finalDraftSha256") != sha256_text(final):
        add(issues, "final-hash-mismatch", "최종 평문 SHA-256이 실제 파일과 다릅니다.")

    draft_author = str(receipt.get("draftAuthor", "")).strip()
    reviewer = str(receipt.get("reviewer", "")).strip()
    if not draft_author or not reviewer or draft_author == reviewer:
        add(issues, "reviewer-not-independent", "초안 작성자와 독립 검수자의 식별값은 서로 달라야 합니다.")
    if receipt.get("draftReviewerSeparated") is not True:
        add(issues, "reviewer-role-not-separated", "초안 작성과 독립 검수 역할이 분리되어야 합니다.")
    if receipt.get("reviewerRole") != REVIEWER_ROLE:
        add(issues, "reviewer-role", f"reviewerRole은 {REVIEWER_ROLE}이어야 합니다.")
    if receipt.get("reviewerInputMode") != INPUT_MODE:
        add(issues, "reviewer-input-leak", "검수자에게는 제목과 초안 평문만 전달해야 합니다.")

    if not meaningful(receipt.get("reviewerReport"), 80):
        add(issues, "review-report-too-vague", "검수 결과에는 실제 어색함과 글 전체 흐름에 대한 구체적 설명이 필요합니다.")
    if not meaningful(receipt.get("meaningPreservationReport"), 60):
        add(issues, "meaning-preservation-evidence-missing", "어떤 정보와 의료 경계를 보존했는지 구체적으로 기록해야 합니다.")
    if not meaningful(receipt.get("wholeDraftRereadReport"), 80):
        add(issues, "whole-draft-reread-evidence-missing", "수정 뒤 전체 평문을 다시 읽은 구체적 기록이 필요합니다.")

    findings = receipt.get("findings")
    if not isinstance(findings, list) or not findings:
        add(issues, "concrete-findings-missing", "true 체크가 아니라 실제 전·후 문장과 수정 이유가 한 건 이상 필요합니다.")
        findings = []
    for index, finding in enumerate(findings, start=1):
        if not isinstance(finding, dict):
            add(issues, "finding-shape", f"수정 기록 {index}은 객체여야 합니다.")
            continue
        old = str(finding.get("before", "")).strip()
        new = str(finding.get("after", "")).strip()
        reason = str(finding.get("reason", "")).strip()
        if not old or old not in before:
            add(issues, "finding-before-not-found", f"수정 기록 {index}의 이전 문장이 실제 초안에 없습니다.")
        if not new or new not in final:
            add(issues, "finding-after-not-found", f"수정 기록 {index}의 수정 문장이 실제 최종 평문에 없습니다.")
        if normalize(old) == normalize(new):
            add(issues, "finding-not-changed", f"수정 기록 {index}의 전·후 문장이 같습니다.")
        if not meaningful(reason, 20):
            add(issues, "finding-reason-too-vague", f"수정 기록 {index}은 단어 결합이나 뜻이 왜 어색했는지 구체적으로 설명해야 합니다.")

    flow_checks = receipt.get("flowChecks")
    if not isinstance(flow_checks, list) or len(flow_checks) < 2:
        add(issues, "whole-flow-evidence-missing", "서로 다른 블록 연결을 실제 문장으로 확인한 기록이 2건 이상 필요합니다.")
        flow_checks = []
    for index, check in enumerate(flow_checks, start=1):
        if not isinstance(check, dict):
            add(issues, "flow-check-shape", f"흐름 기록 {index}은 객체여야 합니다.")
            continue
        source = str(check.get("fromExcerpt", "")).strip()
        target = str(check.get("toExcerpt", "")).strip()
        reason = str(check.get("reason", "")).strip()
        source_pos = final.find(source) if source else -1
        target_pos = final.find(target) if target else -1
        if source_pos < 0 or target_pos < 0:
            add(issues, "flow-excerpt-not-found", f"흐름 기록 {index}의 인용문이 최종 평문에 없습니다.")
        elif source_pos >= target_pos:
            add(issues, "flow-order-wrong", f"흐름 기록 {index}의 앞·뒤 문장 순서가 실제 평문과 다릅니다.")
        if not meaningful(reason, 20):
            add(issues, "flow-reason-too-vague", f"흐름 기록 {index}에는 두 문단이 어떻게 이어지는지 구체적 이유가 필요합니다.")

    if receipt.get("remainingAwkwardPassages") != []:
        add(issues, "unresolved-awkward-passages", "남은 어색한 구절이 있으면 사용자 제시 전 단계로 갈 수 없습니다.")
    if receipt.get("productionHandoffStatus") != "ready-for-automatic-production":
        add(issues, "automatic-production-handoff", "내부 검수 뒤에는 ready-for-automatic-production 상태여야 합니다.")

    structure_result: dict[str, Any] = {"status": "not-run", "issues": []}
    natural_result: dict[str, Any] = {"status": "not-run", "issues": []}
    sentence_count = 0
    if final and title:
        structure_contract = json.loads((ASSETS / "information-delivery-structure-contract.json").read_text(encoding="utf-8"))
        proof = json.loads((ASSETS / "goldhand-value-proof-library.json").read_text(encoding="utf-8"))
        natural_contract = json.loads((ASSETS / "natural-korean-regression-contract.json").read_text(encoding="utf-8"))
        structure_result = STRUCTURE.validate_plain(final, title, structure_contract, proof)
        natural_contract_issues = NATURAL.contract_errors(natural_contract)
        if natural_contract_issues:
            add(issues, "natural-contract-invalid", " / ".join(natural_contract_issues))
        natural_result = NATURAL.validate_text("", final, natural_contract)
        if structure_result["status"] != "pass":
            add(issues, "single-structure-failed", "최종 평문이 유일한 정보전달형 구조 검사를 통과하지 못했습니다.")
        if natural_result["status"] != "pass":
            add(issues, "known-korean-regression", "최종 평문에 사용자 교정과 같은 생활어 회귀가 남았습니다.")
        sentence_count = len(reviewable_sentences(final, title, [str(item) for item in proof.get("fixedRows", [])]))

    audited_count = receipt.get("auditedSentenceCount")
    checked = receipt.get("sentenceIndexesChecked")
    expected_indexes = list(range(1, sentence_count + 1))
    if audited_count != sentence_count or checked != expected_indexes:
        add(issues, "sentence-audit-incomplete", "최종 평문의 모든 발화 문장을 문자 그대로 다시 확인한 범위가 맞지 않습니다.")

    return {
        "status": "fail" if issues else "pass",
        "contractId": CONTRACT_ID,
        "mechanicalPassDoesNotProveNaturalness": True,
        "plainTextApprovalRequired": False,
        "automaticProductionHandoffReady": not issues,
        "metrics": {
            "findingCount": len(findings),
            "flowCheckCount": len(flow_checks),
            "reviewableSentenceCount": sentence_count,
            "structureStatus": structure_result.get("status"),
            "knownRegressionStatus": natural_result.get("status"),
        },
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="독립 검수 영수증 JSON")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        receipt = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict):
            raise ValueError("검수 영수증의 최상위 값은 객체여야 합니다.")
        result = validate_receipt(args.input, receipt)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        print(f"독립 생활어 검수 영수증을 읽지 못했습니다: {exc}", file=sys.stderr)
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
