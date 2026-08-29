#!/usr/bin/env python3
"""Validate Goldhand spoken Korean without defining an article structure."""

from __future__ import annotations

import argparse
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = SKILL_DIR / "assets" / "goldhand-official-voice-profile.json"


class ProseParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"table", "script", "style"}:
            self.skip_depth += 1
        elif tag == "br" and not self.skip_depth:
            self.parts.append(" ")
        elif tag in {"p", "section", "blockquote", "h2", "h3", "article"} and not self.skip_depth:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"table", "script", "style"} and self.skip_depth:
            self.skip_depth -= 1
        elif tag in {"p", "section", "blockquote", "h2", "h3", "article"} and not self.skip_depth:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def attr_values(fragment: str, name: str) -> list[str]:
    match = re.search(r"<article\b(?P<attrs>[^>]*)>", fragment, re.I | re.S)
    if not match:
        return []
    return re.findall(rf"\b{re.escape(name)}\s*=\s*['\"]([^'\"]+)['\"]", match.group("attrs"), re.I)


def prose_text(fragment: str) -> str:
    if "<" not in fragment:
        return re.sub(r"[ \t]+", " ", html.unescape(fragment)).strip()
    parser = ProseParser()
    parser.feed(fragment)
    return re.sub(r"[ \t]+", " ", html.unescape("".join(parser.parts))).strip()


def sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def validate(
    fragment: str,
    profile: dict[str, Any],
    *,
    require_html_metadata: bool = True,
) -> dict[str, Any]:
    text = prose_text(fragment)
    compact = re.sub(r"\s+", "", text)
    issues: list[dict[str, str]] = []

    def error(code: str, detail: str) -> None:
        issues.append({"severity": "error", "code": code, "detail": detail})

    profile_id = str(profile.get("profileId", "goldhand-natural-spoken-korean-v1"))
    if require_html_metadata and attr_values(fragment, "data-goldhand-voice-profile") != [profile_id]:
        error(
            "voice-profile-missing",
            f"article에 data-goldhand-voice-profile={profile_id}가 정확히 한 번 필요합니다.",
        )

    forbidden = profile.get("forbidden", {})
    required = profile.get("requiredSignals", {})
    limits = profile.get("cadenceLimits", {})
    if not isinstance(forbidden, dict) or not isinstance(required, dict) or not isinstance(limits, dict):
        error("voice-profile-shape", "말투 프로필의 requiredSignals, cadenceLimits, forbidden은 객체여야 합니다.")
        forbidden, required, limits = {}, {}, {}

    for value in forbidden.get("emoticons", []):
        if value and str(value) in text:
            error("emoticon", f"금지된 이모티콘·장식이 있습니다: {value}")
    if match := re.search("[\U0001F1E6-\U0001FAFF\u2600-\u27BF]", text):
        error("emoji", f"이모지는 사용하지 않습니다: {match.group(0)}")
    for phrase in forbidden.get("aiTemplatePhrases", []):
        if phrase and str(phrase) in text:
            error("ai-template-phrase", f"실제 말보다 문서 문구에 가까운 표현이 있습니다: {phrase}")

    patterns = forbidden.get("aiRegisterPatterns", [])
    active_count = int(forbidden.get("activeAiRegisterPatternCount", len(patterns)))
    for rule in patterns[:active_count]:
        if not isinstance(rule, dict) or not str(rule.get("pattern", "")).strip():
            continue
        try:
            match = re.search(str(rule["pattern"]), text, re.I | re.S)
        except re.error as exc:
            error("voice-profile-pattern-invalid", f"말투 프로필 정규식이 잘못되었습니다: {exc}")
            continue
        if match:
            detail = str(rule.get("detail", "실제 한국인이 자주 쓰는 말로 다시 쓰세요."))
            excerpt = re.sub(r"\s+", " ", match.group(0)).strip()
            error(str(rule.get("code", "ai-register-pattern")), f"{detail} 감지 문장: {excerpt}")

    all_sentences = sentences(text)
    first_person = len(re.findall(r"(?:제가|저는|저도|저희|박원장)", text))
    conversational = len(re.findall(r"(?:죠|거든요|네요|세요|했어요|에요|예요)(?:[.!?]|\s|$)", text))
    transitions = sum(text.count(str(value)) for value in required.get("candidTransitions", []))
    scene_noun = re.compile(
        r"(?:앉|서서|걷|계단|화면|스마트폰|고개|목|어깨|팔|손|허리|골반|무릎|발|잠|수면|식사|출근|운전|일어나|야식|커피|밥)"
    )
    scene_action = re.compile(
        r"(?:아프|뻐근|저리|힘들|빠지|휘청|숙이|돌리|올리|내리|깨|자|먹|걷|앉|서|움직|일하|운전|답답|두근|붓|지치|굶)"
    )
    concrete_scenes = sum(1 for sentence in all_sentences if scene_noun.search(sentence) and scene_action.search(sentence))

    minimums = (
        ("first-person-dropout", first_person, int(required.get("minimumFirstPersonSignalsOutsideGreeting", 0)), "원장의 1인칭 판단"),
        ("ending-monotony", conversational, int(required.get("minimumConversationalEndings", 0)), "자연스러운 대화형 종결"),
        ("candid-transition-dropout", transitions, int(required.get("minimumCandidTransitionSignals", 0)), "뜻이 실제로 이어지는 연결"),
        ("concrete-scene-dropout", concrete_scenes, int(required.get("minimumConcreteDailyScenes", 0)), "구체적인 생활 장면"),
    )
    for code, actual, minimum, label in minimums:
        if actual < minimum:
            error(code, f"{label}이 부족합니다. 요구 {minimum}, 현재 {actual}입니다.")

    possibility = len(re.findall(r"(?:수(?:는|도)?\s*없습니다|수(?:도)?\s*있습니다|일\s*수\s*있습니다)", text))
    process = len(re.findall(r"(?:확인합니다|확인해야\s*합니다|살핍니다|살펴야\s*합니다|판단합니다)", text))
    treatment_names = {
        name
        for name in ("침", "약침", "추나", "물리치료", "한약", "뜸", "부항", "골타요법", "공진단", "경옥고")
        if re.search(rf"(?<![가-힣]){re.escape(name)}(?:은|는|이|가|을|를|과|와|으로|만|도)?(?![가-힣])", text)
    }
    if possibility > int(limits.get("maximumPossibilityPhrases", 6)):
        error("possibility-ending-overuse", "‘~할 수 있습니다’가 반복됩니다. 가능한 조건과 실제 행동을 직접 말하세요.")
    if process > int(limits.get("maximumClinicalProcessPredicates", 8)):
        error("repeated-clinical-predicate", "‘확인합니다·살핍니다·판단합니다’가 반복됩니다. 무엇을 왜 보는지 구체적으로 쓰세요.")
    if len(treatment_names) > int(limits.get("maximumDistinctTreatmentNames", 4)):
        error("treatment-catalogue", "한 문맥에서 치료 이름을 목록처럼 늘어놓지 마세요.")

    longest_formal_run = 0
    current_run = 0
    for sentence in all_sentences:
        if re.search(r"(?:습니다|합니다|입니다|됩니다)[.!?]?$", sentence):
            current_run += 1
            longest_formal_run = max(longest_formal_run, current_run)
        else:
            current_run = 0
    maximum_formal_run = int(limits.get("maximumConsecutiveFormalEndings", 10))
    if longest_formal_run > maximum_formal_run:
        error("formal-ending-run", f"격식 종결이 {longest_formal_run}문장 연속입니다. 같은 어미가 계속 들리지 않게 문장 호흡을 다시 보세요.")

    return {
        "status": "fail" if issues else "pass",
        "metrics": {
            "profileId": profile_id,
            "nonWhitespaceChars": len(compact),
            "firstPersonSignals": first_person,
            "conversationalEndings": conversational,
            "candidTransitions": transitions,
            "concreteDailyScenes": concrete_scenes,
            "possibilityPhrases": possibility,
            "clinicalProcessPredicates": process,
            "distinctTreatmentNames": sorted(treatment_names),
            "longestFormalEndingRun": longest_formal_run,
            "naturalSpeechPatternErrors": len(issues),
            "errors": len(issues),
        },
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--plain-text", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        fragment = args.input.read_text(encoding="utf-8")
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
        if not isinstance(profile, dict):
            raise ValueError("말투 프로필은 JSON 객체여야 합니다.")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"말투 검수 입력을 읽지 못했습니다: {exc}")
        return 2
    result = validate(fragment, profile, require_html_metadata=not args.plain_text)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status: {result['status']}")
        for issue in result["issues"]:
            print(f"[ERROR] {issue['code']}: {issue['detail']}")
    return 1 if result["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
