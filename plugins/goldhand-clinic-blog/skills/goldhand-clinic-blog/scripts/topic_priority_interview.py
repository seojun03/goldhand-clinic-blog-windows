#!/usr/bin/env python3
"""Prepare the topic interview and check user-input and review integrity.

These checks do not decide whether a priority is meaningful or central to prose.
The editor must make that judgment separately from the blind prose review.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import unicodedata
from pathlib import Path

COUNTS = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6,
          "일곱": 7, "여덟": 8, "아홉": 9, "열": 10}
PROMISE = re.compile(r"(?P<count>(?<![\d.])\d+|(?<![가-힣])(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉|열))\s*가지")


def prepare(topic: str, title: str) -> dict:
    if not topic.strip() or not title.strip():
        raise ValueError("사용자가 확정한 주제와 제목이 모두 필요합니다. 없는 값을 추정하지 마세요.")
    matches = [m.group("count") for m in PROMISE.finditer(unicodedata.normalize("NFKC", title))]
    counts = {int(value) if value.isdigit() else COUNTS[value] for value in matches}
    if len(counts) > 1 or any(count < 1 for count in counts):
        raise ValueError("제목의 답 개수가 충돌하거나 1보다 작습니다. 해당 개수만 사용자에게 확인하세요.")
    count = next(iter(counts), None)
    question = (f"'{topic}'에 대해 중요하게 생각하는 {count}가지가 무엇인가요?" if count else
                f"'{topic}'에 대해 중요하게 생각하는 내용은 무엇인가요?")
    return {"status": "awaiting-user-priorities", "topic": topic, "title": title,
            "answerCount": count, "question": question, "draftingAllowed": False,
            "productionAllowed": False}


def check_response(topic: str, title: str, receipt: dict) -> dict:
    result = prepare(topic, title)
    issues = []
    if not isinstance(receipt, dict):
        return {**result, "status": "needs-priority-clarification", "issues": ["interview-record-invalid"]}
    if receipt.get("topic") != topic or receipt.get("title") != title:
        issues.append("interview-topic-or-title-changed")
    response = receipt.get("userResponse")
    if not isinstance(response, str) or not response.strip():
        issues.append("user-response-missing")
        response = ""
    priorities = receipt.get("priorities")
    if not isinstance(priorities, list) or not priorities or any(not isinstance(p, str) or not p.strip() for p in priorities):
        issues.append("user-priorities-missing")
        priorities = []
    if priorities:
        if any(p not in response for p in priorities):
            issues.append("priority-not-in-user-response")
        positions = [response.find(p) for p in priorities]
        if positions != sorted(positions):
            issues.append("priority-order-changed")
        if len({re.sub(r"\s+", "", p) for p in priorities}) != len(priorities):
            issues.append("duplicate-user-priority")
    count = result["answerCount"]
    if count is not None and len(priorities) != count:
        issues.append("priority-count-mismatch")
    result.update(status="needs-priority-clarification" if issues else "ready-for-user-centered-draft",
                  answerCount=count if count is not None else len(priorities),
                  draftingAllowed=not issues, issues=issues)
    return result


def check_coverage(topic: str, title: str, receipt: dict, raw: str, review: dict, *, is_html: bool = False) -> dict:
    result = check_response(topic, title, receipt)
    if result["issues"]:
        return result
    path = Path(__file__).with_name("validate_title_alignment.py")
    spec = importlib.util.spec_from_file_location("goldhand_priority_prose", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = review.get("userPriorityReview") if isinstance(review, dict) else None
    issues = []
    if not isinstance(report, dict):
        issues.append("user-priority-review-missing")
        report = {}
    for field in ("topic", "title", "userResponse", "priorities"):
        if report.get(field) != receipt.get(field):
            issues.append("user-priority-review-stale-" + field)
    if report.get("bodySha256") != module.body_digest(raw, title, is_html):
        issues.append("user-priority-review-stale-prose")
    author, reviewer = report.get("draftAuthor"), report.get("reviewer")
    if not isinstance(author, str) or not author.strip() or not isinstance(reviewer, str) or not reviewer.strip() or author == reviewer:
        issues.append("user-priority-review-not-independent")
    sections = module.sections(raw, title, is_html)
    answers = report.get("answers")
    if not isinstance(answers, list):
        answers = []
    if len(sections) != result["answerCount"] or len(answers) != len(receipt["priorities"]):
        issues.append("user-priority-section-count-mismatch")
    for number, (priority, answer, section) in enumerate(zip(receipt["priorities"], answers, sections), 1):
        if not isinstance(answer, dict):
            issues.append("user-priority-answer-invalid")
            continue
        if answer.get("priority") != priority or answer.get("number") != number or section["number"] != number:
            issues.append("user-priority-answer-mapping")
        excerpt = answer.get("bodyExcerpt")
        if not isinstance(excerpt, str) or len(excerpt.strip()) < 8 or module.compact(excerpt) not in module.compact(section["body"]):
            issues.append("user-priority-body-excerpt")
        reason = answer.get("whyCentral")
        if not isinstance(reason, str) or len(reason.strip()) < 20:
            issues.append("user-priority-centrality-evidence")
    if report.get("verdict") != "pass" or report.get("unresolvedPriorities") != []:
        issues.append("user-priority-review-unresolved")
    return {**result, "status": "fail" if issues else "pass", "issues": issues,
            "productionAllowed": not issues, "mechanicalPassDoesNotProveCentrality": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--article", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--html", action="store_true")
    args = parser.parse_args()
    try:
        if (args.article or args.review or args.html) and not (args.input and args.article and args.review):
            raise ValueError("본문 검수에는 --input, --article, --review가 모두 필요합니다.")
        if args.article:
            result = check_coverage(args.topic, args.title, json.loads(args.input.read_text(encoding="utf-8")),
                                    args.article.read_text(encoding="utf-8"),
                                    json.loads(args.review.read_text(encoding="utf-8")), is_html=args.html)
        elif args.input:
            result = check_response(args.topic, args.title, json.loads(args.input.read_text(encoding="utf-8")))
        else:
            result = prepare(args.topic, args.title)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("issues") else 0
    except (ValueError, OSError, UnicodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
