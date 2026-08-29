from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SELECTOR_PATH = SKILL_DIR / "scripts" / "select_general_information.py"


def load_selector():
    spec = importlib.util.spec_from_file_location("goldhand_sensitive_information", SELECTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("민감 주제 정보 선택기를 불러오지 못했습니다.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SELECTOR = load_selector()


class SensitiveTopicGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.briefs = json.loads(
            (SKILL_DIR / "assets" / "wipark-content-briefs.json").read_text(encoding="utf-8")
        )
        cls.library = json.loads(
            (SKILL_DIR / "assets" / "user-general-information-references.json").read_text(
                encoding="utf-8"
            )
        )

    def select(self, topic: str, title: str) -> dict[str, object]:
        return SELECTOR.select_information(topic, title, self.briefs, self.library)

    @staticmethod
    def source_ids(result: dict[str, object]) -> set[str]:
        return {str(source["id"]) for source in result["storedSources"]}

    @staticmethod
    def source_atom_ids(result: dict[str, object], source_id: str) -> set[str]:
        return {
            str(atom_id)
            for atom in result["mergedInformationAtoms"]
            for atom_id in atom["sourceAtomIds"]
            if str(atom_id).startswith(f"{source_id}-")
        }

    def test_broad_and_unrelated_queries_do_not_load_sensitive_information(self) -> None:
        for topic, title in (
            ("생활 관리", "생활 관리에서 바꿀 습관 2가지"),
            ("허리 통증", "허리가 아플 때 피해야 할 행동 2가지"),
            ("소화불량", "속이 더부룩할 때 확인할 원인 3가지"),
        ):
            with self.subTest(topic=topic):
                selected = self.source_ids(self.select(topic, title))
                self.assertTrue({"INFO04", "INFO11"}.isdisjoint(selected), selected)

    def test_explicit_trauma_topic_can_use_info11_information_atoms(self) -> None:
        for topic in ("트라우마", "외상 후 스트레스", "PTSD"):
            with self.subTest(topic=topic):
                result = self.select(topic, f"{topic} 뒤 힘들 때 알아야 할 점 2가지")
                self.assertIn("INFO11", self.source_ids(result))
                self.assertTrue(self.source_atom_ids(result, "INFO11"))

    def test_insomnia_uses_sleep_atoms_without_panic_only_atoms(self) -> None:
        result = self.select("불면증", "잠이 오지 않을 때 확인할 원인 2가지")
        self.assertIn("INFO04", self.source_ids(result))
        self.assertEqual(
            self.source_atom_ids(result, "INFO04"),
            {"INFO04-A1", "INFO04-A3"},
        )

    def test_explicit_panic_context_unlocks_panic_atoms(self) -> None:
        result = self.select("공황장애와 불면증", "공황과 불면이 겹칠 때 볼 점 3가지")
        atom_ids = self.source_atom_ids(result, "INFO04")
        self.assertIn("INFO04-A2", atom_ids)
        self.assertIn("INFO04-A4", atom_ids)

    def test_trauma_source_is_never_a_generic_fallback(self) -> None:
        result = self.select("정신건강 상담", "마음이 지칠 때 확인할 점 2가지")
        self.assertNotIn("INFO11", self.source_ids(result))


if __name__ == "__main__":
    unittest.main()
