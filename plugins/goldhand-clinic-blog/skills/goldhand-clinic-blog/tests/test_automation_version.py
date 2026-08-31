from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = SKILL_DIR.parents[1]
REFRESH_PATH = PLUGIN_ROOT / "scripts" / "refresh_plugin.py"


def load_refresh_module():
    spec = importlib.util.spec_from_file_location(
        "goldhand_refresh_plugin_version_tests",
        REFRESH_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"새로고침 모듈을 불러올 수 없습니다: {REFRESH_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REFRESH = load_refresh_module()


class AutomationVersionTests(unittest.TestCase):
    def make_plugin(self, root: Path) -> tuple[Path, Path, Path]:
        manifest = root / ".codex-plugin" / "plugin.json"
        skill = root / "skills" / "goldhand-clinic-blog" / "SKILL.md"
        state = (
            root
            / "skills"
            / "goldhand-clinic-blog"
            / "assets"
            / "automation-version.json"
        )
        manifest.parent.mkdir(parents=True)
        skill.parent.mkdir(parents=True)
        state.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps(
                {
                    "name": "goldhand-clinic-blog",
                    "version": "1.0.0+codex.20260827000000",
                    "description": "test",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        skill.write_text(
            "# 금손한의원 블로그 자동화\n\n"
            "## 시작 표시와 자동화 버전\n\n"
            "- 현재 자동화 버전: `1.0`\n"
            "- 사용자에게는 아래 한 문장만 정확히 보인다.\n\n"
            "  `버전 v{automationVersion} 업데이트 된 시각 {displayUpdatedAtKst}`\n",
            encoding="utf-8",
        )
        state.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "automationVersion": "1.0",
                    "sourceFingerprint": "",
                    "packageVersion": "",
                    "updatedAt": "",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return manifest, skill, state

    def test_initial_baseline_is_v1_0_without_an_extra_bump(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name) / "plugin"
            manifest, skill, state = self.make_plugin(root)
            result = REFRESH.sync_automation_version(
                root,
                now="2026-08-27T00:00:00+00:00",
            )
            self.assertTrue(result["initialized"])
            self.assertFalse(result["contentChanged"])
            self.assertTrue(result["needsCachebuster"])
            self.assertEqual(result["currentVersion"], "1.0")
            self.assertIn("현재 자동화 버전: `1.0`", skill.read_text(encoding="utf-8"))
            self.assertTrue(
                json.loads(manifest.read_text(encoding="utf-8"))["version"].startswith(
                    "1.0.0+codex."
                )
            )
            self.assertTrue(
                json.loads(state.read_text(encoding="utf-8"))["sourceFingerprint"]
            )
            self.assertEqual(
                json.loads(state.read_text(encoding="utf-8"))["displayUpdatedAtKst"],
                "2026.08.27 09:00",
            )

    def test_crlf_skill_initializes_with_the_same_managed_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name) / "plugin"
            manifest, skill, state = self.make_plugin(root)
            skill.write_bytes(
                skill.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8")
            )

            result = REFRESH.sync_automation_version(
                root,
                now="2026-08-27T00:00:00+00:00",
            )

            self.assertTrue(result["initialized"])
            self.assertFalse(result["contentChanged"])
            self.assertEqual(result["currentVersion"], "1.0")
            self.assertTrue(
                json.loads(state.read_text(encoding="utf-8"))["sourceFingerprint"]
            )

    def test_one_source_update_bumps_once_and_retry_keeps_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name) / "plugin"
            manifest, skill, state = self.make_plugin(root)
            REFRESH.sync_automation_version(root, now="2026-08-27T00:00:00+00:00")
            REFRESH.mark_package_version(root, now="2026-08-27T00:00:01+00:00")

            runtime_file = root / "skills" / "goldhand-clinic-blog" / "scripts" / "runtime.py"
            runtime_file.parent.mkdir(parents=True)
            runtime_file.write_text("VALUE = 1\n", encoding="utf-8")
            changed = REFRESH.sync_automation_version(
                root,
                now="2026-08-27T00:01:00+00:00",
            )
            self.assertTrue(changed["contentChanged"])
            self.assertEqual(changed["previousVersion"], "1.0")
            self.assertEqual(changed["currentVersion"], "1.1")
            self.assertTrue(changed["needsCachebuster"])
            self.assertIn("현재 자동화 버전: `1.1`", skill.read_text(encoding="utf-8"))
            self.assertEqual(changed["displayUpdatedAtKst"], "2026.08.27 09:01")
            self.assertTrue(
                json.loads(manifest.read_text(encoding="utf-8"))["version"].startswith(
                    "1.1.0+codex."
                )
            )

            retry = REFRESH.sync_automation_version(
                root,
                now="2026-08-27T00:02:00+00:00",
            )
            self.assertFalse(retry["contentChanged"])
            self.assertEqual(retry["currentVersion"], "1.1")
            self.assertTrue(retry["needsCachebuster"])
            self.assertEqual(
                json.loads(state.read_text(encoding="utf-8"))["automationVersion"],
                "1.1",
            )

            REFRESH.mark_package_version(root, now="2026-08-27T00:02:01+00:00")
            installed_retry = REFRESH.sync_automation_version(
                root,
                now="2026-08-27T00:03:00+00:00",
            )
            self.assertFalse(installed_retry["contentChanged"])
            self.assertFalse(installed_retry["needsCachebuster"])
            self.assertEqual(installed_retry["currentVersion"], "1.1")
            self.assertEqual(installed_retry["displayUpdatedAtKst"], "2026.08.27 09:01")

    def test_current_skill_starts_with_only_version_and_update_time(self) -> None:
        skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        agent_text = (SKILL_DIR / "agents" / "openai.yaml").read_text(
            encoding="utf-8"
        )
        state = json.loads(
            (SKILL_DIR / "assets" / "automation-version.json").read_text(
                encoding="utf-8"
            )
        )
        managed = REFRESH.managed_skill_version(SKILL_DIR / "SKILL.md")
        self.assertEqual(managed, state["automationVersion"])
        self.assertIn(
            "버전 v{automationVersion} 업데이트 된 시각 {displayUpdatedAtKst}",
            skill_text,
        )
        self.assertRegex(state["displayUpdatedAtKst"], r"^\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}$")
        self.assertEqual(
            state["displayUpdatedAtKst"],
            REFRESH.display_updated_at_kst(state["updatedAt"]),
        )
        self.assertNotIn("현재 버전 브리핑", skill_text)
        self.assertNotIn("금손한의원 블로그 자동화 v{현재 자동화 버전}을 시작합니다.", skill_text)
        self.assertNotIn("현재 버전: {현재 버전 브리핑}", skill_text)
        self.assertIn("output exactly the version line required by SKILL.md", agent_text)
        self.assertNotIn("and Korean briefing", agent_text)
        self.assertLess(
            skill_text.index("## 시작 표시와 자동화 버전"),
            skill_text.index("## 절대 구조 조건"),
        )

    def test_current_skill_starts_with_ten_topic_recommendations_and_accepts_direct_input(self) -> None:
        skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        readme_text = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        agent_text = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
        manifest = json.loads(
            (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )
        topic_question = "1~10번 중 작성할 주제를 선택하거나, 원하는 주제를 직접 입력해 주세요."
        title_question = "1~5번 중 사용할 제목을 선택하거나, 원하는 제목을 직접 입력해 주세요."
        topic_contract = json.loads(
            (SKILL_DIR / "assets" / "topic-recommendation-contract.json").read_text(
                encoding="utf-8"
            )
        )
        topic_library = json.loads(
            (SKILL_DIR / "assets" / topic_contract["sourceAsset"]).read_text(
                encoding="utf-8"
            )
        )
        eligible_topics = [
            item
            for item in topic_library[topic_contract["sourceCollection"]]
            if item.get("autoEligible") is True and item.get(topic_contract["sourceTextField"])
        ]

        self.assertIn(topic_question, skill_text)
        self.assertIn("메인키워드는 묻지 않는다", skill_text)
        self.assertIn(title_question, skill_text)
        self.assertLess(skill_text.index(topic_question), skill_text.index(title_question))

        self.assertIn("짧은 주제 키워드 10개를 추천", skill_text)
        self.assertIn("숫자형 제목을 정확히 5개 제안", skill_text)
        self.assertIn("글자 수는 우선순위와 기본 작업에 없다", skill_text)
        self.assertIn("한국어 자료", skill_text)
        self.assertIn("환자나 원장이 실제로 말할 법한 생활어", skill_text)
        self.assertIn("clinic-facts.md", skill_text)
        self.assertNotIn("현재 검토된 정보글 범위에서 연결할 수 없는 주제입니다", skill_text)
        self.assertNotIn("1. 자동모드  2. 정밀작성모드", skill_text)
        self.assertNotIn("정밀작성모드", skill_text)
        self.assertNotIn("정밀작성모드", readme_text)
        self.assertIn("offer exactly ten short topic keywords in source order and wait", agent_text)
        self.assertNotIn("메인키워드를 입력해 주세요.", agent_text)
        self.assertIn("offer exactly five natural Korean titles", agent_text)
        self.assertIn("주제 키워드 10개", readme_text)
        self.assertIn("제목 5개", readme_text)
        self.assertEqual(topic_contract["candidateCount"], 10)
        self.assertTrue(topic_contract["numberedOutputRequired"])
        self.assertEqual(topic_contract["displayFormat"], "{number}. {keyword}")
        self.assertTrue(topic_contract["keywordOnly"])
        self.assertTrue(topic_contract["descriptionsQuestionsAndSubtitlesForbidden"])
        self.assertFalse(topic_contract["researchRequiredBeforeRecommendations"])
        self.assertTrue(topic_contract["numberSelection"]["preserveExactCandidateText"])
        self.assertTrue(topic_contract["numberSelection"]["mustNotReplaceWithDetailedTopicIdea"])
        self.assertEqual(topic_contract["numberingStart"], 1)
        self.assertEqual(topic_contract["numberingEnd"], 10)
        self.assertEqual(topic_contract["selectionPrompt"], topic_question)
        self.assertTrue(topic_contract["customTopic"]["allowed"])
        self.assertTrue(topic_contract["customTopic"]["preserveExactUserWording"])
        self.assertGreaterEqual(len(eligible_topics), topic_contract["candidateCount"])
        self.assertEqual(
            len({item["keyword"] for item in eligible_topics}),
            len(eligible_topics),
        )
        self.assertGreaterEqual(
            len({item["topicCluster"] for item in eligible_topics}),
            5,
        )
        # Check the actual menu assembled from the configured source, not just metadata.
        rendered = [
            topic_contract["displayFormat"].format(number=number, **item)
            for number, item in enumerate(eligible_topics[:topic_contract["candidateCount"]], 1)
        ]
        self.assertEqual(rendered, [
            "1. 다이어트", "2. 교통사고", "3. 비염", "4. 추나요법", "5. 목 통증",
            "6. 허리 통증", "7. 소화불량", "8. 공진단", "9. 경옥고", "10. 아이 성장",
        ])
        detail_library = json.loads(
            (SKILL_DIR / "assets" / topic_library["relatedTopicSourceAsset"]).read_text(encoding="utf-8")
        )
        approved_idea_ids = {
            item["id"] for item in detail_library["topicIdeas"] if item.get("autoEligible") is True
        }
        for item in eligible_topics:
            self.assertTrue(item["relatedTopicIdeaIds"])
            self.assertTrue(set(item["relatedTopicIdeaIds"]) <= approved_idea_ids)
        self.assertTrue(
            any(
                "주제 키워드 10개" in prompt and "직접 입력" in prompt
                for prompt in manifest["interface"]["defaultPrompt"]
            )
        )
        self.assertTrue(
            all(
                "정밀작성모드" not in prompt
                for prompt in manifest["interface"]["defaultPrompt"]
            )
        )

    def test_update_time_uses_fixed_korean_standard_time(self) -> None:
        self.assertEqual(
            REFRESH.display_updated_at_kst("2026-08-29T03:01:00Z"),
            "2026.08.29 12:01",
        )
        with self.assertRaisesRegex(ValueError, "시간대가 없습니다"):
            REFRESH.display_updated_at_kst("2026-08-29T03:01:00")


if __name__ == "__main__":
    unittest.main()
