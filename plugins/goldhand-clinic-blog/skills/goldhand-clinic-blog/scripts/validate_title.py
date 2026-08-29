#!/usr/bin/env python3
"""Validate a confirmed Goldhand information-article title."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = SKILL_DIR / "references" / "clinic-facts.md"

FORBIDDEN = {
    "daily-post": re.compile(r"일상글|소소하루"),
    "specialist": re.compile(r"(?:전문의|통증\s*전문|소아\s*전문|갑상선\s*전문|다이어트\s*전문)"),
    "superlative": re.compile(r"(?:지역\s*1위|광주\s*1위|전국\s*1위|유일|최고|최상|가장\s*잘|무조건|완치|100\s*%)"),
    "unsupported-metric": re.compile(r"(?:누적\s*환자|누적\s*추나|재방문율|소개율|만족도|후기\s*수)"),
    "wrong-obesity-credential": re.compile(r"한방\s*비만\s*치료\s*인증\s*전문\s*한의사"),
    "wrong-ministry-credential": re.compile(r"보건복지부\s*인증\s*(?:약침\s*치료|골타\s*요법|한의원)"),
    "reference-business-leak": re.compile(r"(?:위석\s*부부\s*한의원|위석\s*원장|박경화|송정동|광산구|광주송정역|영광통|송정농협)"),
}
EMOTICON = re.compile(r"(?:\^\^|ㅎㅎ|ㅠㅠ|ㅜㅜ|♥|❤|♡|#[0-9A-Za-z가-힣_]+)")
EMOJI = re.compile("[\U0001F1E6-\U0001FAFF\u2600-\u27BF]")
NUMBERED_PROMISE = re.compile(r"(?P<count>\d+)\s*(?:가지|단계|기준|이유|방법|원칙|포인트)")
NUMERIC_CLAIM = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:년차|년|개월|일|시간|분|회|명|건|%|퍼센트)")


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).replace("\u200b", "").strip()


def compact(value: str) -> str:
    return re.sub(r"\s+", "", normalize(value))


def add(issues: list[dict[str, str]], code: str, detail: str) -> None:
    issues.append({"severity": "error", "code": code, "detail": detail})


def validate_title(
    title: str,
    *,
    evidence: str = "",
    answer_count: int | None = None,
    **_ignored: object,
) -> dict[str, object]:
    title = normalize(title)
    issues: list[dict[str, str]] = []
    if not title:
        add(issues, "title-empty", "제목이 비어 있습니다.")

    for code, pattern in FORBIDDEN.items():
        if match := pattern.search(title):
            add(issues, code, f"금지된 제목 표현: {match.group(0)}")
    for code, pattern in (("emoticon", EMOTICON), ("emoji", EMOJI)):
        if match := pattern.search(title):
            add(issues, code, f"장식 문자를 제거하세요: {match.group(0)}")

    promises = [int(match.group("count")) for match in NUMBERED_PROMISE.finditer(title)]
    if len(set(promises)) > 1:
        add(issues, "numbered-promise-ambiguous", f"제목에 서로 다른 답 개수가 함께 있습니다: {promises}")
    elif promises and promises[0] < 1:
        add(issues, "numbered-promise-unsupported", "제목의 답 개수는 1 이상의 정수여야 합니다.")

    if answer_count is None:
        add(issues, "answer-count-required", "--answer-count로 실제 번호 소제목 개수를 확인해야 합니다.")
    elif answer_count < 1:
        add(issues, "answer-count-unsupported", "실제 번호 소제목 개수는 1개 이상이어야 합니다.")
    elif promises and any(count != answer_count for count in promises):
        add(issues, "answer-count-mismatch", f"제목 약속 {promises}와 실제 답 {answer_count}개가 다릅니다.")

    evidence_compact = compact(evidence)
    for match in NUMERIC_CLAIM.finditer(title):
        claim = match.group(0)
        if compact(claim) not in evidence_compact:
            add(issues, "unsupported-title-number", f"내장 사실에서 확인되지 않은 수치: {claim}")

    errors = len(issues)
    return {
        "status": "fail" if errors else "pass",
        "metrics": {
            "nonWhitespaceChars": len(compact(title)),
            "answerPromises": promises,
            "answerCount": answer_count,
            "singleStructureContractId": "goldhand-single-information-delivery-structure-v1",
            "errors": errors,
            "warnings": 0,
        },
        "issues": issues,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--answer-count", type=int, required=True)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        evidence = args.evidence.read_text(encoding="utf-8") if args.evidence.exists() else ""
    except (OSError, UnicodeError) as exc:
        print(f"제목 근거를 읽지 못했습니다: {exc}", file=sys.stderr)
        return 2
    validation = validate_title(
        args.title,
        evidence=evidence,
        answer_count=args.answer_count,
    )
    if args.json:
        print(json.dumps(validation, ensure_ascii=False, indent=2))
    else:
        print(f"status: {validation['status']}")
        for issue in validation["issues"]:
            print(f"[ERROR] {issue['code']}: {issue['detail']}")
    return 1 if validation["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
