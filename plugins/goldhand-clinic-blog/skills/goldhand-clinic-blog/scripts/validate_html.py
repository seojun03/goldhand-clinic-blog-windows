#!/usr/bin/env python3
"""Validate a Goldhand Naver copy page without reintroducing old article structures."""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


REQUIRED_SNIPPETS = {
    "copy-root": 'id="naver-copy-root"',
    "copy-button": 'id="copy-for-naver"',
    "clipboard-item": "ClipboardItem",
    "html-mime": "text/html",
    "plain-mime": "text/plain",
    "copy-fallback": "execCommand('copy')",
    "copy-preview": "__goldhandCopyPreview",
    "native-copy-sanitizer": "stripInternalMetadata",
    "article-wrapper-strip": "root.querySelector('article')",
    "native-input-buffer": "INPUT_BUFFER_DATA;",
    "native-selection-root": "nativeSelectionRoot",
    "native-selection-copy": "copyRenderedSelection(nativeSelectionRoot(inputBuffer,nativeHtml))",
    "native-selection-input-buffer": "inputBuffer.cloneNode(true)",
    "native-selection-html": "selectionRoot.insertAdjacentHTML('beforeend',nativeHtml)",
    "native-selection-attach": "document.body.appendChild(copyRoot)",
    "native-selection-range": "range.selectNodeContents(copyRoot)",
    "native-selection-add-range": "selection.addRange(range)",
    "native-selection-cleanup": "copyRoot.remove()",
    "clipboard-html-payload": "'text/html':new Blob([htmlValue]",
    "clipboard-plain-payload": "'text/plain':new Blob([plainValue]",
}

FORBIDDEN_OLD_STRUCTURE = {
    "editorial-master-metadata": re.compile(r"\bdata-editorial-(?:mode|master-id|reference-source|source-role|profile-status)\s*=", re.I),
    "old-greeting-role": re.compile(r"\bdata-reference-role\s*=\s*['\"]greeting-authority['\"]", re.I),
    "old-neutral-close": re.compile(r"\bdata-reference-role\s*=\s*['\"]neutral-close['\"]", re.I),
    "old-contact-role": re.compile(r"\bdata-reference-role\s*=\s*['\"]contact['\"]", re.I),
    "old-clinic-info": re.compile(r"\bdata-native-table-purpose\s*=\s*['\"]clinic-info['\"]", re.I),
    "old-closing-links": re.compile(r"\bdata-goldhand-closing-links\s*=", re.I),
    "post-cta-related-content": re.compile(r"\bse-(?:oglink|placesMap)\b|함께\s*보면\s*좋은\s*글", re.I),
}


def add(issues: list[dict[str, str]], severity: str, code: str, detail: str) -> None:
    issues.append({"severity": severity, "code": code, "detail": detail})


def page_title(raw: str) -> str:
    match = re.search(
        r"<title\b[^>]*>\s*(.*?)\s*·\s*금손한의원\s+네이버용\s+HTML\s*</title>",
        raw,
        flags=re.I | re.S,
    )
    return re.sub(r"\s+", " ", html.unescape(match.group(1))).strip() if match else ""


def article_fragment(raw: str) -> str:
    matches = re.findall(r"<article\b[^>]*>.*?</article>", raw, flags=re.I | re.S)
    if len(matches) != 1:
        raise ValueError(f"복사 페이지에는 article 하나가 필요합니다. 현재 {len(matches)}개입니다.")
    return matches[0]


def structure_validation(article: str, title: str) -> dict[str, Any]:
    path = Path(__file__).with_name("validate_information_article_structure.py")
    spec = importlib.util.spec_from_file_location("goldhand_copy_information_structure", path)
    if spec is None or spec.loader is None:
        raise ValueError("정보전달형 단일 구조 검증기를 불러올 수 없습니다.")
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    contract = json.loads(validator.DEFAULT_CONTRACT.read_text(encoding="utf-8"))
    proof = json.loads(validator.DEFAULT_VALUE_PROOF.read_text(encoding="utf-8"))
    return validator.validate_html(article, title, contract, proof)


