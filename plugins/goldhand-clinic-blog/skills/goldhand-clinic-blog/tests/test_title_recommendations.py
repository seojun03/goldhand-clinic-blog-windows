from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_DIR / "scripts" / "validate_title_recommendations.py"


def load_validator():
    spec = importlib.util.spec_from_file_location(
        "goldhand_title_recommendation_tests",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = load_validator()


class TitleRecommendationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(
            (SKILL_DIR / "assets" / "title-recommendation-contract.json").read_text(
                encoding="utf-8"
            )
        )
        cls.evidence = (SKILL_DIR / "references" / "clinic-facts.md").read_text(
            encoding="utf-8"
        )

    def valid_payload(self) -> dict[str, object]:
        return {
            "topic": "다이어트 뒤 요요",
            "informationDoctor": {
                "queried": True,
                "stage": "title",
                "status": "stored-match",
                "sourceProseLoaded": False,
                "structureLoadedFromSources": False,
                "singleStructureAuthority": "references/information-delivery-structure.md",
                "matchedSourceIds": ["WIP-223606765259"],
            },
            "candidates": [
                {"title": "야식 뒤 다시 찌는 이유 2가지", "answerCount": 2},
                {"title": "요요를 막으려면 먼저 바꿔야 할 습관 3가지", "answerCount": 3},
                {"title": "다이어트가 끝난 뒤 식사량을 늘리는 방법 2가지", "answerCount": 2},
                {"title": "살을 뺀 뒤 체중이 다시 오를 때 확인할 것 3가지", "answerCount": 3},
                {"title": "굶어서 뺀 살이 다시 찌지 않게 지킬 습관 2가지", "answerCount": 2},
            ],
        }

    def validate(self, payload: dict[str, object]) -> dict[str, object]:
        return VALIDATOR.validate_recommendations(
            payload,
            contract=self.contract,
            evidence=self.evidence,
        )

    def test_five_numbered_titles_pass(self) -> None:
        result = self.validate(self.valid_payload())
        self.assertEqual(result["status"], "pass", result)
        self.assertEqual(result["metrics"]["candidateCount"], 5)
        self.assertEqual(result["metrics"]["numberedCandidateCount"], 5)
        self.assertEqual(
            result["metrics"]["singleStructureContractId"],
            "goldhand-single-information-delivery-structure-v1",
        )

    def test_information_doctor_must_not_load_source_prose_or_structure(self) -> None:
        payload = self.valid_payload()
        payload["informationDoctor"]["sourceProseLoaded"] = True
        payload["informationDoctor"]["structureLoadedFromSources"] = True
        result = self.validate(payload)
        codes = {item["code"] for item in result["issues"]}
        self.assertIn("source-prose-loaded", codes)
        self.assertIn("source-structure-loaded", codes)

    def test_title_number_must_match_answer_count(self) -> None:
        payload = self.valid_payload()
        payload["candidates"][0]["answerCount"] = 3
        result = self.validate(payload)
        nested = {
            item["code"]
            for item in result["candidateResults"][0]["validation"]["issues"]
        }
        self.assertIn("answer-count-mismatch", nested)

    def test_positive_n_is_allowed_and_zero_is_rejected(self) -> None:
        payload = self.valid_payload()
        payload["candidates"][0] = {
            "title": "야식 뒤 다시 찌는 이유 1가지",
            "answerCount": 1,
        }
        result = self.validate(payload)
        self.assertEqual(result["status"], "pass", result)

        payload = self.valid_payload()
        payload["candidates"][0] = {
            "title": "야식 뒤 다시 찌는 이유 0가지",
            "answerCount": 0,
        }
        result = self.validate(payload)
        nested = {
            item["code"]
            for item in result["candidateResults"][0]["validation"]["issues"]
        }
        self.assertIn("numbered-promise-unsupported", nested)
        self.assertIn("answer-count-unsupported", nested)

    def test_candidate_count_and_duplicate_titles_fail(self) -> None:
        payload = self.valid_payload()
        payload["candidates"][-1] = dict(payload["candidates"][0])
        result = self.validate(payload)
        self.assertIn("duplicate-title", {item["code"] for item in result["issues"]})

        payload = self.valid_payload()
        payload["candidates"] = payload["candidates"][:4]
        result = self.validate(payload)
        self.assertIn("candidate-count", {item["code"] for item in result["issues"]})


if __name__ == "__main__":
    unittest.main()
