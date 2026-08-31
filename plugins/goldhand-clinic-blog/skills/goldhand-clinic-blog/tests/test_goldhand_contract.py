from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
ASSETS = SKILL_DIR / "assets"
REFERENCES = SKILL_DIR / "references"
SCRIPTS = SKILL_DIR / "scripts"


def load_script(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"goldhand_{name}_contract", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NATURAL = load_script("validate_natural_korean")
ARTICLE = load_script("validate_article")


class GoldhandCoreContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.structure = json.loads(
            (ASSETS / "information-delivery-structure-contract.json").read_text(
                encoding="utf-8"
            )
        )
        cls.natural = json.loads(
            (ASSETS / "natural-korean-regression-contract.json").read_text(
                encoding="utf-8"
            )
        )

    def test_only_one_information_article_order_remains(self) -> None:
        self.assertEqual(
            self.structure["onlyAllowedOrder"],
            [
                "title",
                "reader-empathy-quotes",
                "goldhand-value-proof-table",
                "three-minute-solution-preview",
                "numbered-answer-sections",
                "closing-summary",
                "cta",
            ],
        )
        self.assertEqual(
            self.structure["authority"],
            "references/information-delivery-structure.md",
        )
        self.assertTrue(self.structure["numberedAnswers"]["generatedTitlePromiseRequired"])
        self.assertTrue(self.structure["numberedAnswers"]["confirmedUserTitleMayOmitPromise"])
        self.assertTrue(self.structure["numberedAnswers"]["mustEqualTitlePromiseWhenPresent"])
        self.assertTrue(self.structure["closing"]["ctaMustBeFinalBlock"])
        self.assertEqual(
            self.structure["closing"]["allowedInnerFlows"],
            [
                "helpful-then-thanks-then-direct-evaluation",
                "n-points-benefit-then-next-step-then-thanks",
            ],
        )
        self.assertEqual(self.structure["closing"]["gratitudeCount"], 1)
        self.assertTrue(self.structure["closing"]["gratitudeWordingIsNonBindingExample"])
        self.assertTrue(
            self.structure["closing"]["exactGratitudeReuseAcrossManuscriptsForbidden"]
        )
        self.assertTrue(self.structure["closing"]["clinicNameOrRegionalKeywordForbidden"])
        self.assertTrue(self.structure["closing"]["neutralDirectEvaluationRequired"])
        self.assertNotIn(
            "gratitudeWording",
            self.structure["closing"]["helpfulThenThanksThenDirectEvaluation"],
        )
        self.assertNotIn(
            "gratitudeWording",
            self.structure["closing"]["nPointsBenefitThenNextStepThenThanks"],
        )
        self.assertTrue(
            self.structure["closing"]["nPointsBenefitThenNextStepThenThanks"][
                "countMustEqualTitlePromiseWhenPresent"
            ]
        )

    def test_competing_editorial_master_resources_are_absent(self) -> None:
        removed = {
            SCRIPTS: {
                "select_reference_master.py",
                "select_wipark_content_reference.py",
                "select_topic_idea.py",
                "validate_editorial_fidelity.py",
                "validate_editorial_master_profiles.py",
                "validate_reference_learning.py",
                "validate_reference_reconstruction.py",
                "build_wipark_master_profiles.py",
                "build_wipark_topic_idea_library.py",
                "recommend_" + "closing_trust_media.py",
                "record_" + "article_state.py",
                "validate_" + "natural_speech_suite.py",
                "validate_" + "final_voice_review.py",
            },
            REFERENCES: {
                "content-formulas.md",
                "reference-exact-reconstruction.md",
                "reference-editorial-reasoning.md",
                "reference-master-library.md",
                "editorial-close-adaptation.md",
                "wipark-content-source-policy.md",
                "general-information-retrieval.md",
                "topic-idea-types.md",
                "beomeo-topic-source-policy.md",
                "two-reader-hooks-reference-audit.md",
                "final-" + "humanize-korean-review.md",
                "final-" + "writing-voice-review.md",
            },
            ASSETS: {
                "reference-master-profiles.json",
                "reference-writing-intelligence.json",
                "beomeo-editorial-master-profiles.json",
                "two-reader-hooks-reference-family.json",
                "topic-idea-library.json",
                "goldhand-closing-links.json",
                "humanize-" + "korean-final-review-contract.json",
                "writing-" + "voice-final-review-contract.json",
            },
        }
        leftovers = [str(folder / name) for folder, names in removed.items() for name in names if (folder / name).exists()]
        self.assertEqual(leftovers, [])
        self.assertFalse((SKILL_DIR.parent / "writing-voice").exists())

    def test_removed_structure_schema_cannot_reappear_under_new_filenames(self) -> None:
        forbidden_tokens = {
            "before-" + "credential",
            "closing" + "Trust",
            "approved" + "Closing" + "Trust",
            "data-" + "trust-photo",
            "ordered" + "ContentAtoms",
            "ordered" + "GeneralInformation",
            "humanize-" + "korean-final",
            "main" + "Keyword",
            "reference" + "MasterId",
            "editorial" + "MasterId",
            "pre-" + "blind",
            "final" + "WritingVoiceReview",
            "data-writing-" + "voice",
            "independent" + "RevisionGroups",
        }
        leftovers: list[str] = []
        for path in SKILL_DIR.rglob("*"):
            if path.suffix not in {".py", ".md", ".json", ".yaml", ".yml"}:
                continue
            text = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                if token in text:
                    leftovers.append(f"{path.relative_to(SKILL_DIR)}:{token}")
        self.assertEqual(leftovers, [])

    def test_user_corrected_korean_failures_stay_blocked(self) -> None:
        self.assertEqual(NATURAL.contract_errors(self.natural), [])
        corrected = [
            rule
            for rule in self.natural["failurePatterns"]
            if rule.get("userCorrected") is True
        ]
        self.assertGreaterEqual(len(corrected), 2)
        for rule in corrected:
            with self.subTest(code=rule["code"]):
                failed = NATURAL.validate_text("", rule["failedExample"], self.natural)
                approved = NATURAL.validate_text("", rule["approvedExample"], self.natural)
                self.assertEqual(failed["status"], "fail")
                self.assertEqual(approved["status"], "pass")
        self.assertTrue(self.natural["mechanicalPassDoesNotProveNaturalness"])
        self.assertTrue(self.natural["userPriorityInterviewIsFinalUserGate"])
        self.assertTrue(self.natural["plainTextApprovalGateForbidden"])

    def test_medical_guarantees_and_pressure_cta_are_blocked(self) -> None:
        for phrase in ("완치", "무조건", "반드시 낫습니다", "효과를 보장합니다"):
            with self.subTest(phrase=phrase):
                self.assertIsNotNone(ARTICLE.FORBIDDEN["guarantee"].search(phrase))
        for phrase in ("지금 바로 예약하세요", "늦기 전에 내원하세요", "예약을 서두르세요"):
            with self.subTest(phrase=phrase):
                self.assertIsNotNone(ARTICLE.FORBIDDEN["aggressive-cta"].search(phrase))

    def test_user_corrected_closing_principles_are_permanent(self) -> None:
        corrections = {
            item["id"]: item for item in self.natural["contextualUserCorrections"]
        }
        self.assertEqual(
            set(corrections),
            {
                "gratitude-example-is-not-a-fixed-line",
                "clinic-name-makes-the-close-feel-like-an-ad",
            },
        )
        principles = {item["id"] for item in self.natural["generationPrinciples"]}
        self.assertIn("vary-gratitude-by-rhetorical-job", principles)
        self.assertIn("keep-closing-next-step-clinic-neutral", principles)


if __name__ == "__main__":
    unittest.main()
