from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = SKILL_DIR.parents[1]
CONTRACT_PATH = SKILL_DIR / "assets" / "title-confirmed-execution-contract.json"
TITLE_VALIDATOR_PATH = SKILL_DIR / "scripts" / "validate_title.py"


def load_title_validator():
    spec = importlib.util.spec_from_file_location(
        "goldhand_title_confirmed_autorun", TITLE_VALIDATOR_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(TITLE_VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TITLE_VALIDATOR = load_title_validator()


class TitleConfirmedAutorunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_title_confirmation_is_the_last_user_gate(self) -> None:
        self.assertEqual(self.contract["lastUserInputGate"], "title-confirmation")
        after = self.contract["afterTitleConfirmation"]
        self.assertFalse(after["additionalUserQuestionsAllowed"])
        self.assertFalse(after["plainTextApprovalRequired"])
        self.assertFalse(after["visibleApprovalStatusAllowed"])
        self.assertTrue(after["internalPlainTextReviewRequired"])
        self.assertTrue(after["automaticProductionRequired"])
        self.assertEqual(after["imageFailureFallback"], "finish-without-images")

    def test_three_title_entry_flows_continue_without_another_question(self) -> None:
        scenarios = self.contract["scenarioTests"]
        self.assertEqual(
            {item["id"] for item in scenarios},
            {
                "recommended-numbered-title-selected",
                "direct-numbered-title",
                "direct-title-without-number",
            },
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario["id"]):
                self.assertFalse(scenario["mustAskUserAgain"])
                self.assertEqual(scenario["expectedNext"], "automatic-full-production")

    def test_numberless_confirmed_title_is_valid_without_a_followup(self) -> None:
        result = TITLE_VALIDATOR.validate_title(
            "요요를 막으려면 생활 습관부터 바꿔야 합니다",
            answer_count=2,
        )
        self.assertEqual(result["status"], "pass", result["issues"])
        self.assertEqual(result["metrics"]["answerPromises"], [])
        self.assertEqual(result["metrics"]["answerCount"], 2)

    def test_runtime_instructions_and_manifest_require_automatic_completion(self) -> None:
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        agent = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
        workflow = (SKILL_DIR / "references" / "workflow-and-output.md").read_text(
            encoding="utf-8"
        )
        manifest = json.loads(
            (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertIn("제목 확정이 마지막 사용자 확인 단계", skill)
        self.assertIn("automatically continue", agent)
        self.assertIn("최종 제작까지 이어간다", workflow)
        self.assertTrue(
            any(
                "추가 질문" in prompt and "자동으로 완료" in prompt
                for prompt in manifest["interface"]["defaultPrompt"]
            )
        )


if __name__ == "__main__":
    unittest.main()