def validate_html(raw: str, *, max_megabytes: float = 30.0) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    for code, snippet in REQUIRED_SNIPPETS.items():
        if snippet not in raw:
            add(issues, "error", code, f"필수 복사 페이지 요소가 없습니다: {snippet}")

    copy_root_count = len(re.findall(r"\bid\s*=\s*['\"]naver-copy-root['\"]", raw, flags=re.I))
    if copy_root_count != 1:
        add(issues, "error", "copy-root-count", f"naver-copy-root가 {copy_root_count}개입니다.")
    if not re.search(r"<main\b[^>]*\bid\s*=\s*['\"]naver-copy-root['\"][^>]*>\s*<article\b", raw, flags=re.I | re.S):
        add(issues, "error", "article-outside-copy-root", "복사 대상 main 안에 article 하나가 직접 있어야 합니다.")

    title = page_title(raw)
    if not title:
        add(issues, "error", "article-title-missing", "복사 페이지 title에서 확정 제목을 확인할 수 없습니다.")
    try:
        article = article_fragment(raw)
    except ValueError as exc:
        add(issues, "error", "article-count", str(exc))
        article = ""

    structure_metrics: dict[str, Any] = {}
    if article and title:
        try:
            structure = structure_validation(article, title)
            structure_metrics = structure.get("metrics", {}) if isinstance(structure, dict) else {}
            for issue in structure.get("issues", []):
                add(issues, str(issue.get("severity", "error")), str(issue.get("code", "information-structure")), str(issue.get("detail", "단일 구조를 확인하세요.")))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            add(issues, "error", "information-structure-load", str(exc))

    if article:
        for code, pattern in FORBIDDEN_OLD_STRUCTURE.items():
            if pattern.search(article):
                add(issues, "error", code, "단일 정보전달 구조에 없는 이전 글 블록이나 메타데이터가 남아 있습니다.")
        if re.search(r"<figcaption\b|사진 설명을 입력하세요\.", article, re.I):
            add(issues, "error", "visible-image-caption-forbidden", "보이는 이미지 캡션이나 자리표시자를 남기지 않습니다.")
        if re.search(r"\bdata-local-image\s*=", article, re.I):
            add(issues, "error", "local-image-not-published", "복사용 HTML에는 로컬 이미지 경로를 남길 수 없습니다.")
        for source in re.findall(r"<img\b[^>]*\bsrc\s*=\s*['\"](.*?)['\"]", article, flags=re.I | re.S):
            if not source.startswith("https://"):
                add(issues, "error", "invalid-image-source", f"복사용 이미지 src는 HTTPS여야 합니다: {source[:120]}")

    size_bytes = len(raw.encode("utf-8"))
    if size_bytes > max_megabytes * 1024 * 1024:
        add(issues, "warning", "large-html", f"HTML이 {size_bytes / 1024 / 1024:.1f}MB입니다.")
    errors = sum(item["severity"] == "error" for item in issues)
    warnings = sum(item["severity"] == "warning" for item in issues)
    return {
        "status": "fail" if errors else "warning" if warnings else "pass",
        "metrics": {
            "structureContractId": "goldhand-single-information-delivery-structure-v1",
            "articleCount": 1 if article else 0,
            "copyRootCount": copy_root_count,
            "sizeBytes": size_bytes,
            "readerQuestionCount": structure_metrics.get("readerQuestionCount", 0),
            "numberedHeadingCount": structure_metrics.get("numberedHeadingCount", 0),
            "numberedHeadingNumbers": structure_metrics.get("numberedHeadingNumbers", []),
            "errors": errors,
            "warnings": warnings,
        },
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--max-megabytes", type=float, default=30.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = validate_html(args.input.read_text(encoding="utf-8"), max_megabytes=args.max_megabytes)
    except (OSError, UnicodeError) as exc:
        print(f"HTML 검증 실패: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status: {result['status']}")
        for issue in result["issues"]:
            print(f"[{issue['severity'].upper()}] {issue['code']}: {issue['detail']}")
    return 1 if result["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
