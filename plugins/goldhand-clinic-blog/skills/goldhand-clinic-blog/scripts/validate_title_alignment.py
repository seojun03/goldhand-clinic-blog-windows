#!/usr/bin/env python3
"""Bind an independent title/answer review to the exact prose used in production.

This checks evidence and freshness, not semantic truth. The independent editor
must actually read the title and all prose. A hash or matching keywords cannot
decide whether an explanation answers the reader's question.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import re
import sys
from pathlib import Path

CONTRACT_ID = "goldhand-title-answer-alignment-v1"
ATTRIBUTE = "data-title-alignment"
INPUT_MODE = "title-and-final-plain-text-only"
SKILL_DIR = Path(__file__).resolve().parents[1]
HEADING = re.compile(r"(?m)^\s*(\d+)\s*[.．)\]]\s+([^\n]+)")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def prose(raw: str, title: str, is_html: bool = False) -> str:
    if is_html:
        articles = re.findall(r"<article\b[^>]*>(.*?)</article>", raw, re.I | re.S)
        if len(articles) != 1:
            raise ValueError("제목 검수에는 article 하나가 필요합니다.")
        raw = articles[0]
        # Only the fixed clinic credential table is outside spoken prose.
        # A substantive table elsewhere must remain bound to the review too.
        raw = re.sub(r"<table\b(?=[^>]*\bdata-native-table-purpose\s*=\s*['\"]credential['\"])[^>]*>.*?</table>", "", raw, flags=re.I | re.S)
        raw = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", raw, flags=re.I | re.S)
        raw = re.sub(r"<br\b[^>]*>|</?(?:p|div|section|h[1-6]|blockquote|li|figure)\b[^>]*>", "\n", raw, flags=re.I)
        raw = html.unescape(re.sub(r"<[^>]+>", "", raw))
    else:
        lines = raw.splitlines()
        if not lines or lines[0] != title:
            raise ValueError("평문 첫 줄은 확정 제목과 글자 그대로 같아야 합니다.")
        proof = json.loads((SKILL_DIR / "assets/goldhand-value-proof-library.json").read_text(encoding="utf-8"))
        skip = {f"[{proof['headerText']}]", *proof["fixedRows"]}
        raw = "\n".join(re.sub(r"^\s*>\s?", "", line) for line in lines[1:] if line.strip() not in skip)
    return "\n".join(line.strip() for line in raw.splitlines() if line.strip())


def body_digest(raw: str, title: str, is_html: bool = False) -> str:
    # Ignore layout whitespace only; preserve title, words, order and punctuation.
    return hashlib.sha256((title + "\0" + compact(prose(raw, title, is_html))).encode("utf-8")).hexdigest()


def sections(raw: str, title: str, is_html: bool = False) -> list[dict]:
    text = prose(raw, title, is_html)
    matches = list(HEADING.finditer(text))
    return [{"number": int(m.group(1)), "heading": m.group(0).strip(),
             "body": text[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)].strip()}
            for i, m in enumerate(matches)]


def answer_type(title: str) -> str:
    if re.search(r"이유|원인", title):
        return "reason"
    if re.search(r"습관|방법|대처|해야|관리법|운동법", title):
        return "action"
    if re.search(r"신호|증상|차이|구별|확인", title):
        return "check"
    return "explanation"


def describe(raw: str, title: str, is_html: bool = False) -> dict:
    """Return an UNREVIEWED skeleton. Never manufacture review findings."""
    return {"schemaVersion": 1, "contractId": CONTRACT_ID, "title": title,
            "bodySha256": body_digest(raw, title, is_html),
            "draftAuthor": "", "reviewer": "", "reviewerInputMode": INPUT_MODE,
            "titleSubject": "", "titleQuestion": "", "answerType": answer_type(title),
            "premiseCheck": "", "wholeBodyCheck": "", "distinctionCheck": "",
            "answers": [{"number": s["number"], "heading": s["heading"],
                         "directAnswerExcerpt": "", "whyThisAnswersTitle": ""}
                        for s in sections(raw, title, is_html)],
            "offTopicPassages": [], "verdict": "pending"}


def embedded_review(raw: str) -> dict | None:
    opening = re.search(r"<article\b[^>]*>", raw, re.I | re.S)
    values = re.findall(rf"\b{ATTRIBUTE}\s*=\s*(['\"])(.*?)\1", opening.group(0) if opening else "", re.I | re.S)
    if len(values) != 1:
        return None
    try:
        result = json.loads(base64.b64decode(html.unescape(values[0][1]), validate=True).decode("utf-8"))
    except (ValueError, UnicodeError):
        return None
    return result if isinstance(result, dict) else None


def validate(raw: str, title: str, review: dict | None = None, *, is_html: bool = False) -> dict:
    issues = []
    def error(code: str, detail: str) -> None:
        issues.append({"severity": "error", "code": code, "detail": detail})
    if review is None and is_html:
        review = embedded_review(raw)
    if isinstance(review, dict) and "titleAlignment" in review:
        review = review["titleAlignment"]
    if not isinstance(review, dict):
        error("title-review-missing", "제목과 최종 평문을 별도로 읽은 검수 기록이 없습니다.")
        return {"status": "fail", "issues": issues, "mechanicalPassDoesNotProveAlignment": True}
    if review.get("schemaVersion") != 1 or review.get("contractId") != CONTRACT_ID:
        error("title-review-contract", "제목-답변 검수 기록의 형식이 다릅니다.")
    if review.get("title") != title:
        error("title-review-title-changed", "다른 제목의 검수 기록을 재사용할 수 없습니다.")
    try:
        current_digest = body_digest(raw, title, is_html)
        actual_sections = sections(raw, title, is_html)
    except ValueError as exc:
        error("title-review-input", str(exc))
        current_digest, actual_sections = "", []
    if review.get("bodySha256") != current_digest:
        error("title-review-stale-prose", "검수한 본문과 현재 본문이 다릅니다. 제목만 바꾸거나 다른 글을 붙이지 말고 다시 검수하세요.")
    author, reviewer = review.get("draftAuthor"), review.get("reviewer")
    if not isinstance(author, str) or not isinstance(reviewer, str) or not author.strip() or not reviewer.strip() or author == reviewer:
        error("title-review-not-independent", "초안 작성자와 실제 독립 검수자 식별값이 필요합니다.")
    if review.get("reviewerInputMode") != INPUT_MODE:
        error("title-review-input-mode", "검수자에게 확정 제목과 최종 평문만 전달하세요.")
    for field, minimum in (("titleSubject", 2), ("titleQuestion", 10), ("premiseCheck", 30), ("wholeBodyCheck", 50), ("distinctionCheck", 30)):
        if not isinstance(review.get(field), str) or len(review[field].strip()) < minimum:
            error("title-review-evidence", f"{field}: 제목의 조건과 실제 문단에 근거한 구체 검수 기록이 필요합니다.")
    if review.get("answerType") != answer_type(title):
        error("title-review-answer-type", "이유를 묻는 제목에 관리법만 쓰는 등 답의 종류를 바꿀 수 없습니다.")
    answers = review.get("answers")
    if not isinstance(answers, list):
        answers = []
    if not actual_sections or len(answers) != len(actual_sections):
        error("title-review-answer-count", "모든 번호 답을 각각 검수해야 합니다.")
    count = re.search(r"(\d+)\s*가지", title)
    if count and len(actual_sections) != int(count.group(1)):
        error("title-review-title-count", "제목이 약속한 개수와 실제 답 개수가 다릅니다.")
    excerpts = []
    for section, answer in zip(actual_sections, answers):
        if not isinstance(answer, dict):
            error("title-review-answer-shape", "번호별 검수 기록은 객체여야 합니다.")
            continue
        if answer.get("number") != section["number"] or compact(str(answer.get("heading", ""))) != compact(section["heading"]):
            error("title-review-heading-changed", f"{section['number']}번 소제목이 검수 기록과 다릅니다.")
        excerpt = str(answer.get("directAnswerExcerpt", "")).strip()
        if len(excerpt) < 8 or compact(excerpt) not in compact(section["body"]):
            error("title-review-answer-excerpt", f"{section['number']}번 설명 안에 있는 직접 답 문장을 인용해야 합니다.")
        if len(str(answer.get("whyThisAnswersTitle", "")).strip()) < 30:
            error("title-review-answer-reason", f"{section['number']}번이 제목의 조건에 어떻게 답하는지 설명해야 합니다.")
        excerpts.append(compact(excerpt))
    if len(set(excerpts)) != len(excerpts):
        error("title-review-repeated-answer", "같은 직접 답을 나눠 제목 숫자를 채울 수 없습니다.")
    if review.get("verdict") != "pass" or review.get("offTopicPassages") != []:
        error("title-review-unresolved", "제목에 답하지 않는 문단이 남아 있거나 검수가 끝나지 않았습니다.")
    return {"status": "fail" if issues else "pass", "issues": issues,
            "mechanicalPassDoesNotProveAlignment": True,
            "metrics": {"reviewedAnswers": len(answers), "bodySha256": current_digest}}


def attach(raw: str, title: str, review: dict) -> str:
    review = review.get("titleAlignment", review)
    result = validate(raw, title, review, is_html=True)
    if result["status"] != "pass":
        raise ValueError(" / ".join(i["detail"] for i in result["issues"]))
    encoded = base64.b64encode(json.dumps(review, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).decode("ascii")
    def replace(match: re.Match) -> str:
        opening = re.sub(rf"\s+{ATTRIBUTE}\s*=\s*(['\"]).*?\1", "", match.group(0), flags=re.I | re.S)
        return opening[:-1] + f' {ATTRIBUTE}="{encoded}">'
    return re.sub(r"<article\b[^>]*>", replace, raw, count=1, flags=re.I | re.S)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--html", action="store_true")
    parser.add_argument("--describe", action="store_true", help="미검수 필드와 실제 본문 해시를 출력; 통과 판정 아님")
    parser.add_argument("--attach-output", type=Path, help="통과 기록을 HTML에 결합; --html 및 --review 필요")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        raw = args.input.read_text(encoding="utf-8")
        if args.describe:
            print(json.dumps(describe(raw, args.title, args.html), ensure_ascii=False, indent=2))
            return 0
        review = json.loads(args.review.read_text(encoding="utf-8")) if args.review else None
        result = validate(raw, args.title, review, is_html=args.html)
        if args.attach_output:
            if not args.html or not isinstance(review, dict):
                raise ValueError("결합에는 --html과 --review가 필요합니다.")
            if result["status"] == "pass":
                args.attach_output.write_text(attach(raw, args.title, review), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result["status"] == "fail" else 0
    except (OSError, ValueError, UnicodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
