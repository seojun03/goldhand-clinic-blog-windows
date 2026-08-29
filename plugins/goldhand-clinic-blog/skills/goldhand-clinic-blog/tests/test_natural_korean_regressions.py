from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "validate_natural_korean.py"
CONTRACT = json.loads(
    (SKILL_DIR / "assets" / "natural-korean-regression-contract.json").read_text(encoding="utf-8")
)


def load_validator():
    spec = importlib.util.spec_from_file_location("goldhand_natural_korean_regressions", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"생활어 회귀검사기를 불러올 수 없습니다: {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = load_validator()


class NaturalKoreanRegressionTests(unittest.TestCase):
    def assert_fails(self, sentence: str, code: str) -> None:
        result = VALIDATOR.validate_text("", sentence, CONTRACT)
        self.assertEqual(result["status"], "fail", result)
        self.assertIn(code, {item["code"] for item in result["issues"]}, result)

    def test_user_corrected_late_night_sentence_is_a_permanent_regression(self) -> None:
        self.assert_fails(
            "다시 밤늦게 먹고 늦잠을 자나요?",
            "late-night-eating-late-sleep-ai-collocation",
        )
        approved = VALIDATOR.validate_text("", "다시 야식 먹고 늦게 주무시나요?", CONTRACT)
        self.assertEqual(approved["status"], "pass", approved)

    def test_user_corrected_meal_sentence_is_a_permanent_regression(self) -> None:
        self.assert_fails(
            "거의 먹지 않았다면 원래 식사로 갑자기 돌아가지 마세요.",
            "return-to-original-meal-ai-collocation",
        )
        approved = VALIDATOR.validate_text(
            "",
            "굶다시피 살을 뺐다면, 다이어트가 끝났다고 갑자기 예전만큼 드시면 안 됩니다.",
            CONTRACT,
        )
        self.assertEqual(approved["status"], "pass", approved)

    def test_uncommon_collocation_family_is_blocked(self) -> None:
        examples = {
            "잠과 운동 시간을 만들었습니다.": "make-sleep-exercise-time-ai-collocation",
            "잠드는 시각을 크게 벌리지 마세요.": "widen-bedtime-ai-collocation",
            "굶었던 식사를 한꺼번에 되돌리지 마세요.": "restore-starved-meal-ai-collocation",
        }
        for sentence, code in examples.items():
            with self.subTest(sentence=sentence):
                self.assert_fails(sentence, code)

    def test_stacked_regional_keyword_and_clinic_name_is_blocked(self) -> None:
        self.assert_fails(
            "저희 동천동 한의원 금손한의원에서는 식사량을 묻습니다.",
            "stacked-keyword-clinic-name-ai-frame",
        )
        approved = VALIDATOR.validate_text(
            "",
            "저는 진료할 때 하루에 몇 끼를 드시는지부터 묻습니다.",
            CONTRACT,
        )
        self.assertEqual(approved["status"], "pass", approved)

    def test_mechanical_pass_is_explicitly_not_a_naturalness_certificate(self) -> None:
        result = VALIDATOR.validate_text("", "사실 야식은 줄이는 게 좋죠.", CONTRACT)
        self.assertEqual(result["status"], "pass", result)
        self.assertEqual(
            result["scope"],
            "user-corrections-generation-principles-and-known-regression-guard",
        )
        self.assertIs(result["mechanicalPassDoesNotProveNaturalness"], True)
        self.assertIs(result["userApprovalRequiredToCallUpdateSuccessful"], True)
        self.assertGreaterEqual(result["metrics"]["minimumForwardTestManuscripts"], 3)
        self.assertGreaterEqual(result["metrics"]["observedForwardTestManuscripts"], 3)

    def test_contract_keeps_generation_causes_and_forward_test_gate(self) -> None:
        self.assertEqual(VALIDATOR.contract_errors(CONTRACT), [])
        corrections = [item for item in CONTRACT["failurePatterns"] if item["userCorrected"]]
        self.assertEqual(
            {item["failedExample"] for item in corrections},
            {
                "다시 밤늦게 먹고 늦잠을 자나요?",
                "거의 먹지 않았다면 원래 식사로 갑자기 돌아가지 마세요.",
            },
        )
        for item in corrections:
            self.assertTrue(item["failureMechanism"])
            self.assertTrue(item["generationPrincipleIds"])
        gate = CONTRACT["forwardTestGate"]
        self.assertEqual(gate["statusBeforeUserApproval"], "pending-user-reading")
        self.assertIn("true", gate["rejectedReviewEvidence"])
        findings = CONTRACT["forwardTestFindings"]
        self.assertEqual(findings["status"], "pending-user-reading")
        self.assertGreaterEqual(len(findings["manuscripts"]), 3)
        self.assertTrue(
            all(item["concreteFindingCount"] > 0 for item in findings["manuscripts"])
        )
        self.assertTrue(
            all(item["flowCheckCount"] >= 2 for item in findings["manuscripts"])
        )
        self.assertTrue(
            all(item["reviewReceipt"].endswith("independent-review.json") for item in findings["manuscripts"])
        )
        self.assertEqual(
            {item["title"] for item in findings["manuscripts"]},
            {
                "동천동 한의원 반드시 바꿔야 할 요요 습관 2가지",
                "계단을 내려갈 때 무릎이 아픈 이유 2가지",
                "자다가 자주 깨는 밤에 확인할 것 3가지",
            },
        )
        principle_ids = {item["id"] for item in CONTRACT["generationPrinciples"]}
        self.assertIn("keep-one-structure-vary-numbered-answer-language", principle_ids)
        self.assertIn("close-with-topic-recall-benefit-and-next-step", principle_ids)
        self.assertIn("vary-gratitude-by-rhetorical-job", principle_ids)
        self.assertIn("keep-closing-next-step-clinic-neutral", principle_ids)
        contextual = {
            item["id"]: item for item in CONTRACT["contextualUserCorrections"]
        }
        self.assertEqual(
            set(contextual),
            {
                "gratitude-example-is-not-a-fixed-line",
                "clinic-name-makes-the-close-feel-like-an-ad",
            },
        )
        self.assertTrue(all(item["userCorrected"] for item in contextual.values()))
        self.assertIn(
            "keep-one-structure-vary-numbered-answer-language",
            {
                item["generationPrincipleId"]
                for item in findings["observedFailureFamilies"]
            },
        )
        self.assertIn(
            "close-with-topic-recall-benefit-and-next-step",
            {
                item["generationPrincipleId"]
                for item in findings["observedFailureFamilies"]
            },
        )
        observed_principles = {
            item["generationPrincipleId"]
            for item in findings["observedFailureFamilies"]
        }
        self.assertIn("vary-gratitude-by-rhetorical-job", observed_principles)
        self.assertIn("keep-closing-next-step-clinic-neutral", observed_principles)


if __name__ == "__main__":
    unittest.main()
