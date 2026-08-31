from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location("priority_test_" + name, SKILL / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INTERVIEW = load("topic_priority_interview")
ALIGN = load("validate_title_alignment")
TOPIC = "다이어트"
TITLE = "다이어트, 제가 중요하게 생각하는 2가지"
RECEIPT = {"topic": TOPIC, "title": TITLE, "userResponse": "1. 식사 기록\n2. 운동 계획",
           "priorities": ["식사 기록", "운동 계획"]}
PLAIN = TITLE + "\n1. 식사 기록\n먹은 음식을 기록하며 식사 습관을 돌아봅니다.\n2. 운동 계획\n일정에 맞는 운동 계획을 세우는 과정을 설명합니다."


def fixture():
    # Synthetic integrity evidence, not a real independent editorial review.
    report = {**copy.deepcopy(RECEIPT), "bodySha256": ALIGN.body_digest(PLAIN, TITLE),
              "draftAuthor": "test-writer", "reviewer": "test-editor", "verdict": "pass",
              "unresolvedPriorities": [], "answers": []}
    for p, section in zip(RECEIPT["priorities"], ALIGN.sections(PLAIN, TITLE)):
        report["answers"].append({"priority": p, "number": section["number"],
                                  "bodyExcerpt": section["body"],
                                  "whyCentral": "단위 테스트의 기록이며 실제 사용자 원고의 중심 내용 검수를 대신하지 않습니다."})
    return {"userPriorityReview": report}


class PriorityInterviewTests(unittest.TestCase):
    def test_selected_topic_is_preserved_instead_of_narrowing_to_title(self):
        result = INTERVIEW.prepare(TOPIC, "다이어트 후 요요가 왔다면 돌아볼 2가지")
        self.assertEqual(result["question"], "'다이어트'에 대해 중요하게 생각하는 2가지가 무엇인가요?")
        self.assertFalse(result["draftingAllowed"])

    def test_direct_custom_topic_and_title_remain_exact(self):
        title = "11년차가 3분 안에 설명하는 습관2가지"
        topic = "출산 후 체중 관리"
        result = INTERVIEW.prepare(topic, title)
        self.assertEqual(result["topic"], topic)
        self.assertEqual(result["title"], title)
        self.assertEqual(result["answerCount"], 2)

    def test_non_answer_numbers_do_not_create_a_count(self):
        result = INTERVIEW.prepare(TOPIC, "40대 다이어트, 3분만 읽어 보세요")
        self.assertIsNone(result["answerCount"])
        self.assertEqual(result["question"], "'다이어트'에 대해 중요하게 생각하는 내용은 무엇인가요?")

    def test_korean_and_fullwidth_counts_do_not_rewrite_title(self):
        for title, count in [("중요한 두 가지", 2), ("습관 ３가지", 3)]:
            with self.subTest(title=title):
                result = INTERVIEW.prepare(TOPIC, title)
                self.assertEqual(result["answerCount"], count)
                self.assertEqual(result["title"], title)

    def test_conflicting_counts_and_missing_topic_are_not_inferred(self):
        for topic, title in [(TOPIC, "이유 2가지와 방법 3가지"), (TOPIC, "이유 0가지"), ("", TITLE)]:
            with self.subTest(topic=topic, title=title), self.assertRaises(ValueError):
                INTERVIEW.prepare(topic, title)

    def test_actual_user_response_unlocks_drafting(self):
        result = INTERVIEW.check_response(TOPIC, TITLE, RECEIPT)
        self.assertEqual(result["status"], "ready-for-user-centered-draft")
        self.assertTrue(result["draftingAllowed"])
        self.assertEqual(RECEIPT["priorities"], ["식사 기록", "운동 계획"])

    def test_missing_or_wrong_count_does_not_get_filled_from_sources(self):
        for priorities in [[], ["식사 기록"], ["식사 기록", "운동 계획", "식사"]]:
            with self.subTest(priorities=priorities):
                result = INTERVIEW.check_response(TOPIC, TITLE, {**RECEIPT, "priorities": priorities})
                self.assertFalse(result["draftingAllowed"])
                self.assertIn("priority-count-mismatch", result["issues"])

    def test_fabricated_reordered_and_duplicate_priorities_are_rejected(self):
        cases = [(["식사 기록", "수면 습관"], "priority-not-in-user-response"),
                 (["운동 계획", "식사 기록"], "priority-order-changed"),
                 (["식사 기록", "식사 기록"], "duplicate-user-priority")]
        for priorities, issue in cases:
            with self.subTest(issue=issue):
                result = INTERVIEW.check_response(TOPIC, TITLE, {**RECEIPT, "priorities": priorities})
                self.assertIn(issue, result["issues"])

    def test_old_interview_cannot_be_reused_for_another_title(self):
        result = INTERVIEW.check_response(TOPIC, "체중 관리에서 확인할 2가지", RECEIPT)
        self.assertFalse(result["draftingAllowed"])
        self.assertIn("interview-topic-or-title-changed", result["issues"])

    def test_numberless_title_uses_actual_user_priorities(self):
        title = "다이어트에서 제가 중요하게 생각하는 것"
        result = INTERVIEW.check_response(TOPIC, title, {**RECEIPT, "title": title})
        self.assertTrue(result["draftingAllowed"])
        self.assertEqual(result["answerCount"], 2)

    def test_missing_response_blocks_even_if_priorities_exist(self):
        result = INTERVIEW.check_response(TOPIC, TITLE, {**RECEIPT, "userResponse": ""})
        self.assertFalse(result["draftingAllowed"])

    def test_review_binds_each_priority_to_its_actual_section(self):
        result = INTERVIEW.check_coverage(TOPIC, TITLE, RECEIPT, PLAIN, fixture())
        self.assertEqual(result["status"], "pass", result)
        self.assertTrue(result["mechanicalPassDoesNotProveCentrality"])
        html = "<article>" + "".join("<p>" + line + "</p>" for line in PLAIN.splitlines()[1:]) + "</article>"
        self.assertEqual(INTERVIEW.check_coverage(TOPIC, TITLE, RECEIPT, html, fixture(), is_html=True)["status"], "pass")

    def test_missing_rejected_changed_or_incomplete_review_blocks_production(self):
        cases = [{}, fixture(), fixture(), fixture(), fixture()]
        cases[1]["userPriorityReview"]["verdict"] = "fail"
        cases[2]["userPriorityReview"]["priorities"] = ["수면", "식사"]
        cases[3]["userPriorityReview"]["answers"].pop()
        cases[4]["userPriorityReview"]["unresolvedPriorities"] = ["운동 계획이 본문 중심에서 빠짐"]
        for review in cases:
            with self.subTest(review=review):
                self.assertFalse(INTERVIEW.check_coverage(TOPIC, TITLE, RECEIPT, PLAIN, review)["productionAllowed"])

    def test_changed_prose_or_excerpt_from_another_section_is_rejected(self):
        result = INTERVIEW.check_coverage(TOPIC, TITLE, RECEIPT, PLAIN.replace("먹은 음식", "수면 시간"), fixture())
        self.assertIn("user-priority-review-stale-prose", result["issues"])
        review = fixture()
        review["userPriorityReview"]["answers"][0]["bodyExcerpt"] = "일정에 맞는 운동 계획을 세우는 과정을 설명합니다."
        result = INTERVIEW.check_coverage(TOPIC, TITLE, RECEIPT, PLAIN, review)
        self.assertIn("user-priority-body-excerpt", result["issues"])


if __name__ == "__main__":
    unittest.main()
