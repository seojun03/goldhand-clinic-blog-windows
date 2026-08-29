from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
ASSETS = SKILL_DIR / "assets"


def load_module(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"goldhand_{name}_tests", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


QUERY = load_module("query_information_doctor")
STORE = load_module("store_information_doctor_sources")
COLLECT = load_module("collect_information_reference_blog")
VALIDATE = load_module("validate_general_information_library")


class InformationDoctorTests(unittest.TestCase):
    def source(self) -> dict[str, object]:
        return {
            "id": "USER-SLEEP-01",
            "sourceBlogId": "sleep-example",
            "sourceTitle": "서울 불면증 한의원 잠이 자주 깨는 이유",
            "sourceUrl": "https://blog.naver.com/sleep-example/123",
            "sourceType": "clinic-blog",
            "sourceClinicName": "서울잠한의원",
            "contentHash": "a" * 64,
            "learnedAt": "2026-08-29T00:00:00+00:00",
            "topic": "불면증과 중도 각성",
            "topicTags": ["불면증", "수면장애", "중도각성"],
            "readerQuestions": ["밤중에 반복해서 깨는 원인을 무엇부터 나눠 봐야 하는가?"],
            "titleAngles": [
                {
                    "angleId": "USER-SLEEP-01-T1",
                    "angle": "자주 깨는 밤을 만드는 생활 조건 두 가지",
                    "mechanism": "everyday-cause-count",
                    "supportedAnswerCount": 2,
                }
            ],
            "reviewStatus": "general-information-only-reviewed",
            "generalInformationOnly": True,
            "sourceClinicFactsBlocked": True,
            "sourceSentencesBlocked": True,
            "sourceCasesAndResultsBlocked": True,
            "sourceProgramsProductsEquipmentBlocked": True,
            "officialKoreanMedicalSupportRequiredAtDraftTime": True,
            "blockedEntities": ["서울잠한의원", "서울"],
            "generalInformationAtoms": [
                {
                    "id": "USER-SLEEP-01-A1",
                    "role": "sleep-pattern",
                    "observables": ["잠든 뒤 반복해서 깨는 시각과 횟수"],
                    "meaning": ["잠드는 어려움과 잠을 유지하는 어려움을 나누어 살핌"],
                    "generalInformationOnly": True,
                },
                {
                    "id": "USER-SLEEP-01-A2",
                    "role": "daily-load",
                    "observables": ["늦은 카페인 섭취와 불규칙한 취침 시각"],
                    "meaning": ["수면을 방해할 수 있는 생활 조건을 함께 확인"],
                    "generalInformationOnly": True,
                },
            ],
        }

    def library(self) -> dict[str, object]:
        library = json.loads(
            (ASSETS / "user-general-information-references.json").read_text(encoding="utf-8")
        )
        library["sources"] = [self.source()]
        library["knowledgeDoctor"]["storedSourceCount"] = 1
        return library

    def test_title_query_returns_compact_knowledge_without_source_prose_or_title(self) -> None:
        result = QUERY.title_query(
            "불면증",
            {"briefs": {}},
            self.library(),
        )
        self.assertEqual(result["status"], "stored-match")
        self.assertEqual(result["matchedSourceIds"], ["USER-SLEEP-01"])
        self.assertEqual(result["coverage"]["supportedAnswerCounts"], [1, 2])
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("서울 불면증 한의원", serialized)
        self.assertNotIn("generalInformationAtoms", serialized)
        self.assertTrue(result["boundaries"]["structureLoadedFromSources"] is False)
        self.assertEqual(
            result["boundaries"]["singleStructureAuthority"],
            "references/information-delivery-structure.md",
        )

    def test_title_query_does_not_force_cross_topic_source(self) -> None:
        result = QUERY.title_query(
            "이명",
            {"briefs": {}},
            self.library(),
        )
        self.assertEqual(result["status"], "no-stored-match")
        self.assertEqual(result["matchedSourceIds"], [])
        self.assertTrue(result["fallback"]["useTitleContractOnly"])

    def test_generic_aftereffect_word_does_not_mix_unrelated_conditions(self) -> None:
        traffic = self.source()
        traffic["id"] = "USER-TRAFFIC-01"
        traffic["sourceUrl"] = "https://blog.naver.com/example/traffic"
        traffic["contentHash"] = "b" * 64
        traffic["sourceTitle"] = "교통사고 후유증 정보"
        traffic["topic"] = "교통사고 후유증"
        traffic["topicTags"] = ["교통사고", "후유증"]
        flu = copy.deepcopy(traffic)
        flu["id"] = "USER-FLU-01"
        flu["sourceUrl"] = "https://blog.naver.com/example/flu"
        flu["contentHash"] = "c" * 64
        flu["sourceTitle"] = "독감 후유증 정보"
        flu["topic"] = "독감 후유증"
        flu["topicTags"] = ["독감", "후유증"]
        library = self.library()
        library["sources"] = [traffic, flu]
        result = QUERY.title_query(
            "교통사고 후유증",
            {"briefs": {}},
            library,
        )
        self.assertEqual(result["matchedSourceIds"], ["USER-TRAFFIC-01"])

    def test_same_url_and_hash_is_learned_only_once(self) -> None:
        library = self.library()
        updated, report = STORE.upsert(library, [copy.deepcopy(self.source())], refresh=False)
        self.assertEqual(report["status"], "unchanged")
        self.assertEqual(len(updated["sources"]), 1)
        self.assertEqual(report["skipped"][0]["reason"], "same-url-and-hash-already-learned")

    def test_changed_hash_requires_explicit_refresh(self) -> None:
        changed = self.source()
        changed["contentHash"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "--refresh"):
            STORE.upsert(self.library(), [changed], refresh=False)

    def test_raw_source_prose_cannot_enter_persistent_store(self) -> None:
        source = self.source()
        source["paragraphs"] = ["원문 문장"]
        with self.assertRaisesRegex(ValueError, "원문 보관 필드"):
            STORE.upsert(self.library(), [source], refresh=False)

    def test_title_query_supports_one_answer_when_only_one_distinct_atom_exists(self) -> None:
        source = self.source()
        source["generalInformationAtoms"] = source["generalInformationAtoms"][:1]
        source["titleAngles"] = [
            {
                "angleId": "USER-SLEEP-01-T1",
                "angle": "자주 깨는 밤을 만드는 생활 조건 한 가지",
                "mechanism": "everyday-cause-count",
                "supportedAnswerCount": 1,
            }
        ]
        library = self.library()
        library["sources"] = [source]
        result = QUERY.title_query("불면증", {"briefs": {}}, library)
        self.assertEqual(result["coverage"]["supportedAnswerCounts"], [1])
        self.assertEqual(result["titleAngles"][0]["supportedAnswerCount"], 1)

    def test_article_query_accepts_any_positive_answer_count(self) -> None:
        result = QUERY.query(
            stage="article",
            topic="불면증",
            title="불면증 원인 4가지",
            answer_count=4,
            briefs={"briefs": {}},
            library=self.library(),
            maximum_sources=12,
        )
        self.assertEqual(result["titleContract"]["requestedAnswerCount"], 4)
        with self.assertRaisesRegex(ValueError, "1개 이상"):
            QUERY.query(
                stage="article",
                topic="불면증",
                title="불면증 원인 0가지",
                answer_count=0,
                briefs={"briefs": {}},
                library=self.library(),
                maximum_sources=12,
            )

    def test_installed_information_library_has_reviewed_52_source_expansion(self) -> None:
        library = json.loads(
            (ASSETS / "user-general-information-references.json").read_text(encoding="utf-8")
        )
        self.assertEqual(VALIDATE.validate_library(library)["status"], "pass")
        self.assertEqual(len(library["sources"]), 52)
        self.assertEqual(library["knowledgeDoctor"]["storedSourceCount"], 52)
        counts: dict[str, int] = {}
        for source in library["sources"]:
            counts[source["sourceBlogId"]] = counts.get(source["sourceBlogId"], 0) + 1
        self.assertEqual(counts, {"beomeo_sm": 24, "wi-parkclinic": 28})
        self.assertEqual(
            sum(len(source["generalInformationAtoms"]) for source in library["sources"]),
            104,
        )

    def test_real_traffic_query_does_not_mix_flu_aftereffects(self) -> None:
        briefs = json.loads((ASSETS / "wipark-content-briefs.json").read_text(encoding="utf-8"))
        library = json.loads(
            (ASSETS / "user-general-information-references.json").read_text(encoding="utf-8")
        )
        result = QUERY.title_query("교통사고 후유증", briefs, library)
        self.assertIn("WIP-224355735689", result["matchedSourceIds"])
        self.assertNotIn("WIP-223720354779", result["matchedSourceIds"])

    def test_collector_blocks_notice_case_and_source_specific_posts(self) -> None:
        self.assertEqual(COLLECT.automatic_decision("8월 진료 안내", "건강 정보 본문")[0], "exclude")
        self.assertEqual(COLLECT.automatic_decision("환자 치료 사례", "원인 증상 관리 방법")[0], "exclude")
        self.assertEqual(COLLECT.automatic_decision("엑소웨이브 소개", "원인 증상 관리 방법")[0], "exclude")
        self.assertEqual(COLLECT.blog_id_from("https://m.blog.naver.com/beomeo_sm"), "beomeo_sm")


if __name__ == "__main__":
    unittest.main()
