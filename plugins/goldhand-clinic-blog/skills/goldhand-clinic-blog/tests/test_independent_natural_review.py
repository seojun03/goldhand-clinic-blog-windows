from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "validate_independent_natural_review.py"
PROOF = json.loads(
    (SKILL_DIR / "assets" / "goldhand-value-proof-library.json").read_text(
        encoding="utf-8"
    )
)
TITLE = "요요를 줄이려면 바꿔야 할 습관 2가지"


def load_validator():
    spec = importlib.util.spec_from_file_location("goldhand_independent_natural_review", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = load_validator()


def proof_block() -> str:
    return "\n".join([f"[{PROOF['headerText']}]", *PROOF["fixedRows"]])


def article(question: str) -> str:
    return f"""{TITLE}

> 살을 뺐는데 조금만 먹어도 다시 찌는 이유가 뭘까요?
> {question}

{proof_block()}

3분만 읽어보시면 왜 다시 찌는지, 무엇부터 바꿔야 하는지 알 수 있습니다.

1. 굶다시피 살을 뺀 뒤 예전처럼 먹습니다

먹는 양을 갑자기 줄였다면 예전만큼 한꺼번에 먹지 마세요.

2. 살을 뺄 때만 일찍 자고 운동합니다

늦게까지 깨어 있으면 야식을 먹기 쉽고 다음 날 운동하기도 어렵습니다.

살을 뺀 뒤 다시 찌는 이유를 이해하는 데 오늘 글이 도움이 되었기를 바랍니다. 긴 글 읽어주셔서 진심으로 감사드립니다.

다만 이 글은 요요를 이해하기 위한 일반적인 설명입니다. 혼자 조절하기 어렵다면 직접 진료를 받아보시길 권합니다.
"""


class IndependentNaturalReviewTests(unittest.TestCase):
    def make_case(self, folder: Path) -> tuple[Path, dict]:
        before = article("다이어트가 끝난 뒤에는 어떻게 먹어야 요요가 덜 올까요?")
        final = article("다이어트가 끝난 뒤에는 어떻게 먹어야 요요를 줄일 수 있을까요?")
        (folder / "before-review.txt").write_text(before, encoding="utf-8")
        (folder / "article.txt").write_text(final, encoding="utf-8")
        sentence_count = len(
            VALIDATOR.reviewable_sentences(final, TITLE, PROOF["fixedRows"])
        )
        receipt = {
            "schemaVersion": 1,
            "contractId": VALIDATOR.CONTRACT_ID,
            "title": TITLE,
            "beforePlainTextFile": "before-review.txt",
            "finalPlainTextFile": "article.txt",
            "beforeDraftSha256": VALIDATOR.sha256_text(before),
            "finalDraftSha256": VALIDATOR.sha256_text(final),
            "draftAuthor": "goldhand-draft-writer",
            "reviewer": "independent-reviewer-test",
            "draftReviewerSeparated": True,
            "reviewerRole": VALIDATOR.REVIEWER_ROLE,
            "reviewerInputMode": VALIDATOR.INPUT_MODE,
            "reviewerReport": (
                "두 번째 공감 질문의 ‘요요가 오다’라는 결합이 실제 환자가 묻는 말보다 번역투에 가까웠습니다. "
                "질문의 행동과 결과가 바로 들리도록 고쳤고, 소개 뒤 해결 예고에서 번호 답으로 넘어가는 흐름과 "
                "마지막 정리에서 진료 안내로 이어지는 흐름도 전체 평문으로 다시 읽었습니다."
            ),
            "meaningPreservationReport": (
                "굶다시피 감량한 뒤 식사량을 갑자기 늘리지 말아야 한다는 정보와, 수면과 운동을 감량 뒤에도 "
                "이어가야 한다는 두 가지 답을 그대로 보존했습니다. 치료 결과를 새로 만들거나 보장하지 않았습니다."
            ),
            "wholeDraftRereadReport": (
                "수정한 질문만 확인하지 않고 제목부터 CTA까지 다시 읽었습니다. 공감 질문 세트가 같은 뜻을 "
                "반복하지 않는지, 소개 표 뒤 3분 예고가 첫 번째 답으로 바로 이어지는지, 두 번째 답 뒤의 정리가 "
                "본문을 그대로 복창하지 않는지 확인했습니다."
            ),
            "findings": [
                {
                    "before": "다이어트가 끝난 뒤에는 어떻게 먹어야 요요가 덜 올까요?",
                    "after": "다이어트가 끝난 뒤에는 어떻게 먹어야 요요를 줄일 수 있을까요?",
                    "reason": "이 질문에서는 ‘요요가 오다’보다 결과를 직접 말하는 ‘요요를 줄이다’가 실제 한국어 질문에 가깝습니다.",
                }
            ],
            "flowChecks": [
                {
                    "fromExcerpt": "3분만 읽어보시면 왜 다시 찌는지, 무엇부터 바꿔야 하는지 알 수 있습니다.",
                    "toExcerpt": "1. 굶다시피 살을 뺀 뒤 예전처럼 먹습니다",
                    "reason": "해결 예고에서 약속한 ‘왜 다시 찌는지’에 첫 번째 소제목이 곧바로 한 가지 원인으로 답합니다.",
                },
                {
                    "fromExcerpt": "살을 뺀 뒤 다시 찌는 이유를 이해하는 데 오늘 글이 도움이 되었기를 바랍니다. 긴 글 읽어주셔서 진심으로 감사드립니다.",
                    "toExcerpt": "다만 이 글은 요요를 이해하기 위한 일반적인 설명입니다. 혼자 조절하기 어렵다면 직접 진료를 받아보시길 권합니다.",
                    "reason": "요요가 생기는 이유를 회수하고 감사한 뒤, 일반적인 설명이라는 경계와 특정 병원명을 넣지 않은 진료 권유로 이어집니다.",
                },
            ],
            "remainingAwkwardPassages": [],
            "auditedSentenceCount": sentence_count,
            "sentenceIndexesChecked": list(range(1, sentence_count + 1)),
            "productionHandoffStatus": "ready-for-automatic-production",
        }
        path = folder / "independent-review.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        return path, receipt

    def test_concrete_independent_review_receipt_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path, receipt = self.make_case(Path(tmp))
            result = VALIDATOR.validate_receipt(path, receipt)
            self.assertEqual(result["status"], "pass", result["issues"])
            self.assertTrue(result["mechanicalPassDoesNotProveNaturalness"])
            self.assertFalse(result["plainTextApprovalRequired"])
            self.assertTrue(result["automaticProductionHandoffReady"])

    def test_true_style_or_generic_review_is_not_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path, receipt = self.make_case(Path(tmp))
            receipt["findings"] = []
            receipt["reviewerReport"] = "더 자연스럽게 다듬었습니다."
            result = VALIDATOR.validate_receipt(path, receipt)
            codes = {item["code"] for item in result["issues"]}
            self.assertIn("concrete-findings-missing", codes)
            self.assertIn("review-report-too-vague", codes)

    def test_hash_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path, receipt = self.make_case(Path(tmp))
            receipt["finalDraftSha256"] = "0" * 64
            result = VALIDATOR.validate_receipt(path, receipt)
            self.assertIn(
                "final-hash-mismatch",
                {item["code"] for item in result["issues"]},
            )

    def test_single_structure_failure_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            path, receipt = self.make_case(folder)
            final_path = folder / "article.txt"
            broken = final_path.read_text(encoding="utf-8").replace(
                "먹는 양을 갑자기 줄였다면 예전만큼 한꺼번에 먹지 마세요.",
                "먹는 양을 갑자기 줄였다면 예전만큼 한꺼번에 먹지 마세요.\n\n추가 조언\n\n야식도 줄이세요.",
            )
            final_path.write_text(broken, encoding="utf-8")
            receipt["finalDraftSha256"] = VALIDATOR.sha256_text(broken)
            receipt["auditedSentenceCount"] = len(
                VALIDATOR.reviewable_sentences(broken, TITLE, PROOF["fixedRows"])
            )
            receipt["sentenceIndexesChecked"] = list(
                range(1, receipt["auditedSentenceCount"] + 1)
            )
            result = VALIDATOR.validate_receipt(path, receipt)
            self.assertIn(
                "single-structure-failed",
                {item["code"] for item in result["issues"]},
            )


if __name__ == "__main__":
    unittest.main()
