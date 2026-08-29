#!/usr/bin/env python3
"""Validate the one allowed Goldhand information-article structure."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = SKILL_DIR / "assets" / "information-delivery-structure-contract.json"
DEFAULT_VALUE_PROOF = SKILL_DIR / "assets" / "goldhand-value-proof-library.json"

NUMBERED_PROMISE = re.compile(r"(?P<count>\d+)\s*(?:가지|단계|기준|이유|방법|원칙|포인트)")
NUMBERED_HEADING = re.compile(r"(?m)^\s*(?P<count>\d+)\s*[.．)\]]\s+(?P<text>\S.+?)\s*$")
PAYOFF_CUE = re.compile(r"(?:알\s*수|이해|구분|판단|확인|피할|줄일|놓치지|무엇부터|어떻게|도움)")
CTA_CUE = re.compile(r"(?:진료|진단|검사|의료진|함께\s*(?:확인|살펴|정해))")
AGGRESSIVE_CTA = re.compile(r"(?:지금\s*바로|당장|늦기\s*전에|서둘러|반드시\s*내원|꼭\s*내원)")
HELPFUL_WISH_CUE = re.compile(
    r"도움[이가]?\s*(?:(?:되셨길|되었길|됐길|되기를|되었기를|됐기를).{0,16}(?:바랍니다|좋겠습니다)|(?:되셨으면|되었으면|됐으면)\s*(?:합니다|좋겠습니다))"
)
THANKS_CUE = re.compile(
    r"(?:(?:읽어|함께해)\s*주셔서|읽어\s*주신\s*(?:분들께|데))"
    r"[^.!?\n]{0,30}(?:감사(?:합니다|드립니다)|고맙습니다)"
)
GENERAL_INFORMATION_CUE = re.compile(r"일반적인\s*(?:내용|정보|기준|설명)")
DIRECT_EVALUATION_CUE = re.compile(
    r"(?:직접\s*(?:진료|진단|검사)(?:를)?\s*(?:받|해)|(?:진료|진단|검사)를\s*받아|의료진(?:에게|과)\s*(?:진료|상담|확인))"
)
REFERENCE_CUE = re.compile(
    r"(?:참고(?:하신다면|하셔도)|기억해\s*두(?:신다면|셔도)|"
    r"알아\s*두(?:신다면|셔도)|챙겨\s*보(?:신다면|셔도))"
)
CLOSING_BENEFIT_CUE = re.compile(
    r"(?:알\s*수|이해|구분|판단|분명|쉬워|수월|피할|줄일|놓치지|덜\s*헤매|무엇부터|어떻게|도움|실수)"
)
BRANDED_CLOSING_CUE = re.compile(
    r"(?:금손\s*한의원|저희\s*(?:한의원|병원)|[가-힣0-9]{2,}(?:동|읍|면|구|시)\s*한의원)"
)
DIRECT_SALES_CLOSING_CUE = re.compile(
    r"(?:예약|문의|대표\s*번호|전화\s*(?:주|하|해|를)|연락\s*(?:주|하|해)|찾아오|오시는\s*길|내원)"
)
NATIVE_COUNT_WORDS = {
    1: "한",
    2: "두",
    3: "세",
    4: "네",
    5: "다섯",
    6: "여섯",
    7: "일곱",
    8: "여덟",
    9: "아홉",
    10: "열",
}
FORBIDDEN_EXTRA_HEADING = re.compile(
    r"^(?:FAQ|Q\s*&\s*A|자주\s*묻는\s*질문|추가\s*조언|주의사항|위험\s*신호|마지막으로|함께\s*읽으면\s*좋은\s*글|운영\s*정보)$",
    re.I,
)
PUNCTUATED_EXTRA_HEADING = re.compile(
    r"^(?=.*(?:보너스|추가|주의|확인|관리법|정리|팁|방법|위험|알아둘|기억할)).{1,60}(?:입니다|이에요|예요)[.!?]?$",
    re.I,
)


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff]", "", value)
    return value.strip()


def compact(value: str) -> str:
    return re.sub(r"\s+", "", normalize(value))


def visible_text(value: str) -> str:
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<br\b[^>]*>", "\n", value, flags=re.I)
    value = re.sub(r"</?(?:p|div|section|header|footer|article|h[1-6]|blockquote|li|tr|td|th|table|hr)\b[^>]*>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return normalize(html.unescape(value))


def add(issues: list[dict[str, str]], code: str, detail: str) -> None:
    issues.append({"severity": "error", "code": code, "detail": detail})


def promised_count(title: str) -> int | None:
    values = [int(match.group("count")) for match in NUMBERED_PROMISE.finditer(title)]
    if not values or len(set(values)) != 1:
        return None
    return values[0]


def paragraph_blocks(value: str) -> list[str]:
    return [re.sub(r"\s+", " ", part).strip() for part in re.split(r"\n\s*\n+", value) if compact(part)]


def looks_like_unnumbered_plain_heading(block: str) -> bool:
    value = re.sub(r"\s+", " ", block).strip()
    if not value or NUMBERED_HEADING.fullmatch(value):
        return False
    if "\n" in block or len(value) > 80:
        return False
    if re.search(r"[.!?]$", value) is None:
        return True
    return PUNCTUATED_EXTRA_HEADING.fullmatch(value) is not None


def meaningful_html_gap(fragment: str) -> bool:
    value = re.sub(r"<!--.*?-->", "", fragment, flags=re.S)
    value = re.sub(r"</?(?:div|section|main)\b[^>]*>", "", value, flags=re.I)
    if compact(visible_text(value)):
        return True
    return re.search(r"<(?:img|figure|table|blockquote|p|h[1-6]|ul|ol|li|hr)\b", value, flags=re.I) is not None


def exact_value_proof_lines(library: dict[str, Any]) -> list[str]:
    heading = str(library.get("headerText", "")).strip()
    rows = library.get("fixedRows", [])
    if not heading or not isinstance(rows, list) or not rows:
        raise ValueError("금손한의원 소개 표 계약이 비어 있습니다.")
    return [f"[{heading}]", *[str(row).strip() for row in rows]]


def mentions_promised_count(value: str, promise: int | None) -> bool:
    if promise is None:
        return False
    forms = [rf"{promise}\s*가지"]
    native = NATIVE_COUNT_WORDS.get(promise)
    if native:
        forms.append(rf"{re.escape(native)}\s*가지")
    return re.search(rf"(?:{'|'.join(forms)})", value) is not None


def closing_thanks_at_end(value: str) -> bool:
    match = THANKS_CUE.search(value)
    if match is None:
        return False
    return re.fullmatch(r"\s*[.!?]?\s*", value[match.end() :]) is not None


def validate_closing_flow(
    summary_text: str,
    cta_text: str,
    promise: int | None,
    contract: dict[str, Any],
    issues: list[dict[str, str]],
) -> str | None:
    """Validate the two allowed sentence flows inside the fixed summary -> CTA blocks."""

    summary = re.sub(r"\s+", " ", normalize(summary_text))
    cta = re.sub(r"\s+", " ", normalize(cta_text))
    closing_contract = contract.get("closing", {})
    expected_thanks = int(closing_contract.get("gratitudeCount", 1))
    thanks_count = len(THANKS_CUE.findall(f"{summary}\n{cta}"))
    if thanks_count != expected_thanks:
        add(
            issues,
            "closing-gratitude-count",
            f"마무리에는 문맥에 맞게 새로 쓴 감사의 뜻이 정확히 {expected_thanks}번 필요합니다. 현재 {thanks_count}번입니다.",
        )

    summary_help = HELPFUL_WISH_CUE.search(summary)
    summary_thanks = THANKS_CUE.search(summary)
    cta_general = GENERAL_INFORMATION_CUE.search(cta)
    cta_direct = DIRECT_EVALUATION_CUE.search(cta)
    branded_match = BRANDED_CLOSING_CUE.search(f"{summary}\n{cta}")
    sales_match = DIRECT_SALES_CLOSING_CUE.search(f"{summary}\n{cta}")

    if branded_match:
        add(
            issues,
            "branded-closing-cta",
            f"마무리에는 특정 병원명이나 지역 한의원 키워드를 넣지 않습니다: {branded_match.group(0)}",
        )
    if sales_match:
        add(
            issues,
            "sales-closing-cta",
            f"마무리에는 예약·문의·전화·내원 유도를 넣지 않습니다: {sales_match.group(0)}",
        )

    flow_a = bool(
        summary_help
        and summary_thanks
        and summary_help.start() < summary_thanks.start()
        and closing_thanks_at_end(summary)
        and cta_general
        and cta_direct
        and cta_general.start() < cta_direct.start()
        and thanks_count == expected_thanks
        and not branded_match
        and not sales_match
    )
    if flow_a:
        return "helpful-then-thanks-then-direct-evaluation"

    reference = REFERENCE_CUE.search(summary)
    count_matches = mentions_promised_count(summary, promise)
    benefit_after_reference = bool(
        reference and CLOSING_BENEFIT_CUE.search(summary[reference.end() :])
    )
    cta_thanks = THANKS_CUE.search(cta)
    flow_b = bool(
        reference
        and count_matches
        and benefit_after_reference
        and cta_direct
        and cta_thanks
        and cta_direct.start() < cta_thanks.start()
        and closing_thanks_at_end(cta)
        and thanks_count == expected_thanks
        and not branded_match
        and not sales_match
    )
    if flow_b:
        return "n-points-benefit-then-next-step-then-thanks"

    if reference and not count_matches:
        add(
            issues,
            "closing-title-count-mismatch",
            "마무리에서 회수한 n가지는 제목에서 약속한 답 개수와 같아야 합니다.",
        )
    add(
        issues,
        "closing-flow-unrecognized",
        "마무리는 A(주제별 도움 인사 → 새로 쓴 감사 → 일반 정보 경계 → 중립적인 직접 확인 권유) 또는 B(제목과 같은 n가지의 이득·피할 실수 → 중립적인 직접 확인 권유 → 새로 쓴 감사) 역할을 해야 합니다.",
    )
    return None


def validate_plain(
    raw: str,
    title: str,
    contract: dict[str, Any],
    value_proof: dict[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    value = normalize(raw)
    lines = [line.rstrip() for line in value.splitlines()]
    nonempty = [(index, line.strip()) for index, line in enumerate(lines) if line.strip()]
    if not nonempty:
        add(issues, "article-empty", "평문이 비어 있습니다.")
        return result(issues, title, 0, 0, [], None)

    first_index, first_line = nonempty[0]
    if first_line != title:
        add(issues, "title-first", "평문의 첫 줄은 확정 제목과 정확히 같아야 합니다.")

    proof_lines = exact_value_proof_lines(value_proof)
    marker = proof_lines[0]
    marker_indices = [index for index, line in nonempty if line == marker]
    if len(marker_indices) != 1:
        add(issues, "value-proof-count", f"{marker} 블록은 정확히 한 번 필요합니다.")
        proof_start = len(lines)
        proof_end = len(lines)
    else:
        proof_start = marker_indices[0]
        expected = [line.strip() for line in lines[proof_start : proof_start + len(proof_lines)]]
        if expected != proof_lines:
            add(issues, "value-proof-rows", "금손한의원 소개 표의 고정 행과 순서가 다릅니다.")
        proof_end = proof_start + len(proof_lines)

    quote_lines = [
        line.strip()[1:].strip().strip('"“”')
        for line in lines[first_index + 1 : proof_start]
        if line.strip().startswith(">")
    ]
    minimum = int(contract.get("readerEmpathyQuotes", {}).get("minimum", 2))
    if len(quote_lines) < minimum:
        add(issues, "reader-question-count", f"제목 뒤 공감 질문은 {minimum}개 이상이어야 합니다. 현재 {len(quote_lines)}개입니다.")
    for index, question in enumerate(quote_lines, start=1):
        if not question.endswith("?"):
            add(issues, "reader-question-form", f"공감 인용구 {index}은 실제 질문으로 끝나야 합니다.")
    unexpected_intro = [
        line.strip()
        for line in lines[first_index + 1 : proof_start]
        if line.strip() and not line.strip().startswith(">")
    ]
    if unexpected_intro:
        add(issues, "content-before-value-proof", "제목과 금손한의원 소개 표 사이에는 공감 질문 인용구만 둘 수 있습니다.")
        if any(re.search(r"3\s*분", line) for line in unexpected_intro):
            add(
                issues,
                "value-proof-before-solution-preview",
                "금손한의원 소개 표는 3분 해결 예고보다 앞에 있어야 합니다.",
            )

    headings = list(NUMBERED_HEADING.finditer(value))
    heading_numbers = [int(match.group("count")) for match in headings]
    first_heading_start = headings[0].start() if headings else len(value)
    proof_end_offset = sum(len(line) + 1 for line in lines[:proof_end])
    solution_text = value[proof_end_offset:first_heading_start].strip()
    if not solution_text:
        add(issues, "solution-preview-missing", "금손한의원 소개 표 뒤에 3분 해결 예고가 필요합니다.")
    else:
        solution_blocks = paragraph_blocks(solution_text)
        if len(solution_blocks) != 1:
            add(issues, "solution-preview-paragraph-count", "금손한의원 소개 표와 첫 번호 소제목 사이에는 3분 해결 예고 한 문단만 둘 수 있습니다.")
        if not re.search(r"3\s*분", solution_text):
            add(issues, "three-minute-hook-missing", "해결 예고에는 3분의 읽기 부담이 보여야 합니다.")
        if not PAYOFF_CUE.search(solution_text):
            add(issues, "reader-payoff-missing", "해결 예고에는 얻을 이득 또는 피할 손실이 구체적으로 보여야 합니다.")

    promise = promised_count(title)
    if promise is None:
        add(issues, "title-number-promise-missing", "확정 제목에는 서로 다른 답의 개수가 필요합니다.")
    elif promise < int(contract.get("numberedAnswers", {}).get("minimumCount", 1)):
        add(issues, "title-number-promise-unsupported", "확정 제목의 답 개수는 1 이상의 정수여야 합니다.")
    expected_numbers = list(range(1, (promise or 0) + 1))
    if heading_numbers != expected_numbers:
        add(issues, "numbered-answer-mismatch", f"번호 소제목은 {expected_numbers}여야 하지만 현재 {heading_numbers}입니다.")

    for index, heading in enumerate(headings[:-1]):
        body = value[heading.end() : headings[index + 1].start()]
        if not paragraph_blocks(body):
            add(issues, "numbered-answer-body-missing", f"{heading_numbers[index]}번 소제목 아래 설명이 없습니다.")

    last_heading_end = headings[-1].end() if headings else len(value)
    tail_blocks = paragraph_blocks(value[last_heading_end:])
    summary_text = ""
    if len(tail_blocks) < 3:
        add(issues, "summary-and-cta-missing", "마지막 번호 소제목의 설명 뒤에는 글 전체 정리와 CTA가 각각 별도 문단으로 필요합니다.")
        cta_text = tail_blocks[-1] if tail_blocks else ""
    else:
        summary_text = tail_blocks[-2]
        cta_text = tail_blocks[-1]
        if len(compact(summary_text)) < 12:
            add(issues, "closing-summary-too-short", "마지막에서 두 번째 문단은 본문의 답을 짧게 정리해야 합니다.")
    if cta_text and not CTA_CUE.search(cta_text):
        add(issues, "cta-cue-missing", "마지막 문단에는 부담 없는 진료·상담 다음 행동이 보여야 합니다.")
    if AGGRESSIVE_CTA.search(cta_text):
        add(issues, "aggressive-cta", "CTA에서 방문을 압박하면 안 됩니다.")
    closing_flow = None
    if summary_text and cta_text:
        closing_flow = validate_closing_flow(
            summary_text,
            cta_text,
            promise,
            contract,
            issues,
        )

    structural_text = value[proof_end_offset:]
    for block in paragraph_blocks(structural_text):
        if looks_like_unnumbered_plain_heading(block):
            add(issues, "unnumbered-main-heading", f"번호가 없는 추가 소제목이 있습니다: {block[:60]}")

    for line in lines:
        if FORBIDDEN_EXTRA_HEADING.fullmatch(line.strip()):
            add(issues, "forbidden-extra-section", f"단일 구조 밖의 추가 섹션이 있습니다: {line.strip()}")

    return result(issues, title, len(quote_lines), len(headings), heading_numbers, closing_flow)


def role_matches(article: str, role: str) -> list[re.Match[str]]:
    pattern = re.compile(
        rf"<(?P<tag>[a-z][\w:-]*)\b(?=[^>]*\bdata-reference-role\s*=\s*['\"]{re.escape(role)}['\"])[^>]*>.*?</(?P=tag)>",
        re.I | re.S,
    )
    return list(pattern.finditer(article))


def credential_matches(article: str) -> list[re.Match[str]]:
    return list(re.finditer(
        r"<table\b(?=[^>]*\bdata-native-table-purpose\s*=\s*['\"]credential['\"])[^>]*>.*?</table>",
        article,
        flags=re.I | re.S,
    ))


def validate_html(
    raw: str,
    title: str,
    contract: dict[str, Any],
    value_proof: dict[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    article_matches = list(re.finditer(r"<article\b[^>]*>.*?</article>", raw, flags=re.I | re.S))
    if len(article_matches) != 1:
        add(issues, "article-count", "HTML에는 article 요소가 정확히 하나 있어야 합니다.")
        article = raw
    else:
        article = article_matches[0].group(0)

    questions = role_matches(article, "reader-question")
    credentials = credential_matches(article)
    solutions = role_matches(article, "solution-preview")
    headings = role_matches(article, "section-heading")
    summaries = role_matches(article, "closing-summary")
    ctas = role_matches(article, "cta")

    minimum = int(contract.get("readerEmpathyQuotes", {}).get("minimum", 2))
    if len(questions) < minimum:
        add(issues, "reader-question-count", f"공감 인용구는 {minimum}개 이상이어야 합니다.")
    if len(credentials) != 1:
        add(issues, "value-proof-count", "금손한의원 소개 표는 정확히 한 번 필요합니다.")
    if len(solutions) != 1:
        add(issues, "solution-preview-count", "3분 해결 예고는 정확히 한 번 필요합니다.")
    if len(summaries) != 1:
        add(issues, "closing-summary-count", "글 전체 정리는 정확히 한 번 필요합니다.")
    if len(ctas) != 1:
        add(issues, "cta-count", "CTA는 정확히 한 번 필요합니다.")

    blocks = [*questions, *credentials, *solutions, *headings, *summaries, *ctas]
    if blocks and all((questions, credentials, solutions, headings, summaries, ctas)):
        ordered = [match.start() for match in blocks]
        if ordered != sorted(ordered):
            add(issues, "block-order", "HTML 블록 순서는 공감 → 가치입증 → 3분 해결 예고 → 번호 답 → 정리 → CTA여야 합니다.")

        prefix = [*questions, credentials[0], solutions[0], headings[0]]
        article_open_end = article.find(">") + 1
        cursor = article_open_end
        for block in prefix:
            if meaningful_html_gap(article[cursor:block.start()]):
                add(issues, "unexpected-block-before-numbered-answers", "공감·소개 표·3분 해결 예고·첫 번호 소제목 사이에 다른 글 블록을 둘 수 없습니다.")
                break
            cursor = block.end()

        for index, heading in enumerate(headings):
            boundary = headings[index + 1] if index + 1 < len(headings) else summaries[0]
            if not compact(visible_text(article[heading.end() : boundary.start()])):
                add(issues, "numbered-answer-body-missing", f"{index + 1}번 소제목 아래 설명이 없습니다.")

        answer_ranges = [
            (
                heading.end(),
                headings[index + 1].start() if index + 1 < len(headings) else summaries[0].start(),
            )
            for index, heading in enumerate(headings)
        ]
        for image in re.finditer(r"<img\b[^>]*>", article, flags=re.I | re.S):
            if not any(start <= image.start() < end for start, end in answer_ranges):
                add(
                    issues,
                    "image-outside-numbered-answer",
                    "승인 뒤 추가하는 이미지는 번호 소제목의 설명 안에만 둘 수 있습니다.",
                )

        if meaningful_html_gap(article[summaries[0].end() : ctas[0].start()]):
            add(issues, "content-between-summary-and-cta", "글 전체 정리와 CTA 사이에는 다른 글 블록을 둘 수 없습니다.")

    question_texts = [re.sub(r"\s+", " ", visible_text(match.group(0))).strip() for match in questions]
    for index, question in enumerate(question_texts, start=1):
        if not question.endswith("?"):
            add(issues, "reader-question-form", f"공감 인용구 {index}은 질문으로 끝나야 합니다.")

    if len(credentials) == 1:
        proof_text = compact(visible_text(credentials[0].group(0)))
        for expected in [str(value_proof.get("headerText", "")), *value_proof.get("fixedRows", [])]:
            if compact(str(expected)) not in proof_text:
                add(issues, "value-proof-rows", f"금손한의원 소개 표에서 고정 문구가 빠졌습니다: {expected}")

    if len(solutions) == 1:
        solution_text = visible_text(solutions[0].group(0))
        if not re.search(r"3\s*분", solution_text):
            add(issues, "three-minute-hook-missing", "해결 예고에는 3분이 보여야 합니다.")
        if not PAYOFF_CUE.search(solution_text):
            add(issues, "reader-payoff-missing", "해결 예고에는 구체적 이득 또는 피할 손실이 필요합니다.")

    heading_numbers: list[int] = []
    for match in headings:
        text = re.sub(r"\s+", " ", visible_text(match.group(0))).strip()
        number = re.match(r"(?P<count>\d+)\s*[.．)\]]\s+", text)
        if not number:
            add(issues, "unnumbered-main-heading", f"번호가 없는 주요 소제목이 있습니다: {text[:60]}")
        else:
            heading_numbers.append(int(number.group("count")))

    all_headings = list(re.finditer(r"<h[1-6]\b[^>]*>.*?</h[1-6]>", article, flags=re.I | re.S))
    if len(all_headings) != len(headings):
        add(issues, "unnumbered-main-heading", "번호 답 역할이 없는 추가 HTML 소제목을 둘 수 없습니다.")
    all_tables = list(re.finditer(r"<table\b[^>]*>.*?</table>", article, flags=re.I | re.S))
    if len(all_tables) != 1:
        add(issues, "extra-table", "금손한의원 소개 표 외의 표를 추가할 수 없습니다.")
    allowed_roles = {"reader-question", "solution-preview", "section-heading", "closing-summary", "cta"}
    found_roles = set(re.findall(r"\bdata-reference-role\s*=\s*['\"]([^'\"]+)['\"]", article, flags=re.I))
    unknown_roles = sorted(found_roles - allowed_roles)
    if unknown_roles:
        add(issues, "unknown-structure-role", f"단일 구조에 없는 역할이 있습니다: {unknown_roles}")
    for container in re.finditer(r"<(?:section|aside|header|footer|nav)\b(?P<attrs>[^>]*)>", article, flags=re.I):
        role_match = re.search(
            r"\bdata-reference-role\s*=\s*['\"]([^'\"]+)['\"]",
            container.group("attrs"),
            flags=re.I,
        )
        role = role_match.group(1) if role_match else ""
        if role not in {"closing-summary", "cta"}:
            add(
                issues,
                "extra-structural-container",
                "번호 답 안팎에 역할 없는 section·aside·header·footer·nav 블록을 추가할 수 없습니다.",
            )
    promise = promised_count(title)
    expected_numbers = list(range(1, (promise or 0) + 1))
    if promise is None:
        add(issues, "title-number-promise-missing", "확정 제목에는 답 개수가 필요합니다.")
    elif heading_numbers != expected_numbers:
        add(issues, "numbered-answer-mismatch", f"번호 소제목은 {expected_numbers}여야 하지만 현재 {heading_numbers}입니다.")

    closing_flow = None
    if len(summaries) == 1 and len(ctas) == 1:
        closing_flow = validate_closing_flow(
            visible_text(summaries[0].group(0)),
            visible_text(ctas[0].group(0)),
            promise,
            contract,
            issues,
        )

    if len(ctas) == 1:
        cta_text = visible_text(ctas[0].group(0))
        if not CTA_CUE.search(cta_text):
            add(issues, "cta-cue-missing", "CTA에는 부담 없는 진료·상담 다음 행동이 보여야 합니다.")
        if AGGRESSIVE_CTA.search(cta_text):
            add(issues, "aggressive-cta", "CTA에서 방문을 압박하면 안 됩니다.")
        tail = article[ctas[0].end() :]
        tail = re.sub(r"<!--.*?-->|</?(?:article|section|div)\b[^>]*>", "", tail, flags=re.I | re.S)
        if meaningful_html_gap(tail):
            add(issues, "content-after-cta", "CTA 뒤에는 다른 글 블록을 둘 수 없습니다.")

    return result(issues, title, len(questions), len(headings), heading_numbers, closing_flow)


def result(
    issues: list[dict[str, str]],
    title: str,
    question_count: int,
    heading_count: int,
    heading_numbers: list[int],
    closing_flow: str | None,
) -> dict[str, Any]:
    return {
        "status": "fail" if issues else "pass",
        "contractId": "goldhand-single-information-delivery-structure-v1",
        "metrics": {
            "title": title,
            "readerQuestionCount": question_count,
            "numberedHeadingCount": heading_count,
            "numberedHeadingNumbers": heading_numbers,
            "closingFlow": closing_flow,
            "errors": len(issues),
        },
        "issues": issues,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--html", action="store_true")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--value-proof", type=Path, default=DEFAULT_VALUE_PROOF)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        raw = args.input.read_text(encoding="utf-8")
        contract = json.loads(args.contract.read_text(encoding="utf-8"))
        value_proof = json.loads(args.value_proof.read_text(encoding="utf-8"))
        if not isinstance(contract, dict) or not isinstance(value_proof, dict):
            raise ValueError("구조 계약과 가치입증 계약은 JSON 객체여야 합니다.")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"정보전달형 구조 검증 입력을 읽지 못했습니다: {exc}", file=sys.stderr)
        return 2

    validation = (
        validate_html(raw, normalize(args.title), contract, value_proof)
        if args.html
        else validate_plain(raw, normalize(args.title), contract, value_proof)
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
