from __future__ import annotations

import copy
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location("test_integrity_" + name, SKILL / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ALIGN = load("validate_title_alignment")
UNIQUE = load("validate_unique_images")
SELECT = load("recommend_media")
BUILD = load("build_naver_copy_page")
ARTICLE = load("validate_article")
PAGE = load("validate_html")
TITLE = "교통사고 검사에서 이상이 없다는데도 아픈이유 2가지"
PLAIN = f"""{TITLE}
> 검사에서 이상이 없다는데 왜 목은 계속 아플까요?
> 사고 뒤 시간이 지나 아파질 수도 있나요?
3분만 읽으면 영상 검사와 통증이 다를 수 있는 이유를 알 수 있습니다.
1. 영상에 드러나지 않는 연부조직 손상이 있을 수 있습니다
교통사고 때 목의 근육과 인대가 손상되어도 엑스레이에는 뚜렷하게 보이지 않을 수 있습니다.
2. 손상 뒤 통증이 뒤늦게 나타날 수 있습니다
사고 직후보다 시간이 지난 뒤 조직의 반응으로 통증을 느끼기도 합니다.
검사 결과만으로 통증을 판단하기 어려운 이유를 이해하는 데 도움이 되었기를 바랍니다. 읽어 주셔서 감사합니다.
일반적인 설명이며 증상이 계속되면 직접 진료를 받아보시길 권합니다.
"""


def reviewed_fixture(raw, title, is_html=False):
    """Synthetic evidence for integrity unit tests, never a clinical review."""
    report = ALIGN.describe(raw, title, is_html)
    report.update(draftAuthor="unit-test-writer", reviewer="unit-test-editor",
                  titleSubject=title, titleQuestion="이 제목에서 독자가 묻는 질문에 각각의 번호 답이 대응하는가?",
                  premiseCheck="단위 테스트용 기록이다. 실제 임상 원고의 독립 의미 검수가 아니며 제목과 본문 연결의 무결성만 검증한다.",
                  wholeBodyCheck="단위 테스트용 기록으로, 본문이 바뀌면 이 기록이 무효가 되는지 검사한다. 이 설명을 실제 원고의 의미 검수 증거로 사용해서는 안 된다.",
                  distinctionCheck="테스트에 사용하는 두 번호의 실제 문장은 서로 다르며 한 문장만 다른 번호에 재사용하는 경우를 별도로 검사한다.",
                  verdict="pass")
    for answer, section in zip(report["answers"], ALIGN.sections(raw, title, is_html)):
        answer.update(directAnswerExcerpt=section["body"].splitlines()[0],
                      whyThisAnswersTitle="테스트 픽스처의 해당 번호에서 실제 문장을 인용했는지와 제목 또는 본문 변경을 거부하는지 확인한다.")
    return report


def html_from_plain(raw=PLAIN, title=TITLE):
    import html
    blocks = []
    for line in raw.splitlines()[1:]:
        if not line.strip():
            continue
        tag = "h2" if ALIGN.HEADING.match(line) else "blockquote" if line.startswith(">") else "p"
        blocks.append(f"<{tag}>" + html.escape(line.removeprefix("> ")) + f"</{tag}>")
    return "<article>" + "".join(blocks) + "</article>"


class TitleIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.report = reviewed_fixture(PLAIN, TITLE)
        self.raw = html_from_plain()

    def codes(self, raw, report=None, title=TITLE, is_html=False):
        return {i["code"] for i in ALIGN.validate(raw, title, report, is_html=is_html)["issues"]}

    def test_plain_html_and_linewrap_share_frozen_prose(self):
        sealed = ALIGN.attach(self.raw, TITLE, self.report)
        self.assertEqual(ALIGN.validate(sealed, TITLE, is_html=True)["status"], "pass")
        self.assertEqual(ALIGN.validate(sealed.replace("목의 근육", "목의<br>근육"), TITLE, is_html=True)["status"], "pass")

    def test_unreviewed_html_cannot_proceed(self):
        self.assertIn("title-review-missing", self.codes(self.raw, is_html=True))
        with self.assertRaises(ValueError):
            BUILD.validate_production_integrity(self.raw, TITLE)

    def test_title_swap_rejected_even_with_same_answer_count(self):
        sealed = ALIGN.attach(self.raw, TITLE, self.report)
        self.assertIn("title-review-title-changed", self.codes(sealed, title="계단에서 무릎이 아픈 이유 2가지", is_html=True))

    def test_knee_body_swap_with_cosmetic_accident_word_is_stale(self):
        sealed = ALIGN.attach(self.raw, TITLE, self.report)
        changed = sealed.replace("교통사고 때 목의 근육과 인대가 손상되어도 엑스레이에는 뚜렷하게 보이지 않을 수 있습니다.",
                                 "교통사고와 별개로 계단을 내려갈 때는 무릎에 체중이 실립니다.")
        self.assertIn("title-review-stale-prose", self.codes(changed, is_html=True))

    def test_reviewer_rejection_blocks_even_current_hash(self):
        self.report["verdict"] = "fail"
        self.report["offTopicPassages"] = ["둘째 답이 검사 정상과 통증의 관계를 설명하지 못함"]
        self.assertIn("title-review-unresolved", self.codes(PLAIN, self.report))

    def test_new_body_text_inside_a_table_is_not_exempt_from_review(self):
        sealed = ALIGN.attach(self.raw, TITLE, self.report)
        changed = sealed.replace('</h2>', '</h2><table><tr><td>계단에서 생기는 무릎 통증의 설명을 끼워 넣었습니다.</td></tr></table>', 1)
        self.assertIn("title-review-stale-prose", self.codes(changed, is_html=True))

    def test_action_cannot_replace_reason_review(self):
        self.report["answerType"] = "action"
        self.assertIn("title-review-answer-type", self.codes(PLAIN, self.report))

    def test_excerpt_from_other_number_does_not_count(self):
        self.report["answers"][1]["directAnswerExcerpt"] = self.report["answers"][0]["directAnswerExcerpt"]
        codes = self.codes(PLAIN, self.report)
        self.assertIn("title-review-answer-excerpt", codes)
        self.assertIn("title-review-repeated-answer", codes)

    def test_describe_is_pending_and_not_a_review(self):
        self.assertIn("title-review-unresolved", self.codes(PLAIN, ALIGN.describe(PLAIN, TITLE)))

    def test_direct_title_without_number_is_supported(self):
        title = "사고 뒤 검사 결과와 목 통증을 함께 살펴보기"
        raw = PLAIN.replace(TITLE, title, 1)
        report = reviewed_fixture(raw, title)
        self.assertEqual(ALIGN.validate(raw, title, report)["status"], "pass")

    def test_incidental_knee_in_relevant_accident_section_not_banned(self):
        raw = PLAIN.replace("사고 직후보다", "교통사고 때 부딪친 무릎도 경과를 함께 봅니다. 사고 직후보다")
        report = reviewed_fixture(raw, TITLE)
        self.assertEqual(ALIGN.validate(raw, TITLE, report)["status"], "pass")

    def test_builder_blocks_before_image_publish_or_output_write(self):
        from test_clipboard_context_regressions import valid_structure_article, TITLE as COPY_TITLE
        raw = re.sub(r'\sdata-title-alignment="[^"]*"', '', valid_structure_article(), count=1)
        BUILD.validate_information_article_structure(raw, COPY_TITLE)
        with tempfile.TemporaryDirectory() as tmp:
            source, dest = Path(tmp)/"raw.html", Path(tmp)/"out.html"
            source.write_text(raw, encoding="utf-8")
            args = type("Args", (), {"article_html": source, "title": COPY_TITLE, "output": dest, "text_only_fallback_reason": None})()
            with patch.object(BUILD, "parse_args", return_value=args), patch.object(BUILD, "publish_or_text_only_fallback") as publish:
                self.assertEqual(BUILD.main(), 1)
                publish.assert_not_called()
                self.assertFalse(dest.exists())

    def test_valid_review_cannot_bypass_structure_before_image_publish(self):
        from test_clipboard_context_regressions import valid_structure_article, TITLE as COPY_TITLE
        # The visible words and review remain unchanged, but a numbered
        # answer has lost the required production role.
        raw = valid_structure_article().replace('data-reference-role="section-heading"', 'data-reference-role="unknown-section"', 1)
        self.assertEqual(ALIGN.validate(raw, COPY_TITLE, is_html=True)["status"], "pass")
        with tempfile.TemporaryDirectory() as tmp:
            source, dest = Path(tmp)/"raw.html", Path(tmp)/"out.html"
            source.write_text(raw, encoding="utf-8")
            args = type("Args", (), {"article_html": source, "title": COPY_TITLE, "output": dest, "text_only_fallback_reason": None})()
            with patch.object(BUILD, "parse_args", return_value=args), patch.object(BUILD, "publish_or_text_only_fallback") as publish:
                self.assertEqual(BUILD.main(), 1)
                publish.assert_not_called()
                self.assertFalse(dest.exists())


class PhotoIntegrityTests(unittest.TestCase):
    def check(self, html):
        return UNIQUE.validate(html, {})

    def test_same_url_and_render_variants_rejected(self):
        raw = '<img src="https://images.test/photo.jpg?w=200&amp;type=w80"><img src="https://images.test/photo.jpg?w=800&amp;type=w1000">'
        self.assertEqual(self.check(raw)["metrics"]["duplicateCount"], 1)

    def test_identity_query_values_are_not_discarded(self):
        self.assertEqual(self.check('<img src="https://images.test/image?id=1"><img src="https://images.test/image?id=2">')["status"], "pass")

    def test_image_type_query_can_identify_different_images(self):
        self.assertEqual(self.check('<img src="https://images.test/image?type=front"><img src="https://images.test/image?type=back">')["status"], "pass")

    def test_identical_bytes_with_new_filenames_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp)/"first.png", Path(tmp)/"renamed.jpg"
            a.write_bytes(b"same original image"); b.write_bytes(a.read_bytes())
            self.assertEqual(self.check(f'<img data-local-image="{a}"><img data-local-image="{b}">')["status"], "fail")
            b.write_bytes(b"another actual image")
            self.assertEqual(self.check(f'<img data-local-image="{a}"><img data-local-image="{b}">')["status"], "pass")

    def test_different_urls_with_same_origin_or_hash_rejected(self):
        for attribute in ("data-image-origin", "data-media-sha256", "data-goldhand-media"):
            with self.subTest(attribute=attribute):
                self.assertEqual(self.check(f'<img src="https://a.test/a" {attribute}="same"><img src="https://b.test/b" {attribute}="same">')["status"], "fail")

    def test_selector_deduplicates_aliases_and_prior_section_selection(self):
        library = json.loads((SKILL / "assets/media-library.json").read_text(encoding="utf-8"))
        asset = next(a for a in library["assets"] if SELECT.is_safe_candidate(a))
        asset = copy.deepcopy(asset); asset["placementTerms"] = ["진찰사진선택"]
        alias = copy.deepcopy(asset); alias["id"] = "same-file-another-id"
        result = SELECT.recommend({"assets": [asset, alias]}, topic="진찰사진선택", count=2)
        self.assertEqual(result["selectedCount"], 1)
        self.assertEqual(result["status"], "partial")
        second = SELECT.recommend({"assets": [asset, alias]}, topic="진찰사진선택", count=1, used_media=result["selected"])
        self.assertEqual(second["selectedCount"], 0)
        self.assertEqual(second["used"], result["selected"])
        third = SELECT.recommend({"assets": [asset, alias]}, topic="진찰사진선택", count=1, used_media=second["used"])
        self.assertEqual(third["selectedCount"], 0)

    def test_both_final_validators_reject_photo_duplication(self):
        from test_clipboard_context_regressions import valid_structure_article, TITLE as COPY_TITLE
        original = valid_structure_article()
        photos = '<figure><img src="https://a.test/photo.png"></figure>' * 2
        bad = original.replace('</h2>', '</h2>' + photos, 1)
        self.assertIn("duplicate-article-image", {i["code"] for i in ARTICLE.validate_article(bad, COPY_TITLE)["issues"]})
        page = BUILD.build_page(COPY_TITLE, original)
        page = page.replace('</h2>', '</h2>' + photos, 1)
        self.assertIn("duplicate-article-image", {i["code"] for i in PAGE.validate_html(page)["issues"]})


if __name__ == "__main__":
    unittest.main()
