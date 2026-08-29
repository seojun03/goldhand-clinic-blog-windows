from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "validate_closing_set.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("goldhand_closing_set", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = load_validator()


def manuscript(summary: str, cta: str) -> str:
    return f"""제목 2가지

1. 첫 번째 답

설명입니다.

2. 두 번째 답

설명입니다.

{summary}

{cta}
"""


class ClosingSetTests(unittest.TestCase):
    def write(self, folder: Path, name: str, summary: str, cta: str) -> Path:
        path = folder / name
        path.write_text(manuscript(summary, cta), encoding="utf-8")
        return path

    def test_different_natural_gratitude_sentences_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            first = self.write(
                folder,
                "first.txt",
                "오늘 글이 이해하는 데 도움이 되었기를 바랍니다. 긴 글 읽어주셔서 진심으로 감사드립니다.",
                "불편이 계속되면 직접 진료를 받아보시길 권합니다.",
            )
            second = self.write(
                folder,
                "second.txt",
                "두 가지를 기억해 두시면 실수를 줄일 수 있습니다.",
                "불편이 계속되면 직접 진료를 받아보시길 권합니다. 오늘 글도 끝까지 함께해 주셔서 고맙습니다.",
            )
            result = VALIDATOR.validate_manuscripts([first, second])
            self.assertEqual(result["status"], "pass", result["issues"])
            self.assertEqual(result["metrics"]["uniqueGratitudeSentenceCount"], 2)

    def test_exact_gratitude_reuse_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            phrase = "긴 글 읽어주셔서 진심으로 감사드립니다."
            first = self.write(folder, "first.txt", phrase, "직접 진료를 받아보시길 권합니다.")
            second = self.write(folder, "second.txt", phrase, "직접 진료를 받아보시길 권합니다.")
            result = VALIDATOR.validate_manuscripts([first, second])
            self.assertIn(
                "exact-gratitude-reused-across-manuscripts",
                {item["code"] for item in result["issues"]},
            )

    def test_clinic_name_and_booking_cues_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            first = self.write(
                folder,
                "first.txt",
                "긴 글 읽어주셔서 감사합니다.",
                "금손한의원에서 진료를 받아보시려면 예약 문의를 남겨주세요.",
            )
            second = self.write(
                folder,
                "second.txt",
                "오늘 글도 함께해 주셔서 고맙습니다.",
                "불편이 계속되면 직접 진료를 받아보시길 권합니다.",
            )
            result = VALIDATOR.validate_manuscripts([first, second])
            codes = {item["code"] for item in result["issues"]}
            self.assertIn("branded-closing-cta", codes)
            self.assertIn("sales-closing-cta", codes)


if __name__ == "__main__":
    unittest.main()
