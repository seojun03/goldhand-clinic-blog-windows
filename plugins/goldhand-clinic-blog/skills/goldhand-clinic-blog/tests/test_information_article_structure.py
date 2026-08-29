from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "validate_information_article_structure.py"


def load_module():
    spec = importlib.util.spec_from_file_location("information_structure", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = load_module()
CONTRACT = json.loads((SKILL_DIR / "assets" / "information-delivery-structure-contract.json").read_text(encoding="utf-8"))
PROOF = json.loads((SKILL_DIR / "assets" / "goldhand-value-proof-library.json").read_text(encoding="utf-8"))
TITLE = "요요를 막으려면 바꿔야 할 습관 2가지"


def proof_block() -> str:
    return "\n".join([f"[{PROOF['headerText']}]", *PROOF["fixedRows"]])


def valid_plain() -> str:
    return f"""{TITLE}

> 살을 뺐는데 조금만 먹어도 다시 찌는 이유가 뭘까요?
> 다이어트가 끝난 뒤에는 어떻게 먹어야 요요가 덜 올까요?

{proof_block()}

3분만 읽어보셔도 왜 다시 찌는지, 무엇부터 바꿔야 하는지 알 수 있습니다.

1. 굶다시피 빼고 갑자기 예전만큼 먹지 마세요

먹는 양을 너무 줄였다면 천천히 늘려야 합니다.

2. 다이어트할 때 지킨 생활을 한꺼번에 놓지 마세요

야식과 수면, 운동을 함께 살펴야 합니다.

살을 뺀 뒤 다시 찌는 이유를 이해하는 데 오늘 글이 조금이나마 도움이 되었기를 바랍니다. 긴 글 읽어주셔서 진심으로 감사드립니다.

다만 이 글은 요요가 생기는 이유를 이해하기 위한 일반적인 설명입니다. 식사량을 조절하기 어렵다면 직접 진료를 받아보시는 것을 권해드립니다.
"""


def valid_html() -> str:
    rows = "".join(f"<tr><td>{row}</td></tr>" for row in PROOF["fixedRows"])
    return f'''<article data-goldhand-type="정보전달형">
    <blockquote data-reference-role="reader-question">첫 번째 질문?</blockquote>
    <blockquote data-reference-role="reader-question">두 번째 질문?</blockquote>
    <table data-native-table-purpose="credential"><tr><th>{PROOF["headerText"]}</th></tr>{rows}</table>
    <p data-reference-role="solution-preview">3분만 읽으면 무엇부터 확인할지 알 수 있습니다.</p>
    <h2 data-reference-role="section-heading">1. 첫 번째 답</h2><p>첫 번째 설명입니다.</p>
    <h2 data-reference-role="section-heading">2. 두 번째 답</h2><p>두 번째 설명입니다.</p>
    <section data-reference-role="closing-summary"><p>살을 뺀 뒤 다시 찌는 이유를 이해하는 데 오늘 글이 조금이나마 도움이 되었기를 바랍니다. 긴 글 읽어주셔서 진심으로 감사드립니다.</p></section>
    <section data-reference-role="cta"><p>다만 이 글은 요요가 생기는 이유를 이해하기 위한 일반적인 설명입니다. 식사량을 조절하기 어렵다면 직접 진료를 받아보시는 것을 권해드립니다.</p></section>
    </article>'''


class InformationArticleStructureTests(unittest.TestCase):
    def test_plain_single_structure_passes(self) -> None:
        result = VALIDATOR.validate_plain(valid_plain(), TITLE, CONTRACT, PROOF)
        self.assertEqual(result["status"], "pass", result["issues"])

    def test_value_proof_after_solution_fails(self) -> None:
        source = valid_plain()
        proof = proof_block()
        source = source.replace(proof + "\n\n3분만", "3분만")
        source = source.replace("알 수 있습니다.\n\n1.", f"알 수 있습니다.\n\n{proof}\n\n1.")
        result = VALIDATOR.validate_plain(source, TITLE, CONTRACT, PROOF)
        codes = {issue["code"] for issue in result["issues"]}
        self.assertIn("value-proof-before-solution-preview", codes)

    def test_title_answer_count_must_equal_headings(self) -> None:
        source = valid_plain().replace("2. 다이어트할 때 지킨 생활을 한꺼번에 놓지 마세요", "3. 다이어트할 때 지킨 생활을 한꺼번에 놓지 마세요")
        result = VALIDATOR.validate_plain(source, TITLE, CONTRACT, PROOF)
        codes = {issue["code"] for issue in result["issues"]}
        self.assertIn("numbered-answer-mismatch", codes)

    def test_positive_n_and_more_than_three_questions_are_supported(self) -> None:
        title = "요요를 막으려면 바꿔야 할 습관 4가지"
        source = valid_plain().replace(TITLE, title, 1)
        source = source.replace(
            "> 다이어트가 끝난 뒤에는 어떻게 먹어야 요요가 덜 올까요?",
            "> 다이어트가 끝난 뒤에는 어떻게 먹어야 요요가 덜 올까요?\n"
            "> 운동을 쉬면 바로 다시 찌는 걸까요?\n"
            "> 주말에 생활이 달라져도 괜찮을까요?",
        )
        source = source.replace(
            "살을 뺀 뒤 다시 찌는 이유를 이해하는 데 오늘 글이 조금이나마 도움이 되었기를 바랍니다. 긴 글 읽어주셔서 진심으로 감사드립니다.",
            "3. 운동을 갑자기 끊지 마세요\n\n바쁜 날에도 할 수 있는 만큼 이어갑니다.\n\n"
            "4. 주말이라고 생활 시간을 모두 바꾸지 마세요\n\n평일과 너무 다르게 지내지 않습니다.\n\n"
            "살을 뺀 뒤 다시 찌는 이유를 이해하는 데 오늘 글이 조금이나마 도움이 되었기를 바랍니다. 긴 글 읽어주셔서 진심으로 감사드립니다.",
        )
        result = VALIDATOR.validate_plain(source, title, CONTRACT, PROOF)
        self.assertEqual(result["status"], "pass", result["issues"])
        self.assertEqual(result["metrics"]["readerQuestionCount"], 4)
        self.assertEqual(result["metrics"]["numberedHeadingNumbers"], [1, 2, 3, 4])

    def test_extra_section_is_rejected(self) -> None:
        source = valid_plain().replace("\n살을 뺀 뒤 다시 찌는 이유", "\nFAQ\n\n질문과 답변입니다.\n\n살을 뺀 뒤 다시 찌는 이유")
        result = VALIDATOR.validate_plain(source, TITLE, CONTRACT, PROOF)
        codes = {issue["code"] for issue in result["issues"]}
        self.assertIn("forbidden-extra-section", codes)

    def test_extra_preview_paragraph_and_unnumbered_heading_are_rejected(self) -> None:
        extra_preview = valid_plain().replace(
            "3분만 읽어보셔도 왜 다시 찌는지, 무엇부터 바꿔야 하는지 알 수 있습니다.",
            "3분만 읽어보셔도 왜 다시 찌는지 알 수 있습니다.\n\n그 전에 한 가지만 더 말씀드리겠습니다.",
        )
        result = VALIDATOR.validate_plain(extra_preview, TITLE, CONTRACT, PROOF)
        self.assertIn("solution-preview-paragraph-count", {item["code"] for item in result["issues"]})

        extra_heading = valid_plain().replace(
            "먹는 양을 너무 줄였다면 천천히 늘려야 합니다.",
            "먹는 양을 너무 줄였다면 천천히 늘려야 합니다.\n\n추가로 확인할 점\n\n야식 시간도 함께 봅니다.",
        )
        result = VALIDATOR.validate_plain(extra_heading, TITLE, CONTRACT, PROOF)
        self.assertIn("unnumbered-main-heading", {item["code"] for item in result["issues"]})

        punctuated_heading = valid_plain().replace(
            "먹는 양을 너무 줄였다면 천천히 늘려야 합니다.",
            "먹는 양을 너무 줄였다면 천천히 늘려야 합니다.\n\n보너스 관리법입니다.\n\n야식 시간도 함께 봅니다.",
        )
        result = VALIDATOR.validate_plain(punctuated_heading, TITLE, CONTRACT, PROOF)
        self.assertIn("unnumbered-main-heading", {item["code"] for item in result["issues"]})

    def test_second_closing_flow_passes_with_title_matched_count(self) -> None:
        source = valid_plain().replace(
            "살을 뺀 뒤 다시 찌는 이유를 이해하는 데 오늘 글이 조금이나마 도움이 되었기를 바랍니다. 긴 글 읽어주셔서 진심으로 감사드립니다.\n\n"
            "다만 이 글은 요요가 생기는 이유를 이해하기 위한 일반적인 설명입니다. 식사량을 조절하기 어렵다면 직접 진료를 받아보시는 것을 권해드립니다.",
            "오늘 살펴본 두 가지 이유만 기억해 두셔도, 다이어트가 끝난 뒤 무엇부터 바꿔야 할지 이해하기 쉬워집니다.\n\n"
            "식사량을 조절하기 어렵다면 직접 진료를 받아보시는 것을 권합니다. 오늘 글도 끝까지 함께해 주셔서 고맙습니다.",
        )
        result = VALIDATOR.validate_plain(source, TITLE, CONTRACT, PROOF)
        self.assertEqual(result["status"], "pass", result["issues"])
        self.assertEqual(
            result["metrics"]["closingFlow"],
            "n-points-benefit-then-next-step-then-thanks",
        )

    def test_old_generic_closing_is_rejected(self) -> None:
        source = valid_plain().replace(
            "살을 뺀 뒤 다시 찌는 이유를 이해하는 데 오늘 글이 조금이나마 도움이 되었기를 바랍니다. 긴 글 읽어주셔서 진심으로 감사드립니다.\n\n"
            "다만 이 글은 요요가 생기는 이유를 이해하기 위한 일반적인 설명입니다. 식사량을 조절하기 어렵다면 직접 진료를 받아보시는 것을 권해드립니다.",
            "먹는 양과 생활 습관을 오래 지킬 수 있게 조절하는 것이 중요합니다.\n\n"
            "혼자 조절하기 어렵다면 직접 진료를 받아보실 수 있습니다.",
        )
        result = VALIDATOR.validate_plain(source, TITLE, CONTRACT, PROOF)
        codes = {item["code"] for item in result["issues"]}
        self.assertIn("closing-flow-unrecognized", codes)
        self.assertIn("closing-gratitude-count", codes)

    def test_second_closing_flow_must_use_title_count(self) -> None:
        source = valid_plain().replace(
            "살을 뺀 뒤 다시 찌는 이유를 이해하는 데 오늘 글이 조금이나마 도움이 되었기를 바랍니다. 긴 글 읽어주셔서 진심으로 감사드립니다.\n\n"
            "다만 이 글은 요요가 생기는 이유를 이해하기 위한 일반적인 설명입니다. 식사량을 조절하기 어렵다면 직접 진료를 받아보시는 것을 권해드립니다.",
            "오늘 살펴본 세 가지 이유만 기억해 두셔도, 다이어트가 끝난 뒤 무엇부터 바꿔야 할지 이해하기 쉬워집니다.\n\n"
            "식사량을 조절하기 어렵다면 직접 진료를 받아보시는 것을 권합니다. 오늘 글도 끝까지 함께해 주셔서 고맙습니다.",
        )
        result = VALIDATOR.validate_plain(source, TITLE, CONTRACT, PROOF)
        self.assertIn(
            "closing-title-count-mismatch",
            {item["code"] for item in result["issues"]},
        )

    def test_closing_thanks_must_appear_once(self) -> None:
        source = valid_plain().replace(
            "권해드립니다.",
            "권해드립니다. 오늘 글도 끝까지 읽어주셔서 고맙습니다.",
        )
        result = VALIDATOR.validate_plain(source, TITLE, CONTRACT, PROOF)
        self.assertIn(
            "closing-gratitude-count",
            {item["code"] for item in result["issues"]},
        )

    def test_gratitude_wording_is_not_a_literal_contract(self) -> None:
        closing = CONTRACT["closing"]
        self.assertNotIn("gratitudeWording", closing["helpfulThenThanksThenDirectEvaluation"])
        self.assertNotIn("gratitudeWording", closing["nPointsBenefitThenNextStepThenThanks"])
        self.assertTrue(closing["gratitudeWordingIsNonBindingExample"])
        self.assertTrue(closing["exactGratitudeReuseAcrossManuscriptsForbidden"])

    def test_branded_or_sales_closing_is_rejected(self) -> None:
        branded = valid_plain().replace(
            "직접 진료를 받아보시는 것을 권해드립니다.",
            "금손한의원에서 진료를 받아보세요.",
        )
        result = VALIDATOR.validate_plain(branded, TITLE, CONTRACT, PROOF)
        self.assertIn("branded-closing-cta", {item["code"] for item in result["issues"]})

        sales = valid_plain().replace(
            "직접 진료를 받아보시는 것을 권해드립니다.",
            "직접 진료를 받아보시려면 예약 문의를 남겨주세요.",
        )
        result = VALIDATOR.validate_plain(sales, TITLE, CONTRACT, PROOF)
        self.assertIn("sales-closing-cta", {item["code"] for item in result["issues"]})

    def test_html_cta_must_be_final(self) -> None:
        article = valid_html().replace(
            "</article>",
            '<p>CTA 뒤의 불필요한 글</p><img src="data:,">\n</article>',
        )
        result = VALIDATOR.validate_html(article, TITLE, CONTRACT, PROOF)
        codes = {issue["code"] for issue in result["issues"]}
        self.assertIn("content-after-cta", codes)

    def test_html_images_are_allowed_only_inside_numbered_answers(self) -> None:
        inside = valid_html().replace(
            '<p>첫 번째 설명입니다.</p>',
            '<p>첫 번째 설명입니다.</p><figure><img src="data:,inside"></figure>',
        )
        result = VALIDATOR.validate_html(inside, TITLE, CONTRACT, PROOF)
        self.assertNotIn("image-outside-numbered-answer", {item["code"] for item in result["issues"]})

        in_summary = valid_html().replace(
            '<section data-reference-role="closing-summary"><p>',
            '<section data-reference-role="closing-summary"><img src="data:,summary"><p>',
        )
        result = VALIDATOR.validate_html(in_summary, TITLE, CONTRACT, PROOF)
        self.assertIn("image-outside-numbered-answer", {item["code"] for item in result["issues"]})

    def test_html_rejects_content_before_questions_and_extra_heading(self) -> None:
        article = valid_html().replace(
            '<blockquote data-reference-role="reader-question">',
            '<img src="data:,special"><blockquote data-reference-role="reader-question">',
            1,
        )
        result = VALIDATOR.validate_html(article, TITLE, CONTRACT, PROOF)
        self.assertIn("unexpected-block-before-numbered-answers", {item["code"] for item in result["issues"]})

        article = valid_html().replace(
            '<p>첫 번째 설명입니다.</p>',
            '<p>첫 번째 설명입니다.</p><h3>추가 소제목</h3><p>추가 설명입니다.</p>',
        )
        result = VALIDATOR.validate_html(article, TITLE, CONTRACT, PROOF)
        self.assertIn("unnumbered-main-heading", {item["code"] for item in result["issues"]})

    def test_html_rejects_roleless_structural_containers_inside_answer(self) -> None:
        for tag in ("section", "aside"):
            with self.subTest(tag=tag):
                article = valid_html().replace(
                    '<p>첫 번째 설명입니다.</p>',
                    f'<p>첫 번째 설명입니다.</p><{tag}><p>별도 FAQ 문답입니다.</p></{tag}>',
                )
                result = VALIDATOR.validate_html(article, TITLE, CONTRACT, PROOF)
                self.assertIn(
                    "extra-structural-container",
                    {item["code"] for item in result["issues"]},
                )


if __name__ == "__main__":
    unittest.main()
