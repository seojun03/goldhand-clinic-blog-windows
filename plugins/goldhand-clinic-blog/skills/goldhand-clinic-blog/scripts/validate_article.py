#!/usr/bin/env python3
"""Validate one approved Goldhand information article for structure and safety."""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = SKILL_DIR / "references" / "clinic-facts.md"
DEFAULT_MEDIA_LIBRARY = SKILL_DIR / "assets" / "media-library.json"
ALLOWED_TYPES = {"정보전달형"}
ALLOWED_IMAGE_FALLBACK_REASONS = {
    "image-generation-unavailable",
    "image-generation-failed",
    "image-generation-limit",
    "image-publication-failed",
}

FORBIDDEN = {
    "specialist": re.compile(r"(?:전문의|통증\s*전문|소아\s*전문|갑상선\s*전문|다이어트\s*전문)"),
    "guarantee": re.compile(r"(?:완치|무조건|반드시\s*(?:낫|호전)|100\s*%|효과를\s*보장|확실히\s*(?:낫|좋아))"),
    "superlative": re.compile(r"(?:지역\s*1위|광주\s*1위|전국\s*1위|유일한|최고의|최상급|가장\s*잘하는)"),
    "unsupported-metric": re.compile(r"(?:누적\s*환자|누적\s*추나|재방문율|소개율|만족도|후기\s*수)"),
    "wrong-obesity-credential": re.compile(r"한방\s*비만\s*치료\s*인증\s*전문\s*한의사"),
    "wrong-ministry-credential": re.compile(r"보건복지부\s*인증\s*(?:약침\s*치료|골타\s*요법|한의원)"),
    "remote-treatment": re.compile(r"카카오톡.{0,25}(?:비대면\s*(?:진료|치료|처방)|원격\s*(?:진료|치료))"),
    "aggressive-cta": re.compile(r"(?:지금\s*바로|당장|늦기\s*전에|서둘러|꼭\s*내원|반드시\s*내원|예약을\s*서두)"),
    "source-business-leak": re.compile(
        r"(?:위석부부한의원|설명한의원|김병규\s*(?:대표)?원장|박경화|린다이어트|엑소웨이브|미주안|미주란|라디쥬|보폐고\s*엔오|스파인\s*MT|쿨쎄라|라라샷|퓨라셀|라인약침)"
    ),
}

PRODUCTION_RESIDUE = {
    "placeholder": re.compile(r"(?:\{\{[^{}]+\}\}|\[\s*(?:사진|이미지|입력|작성|추가)[^\]]*\]|<\s*(?:입력|작성|추가)[^>]*>|\bT(?:ODO|BD)\b)", re.I),
    "internal-label": re.compile(r"\b(?:CHECK\s*\d+|FACT[-_]\d+|TEMP[-_]\d+|titlePromise|readerDecision|safeAuto|requiresReview)\b", re.I),
    "source-list": re.compile(r"(?m)^\s*(?:#{1,6}\s*)?(?:출처|참고문헌|References?)\s*:?")
}
EMOTICON = re.compile(r"(?:\^\^|ㅎㅎ|ㅠㅠ|ㅜㅜ|♥|❤|♡|#[0-9A-Za-z가-힣_]+)")
EMOJI = re.compile("[\U0001F1E6-\U0001FAFF\u2600-\u27BF]")
CASE_OR_EFFECT = re.compile(r"(?:환자.{0,24}(?:말했|호전|개선|나아|좋아|경과)|내원.{0,24}(?:후|경과|호전|개선)|치료\s*(?:후|경과)|호전|개선|나아졌|좋아졌|효과를\s*(?:봤|보았))")
DISCLAIMER = re.compile(r"(?:개인차|사람마다\s*다|상태에\s*따라\s*다|진찰이\s*필요|의료진.{0,12}상의)")
NUMERIC_CLAIM = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:%|퍼센트|명|건|회|년차|년|개월|주|일|시간|분)")


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff]", "", value)
    return value.strip()


def visible_text(value: str) -> str:
    value = re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<br\b[^>]*>|</?(?:p|div|section|article|h[1-6]|blockquote|li|tr|td|th|table|figure|figcaption)\b[^>]*>", "\n", value, flags=re.I)
    return normalize(html.unescape(re.sub(r"<[^>]+>", " ", value)))


def compact(value: str) -> str:
    return re.sub(r"\s+", "", visible_text(value))


def attr_values(fragment: str, attribute: str) -> list[str]:
    return [
        html.unescape(match.group(2)).strip()
        for match in re.finditer(rf"\b{re.escape(attribute)}\s*=\s*(['\"])(.*?)\1", fragment, re.I | re.S)
    ]


def add(issues: list[dict[str, object]], severity: str, code: str, detail: str) -> None:
    issues.append({"severity": severity, "code": code, "detail": detail})


def article_fragment(raw: str) -> str:
    matches = re.findall(r"<article\b[^>]*>.*?</article>", raw, flags=re.I | re.S)
    if len(matches) != 1:
        raise ValueError("입력에는 <article> 하나만 있어야 합니다.")
    return matches[0]


def load_media_library(path: Path = DEFAULT_MEDIA_LIBRARY) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    assets = payload.get("assets", []) if isinstance(payload, dict) else []
    return {
        str(asset["id"]): asset
        for asset in assets
        if isinstance(asset, dict) and asset.get("id")
    }


def media_context_tokens(value: str) -> list[str]:
    return re.findall(r"[0-9A-Za-z가-힣]{2,}", normalize(html.unescape(value)).lower())


def selected_media_context_leaks(
    article: str,
    media_library: dict[str, dict[str, object]],
    *,
    minimum_run: int = 7,
) -> list[dict[str, str]]:
    """Detect visible prose copied from a selected photo's internal notes."""

    if minimum_run < 1:
        raise ValueError("minimum_run은 1 이상이어야 합니다.")
    visible_tokens = media_context_tokens(visible_text(article))
    if len(visible_tokens) < minimum_run:
        return []
    visible_runs = {
        tuple(visible_tokens[index : index + minimum_run])
        for index in range(len(visible_tokens) - minimum_run + 1)
    }
    selected_ids = {
        asset_id
        for tag in re.findall(r"<img\b[^>]*>", article, flags=re.I | re.S)
        for asset_id in attr_values(tag, "data-goldhand-media")
        if asset_id
    }
    leaks: list[dict[str, str]] = []
    for asset_id in sorted(selected_ids):
        asset = media_library.get(asset_id)
        if not isinstance(asset, dict):
            continue
        source_tokens = media_context_tokens(str(asset.get("context", "")))
        for index in range(len(source_tokens) - minimum_run + 1):
            run = tuple(source_tokens[index : index + minimum_run])
            if run in visible_runs:
                leaks.append({"assetId": asset_id, "field": "context", "excerpt": " ".join(run)})
                break
    return leaks



def production_integrity(article: str, title: str) -> dict:
    spec = importlib.util.spec_from_file_location("goldhand_production_integrity", Path(__file__).with_name("validate_production_integrity.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate(article, title)

def structure_validation(article: str, title: str) -> dict[str, Any]:
    path = Path(__file__).with_name("validate_information_article_structure.py")
    spec = importlib.util.spec_from_file_location("goldhand_information_structure", path)
    if spec is None or spec.loader is None:
        raise ValueError("정보전달형 단일 구조 검증기를 불러올 수 없습니다.")
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    contract = json.loads(validator.DEFAULT_CONTRACT.read_text(encoding="utf-8"))
    proof = json.loads(validator.DEFAULT_VALUE_PROOF.read_text(encoding="utf-8"))
    return validator.validate_html(article, title, contract, proof)


def image_checks(article: str, issues: list[dict[str, object]]) -> dict[str, object]:
    opening = re.match(r"<article\b[^>]*>", article, flags=re.I | re.S)
    opening_tag = opening.group(0) if opening else ""
    modes = attr_values(opening_tag, "data-image-output-mode")
    reasons = attr_values(opening_tag, "data-image-fallback-reason")
    mode = modes[0] if len(modes) == 1 else "full-media" if not modes else ""
    reason = reasons[0] if len(reasons) == 1 else ""
    images = re.findall(r"<img\b[^>]*>", article, flags=re.I | re.S)
    if mode not in {"full-media", "text-only-fallback"}:
        add(issues, "error", "image-output-mode-invalid", "이미지 출력 방식은 full-media 또는 text-only-fallback이어야 합니다.")
    if mode == "text-only-fallback":
        if reason not in ALLOWED_IMAGE_FALLBACK_REASONS:
            add(issues, "error", "image-fallback-reason-invalid", "텍스트 전용 결과에는 허용된 이미지 실패 사유가 필요합니다.")
        if images or re.search(r"<figure\b|\bdata-local-image\s*=", article, flags=re.I):
            add(issues, "error", "text-only-fallback-image-present", "텍스트 전용 결과에는 이미지 요소를 남기지 않습니다.")
    elif reasons:
        add(issues, "error", "image-fallback-reason-unexpected", "일반 이미지 결과에는 fallback 사유를 쓰지 않습니다.")

    https_count = 0
    local_count = 0
    for index, tag in enumerate(images, start=1):
        sources = attr_values(tag, "src")
        locals_ = attr_values(tag, "data-local-image")
        source = sources[0] if len(sources) == 1 else ""
        local = locals_[0] if len(locals_) == 1 else ""
        if source.startswith("https://") and not local:
            https_count += 1
        elif local and not source:
            path = Path(local).expanduser()
            if path.is_absolute() and path.is_file():
                local_count += 1
            else:
                add(issues, "error", "local-image-missing", f"이미지 {index}의 로컬 파일을 읽을 수 없습니다: {path}")
        else:
            add(issues, "error", "invalid-image-source", f"이미지 {index}에는 HTTPS 주소 또는 유효한 로컬 파일 하나만 필요합니다.")
    return {"imageOutputMode": mode or "invalid", "imageFallbackReason": reason, "images": len(images), "httpsImages": https_count, "localImages": local_count}


def validate_article(
    raw: str,
    title: str,
    *,
    evidence: str = "",
    media_library: dict[str, dict[str, object]] | None = None,
    **_ignored: object,
) -> dict[str, Any]:
    """Validate the sole macro structure plus publication safety."""
    issues: list[dict[str, object]] = []
    try:
        article = article_fragment(normalize(raw))
    except ValueError as exc:
        add(issues, "error", "article-count", str(exc))
        article = normalize(raw)

    opening = re.match(r"<article\b[^>]*>", article, flags=re.I | re.S)
    opening_tag = opening.group(0) if opening else ""
    article_type = attr_values(opening_tag, "data-goldhand-type")
    if article_type != ["정보전달형"]:
        add(issues, "error", "invalid-type", "article의 data-goldhand-type은 정보전달형이어야 합니다.")
    if re.search(r"<h1\b", article, flags=re.I):
        add(issues, "error", "duplicate-title-heading", "제목은 네이버 제목 입력란에 두고 article 안에 h1으로 반복하지 않습니다.")
    if re.search(r"<figcaption\b", article, flags=re.I):
        add(issues, "error", "visible-image-caption-forbidden", "보이는 이미지 캡션을 자동으로 덧붙이지 않습니다.")

    try:
        structure = structure_validation(article, normalize(title))
        for issue in structure.get("issues", []):
            add(issues, str(issue.get("severity", "error")), str(issue.get("code", "information-structure")), str(issue.get("detail", "단일 구조를 확인하세요.")))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        structure = {"metrics": {}}
        add(issues, "error", "information-structure-load", str(exc))

    text = re.sub(r"\s+", " ", visible_text(article)).strip()
    for code, pattern in FORBIDDEN.items():
        if match := pattern.search(text):
            add(issues, "error", code, f"금지 표현: {match.group(0)}")
    for code, pattern in PRODUCTION_RESIDUE.items():
        if match := pattern.search(article):
            add(issues, "error", code, f"제작 흔적을 제거하세요: {visible_text(match.group(0)) or match.group(0)}")
    for code, pattern in (("emoticon", EMOTICON), ("emoji", EMOJI)):
        if match := pattern.search(text):
            add(issues, "error", code, f"장식 문자를 제거하세요: {match.group(0)}")
    if re.search(r"https?://(?:m\.|blog\.)?naver\.com/(?:beomeo_sm|wi-parkclinic)(?:/|\b)", article, re.I):
        add(issues, "error", "source-url-leak", "다른 한의원의 출처 URL을 article 본문에 넣지 않습니다.")

    evidence_text = evidence or (DEFAULT_EVIDENCE.read_text(encoding="utf-8") if DEFAULT_EVIDENCE.exists() else "")
    evidence_compact = compact(evidence_text)
    numeric_source = re.sub(
        r"<(?P<tag>[a-z][\w:-]*)\b(?=[^>]*\bdata-reference-role\s*=\s*['\"]solution-preview['\"])[^>]*>.*?</(?P=tag)>",
        " ",
        article,
        flags=re.I | re.S,
    )
    checked: set[str] = set()
    for match in NUMERIC_CLAIM.finditer(visible_text(numeric_source)):
        claim = match.group(0)
        signature = compact(claim)
        if signature in checked:
            continue
        checked.add(signature)
        if signature not in evidence_compact:
            add(issues, "error", "unsupported-numeric-claim", f"확인된 금손 사실에 없는 수치입니다: {claim}")

    if "보건복지부 인증" in text and not re.search(r"보건복지부 인증 원외탕전실.{0,30}약침|약침.{0,30}보건복지부 인증 원외탕전실", text):
        add(issues, "error", "certification-misattribution", "보건복지부 인증은 원외탕전실 제조 약침에만 정확히 연결합니다.")
    if CASE_OR_EFFECT.search(text) and not DISCLAIMER.search(text):
        add(issues, "error", "medical-disclaimer-missing", "치료 경과나 효과를 말할 때는 개인차와 진찰 필요성을 함께 밝혀야 합니다.")

    library = media_library if media_library is not None else load_media_library()
    for leak in selected_media_context_leaks(article, library):
        add(issues, "error", "visible-media-context-leak", f"{leak['assetId']} 사진의 내부 {leak['field']} 문장이 본문에 노출됐습니다: {leak['excerpt']}")
    issues.extend(production_integrity(article, title)["issues"])
    image_metrics = image_checks(article, issues)

    errors = sum(item["severity"] == "error" for item in issues)
    warnings = sum(item["severity"] == "warning" for item in issues)
    structure_metrics = structure.get("metrics", {}) if isinstance(structure, dict) else {}
    return {
        "status": "fail" if errors else "warning" if warnings else "pass",
        "metrics": {
            "structureContractId": "goldhand-single-information-delivery-structure-v1",
            "type": article_type[0] if len(article_type) == 1 else "",
            "nonWhitespaceChars": len(compact(title + text)),
            **image_metrics,
            "readerQuestionCount": structure_metrics.get("readerQuestionCount", 0),
            "numberedHeadingCount": structure_metrics.get("numberedHeadingCount", 0),
            "numberedHeadingNumbers": structure_metrics.get("numberedHeadingNumbers", []),
            "errors": errors,
            "warnings": warnings,
        },
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--evidence", action="append", type=Path, default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        raw = args.input.read_text(encoding="utf-8")
        evidence_paths = args.evidence or [DEFAULT_EVIDENCE]
        evidence = "\n".join(path.read_text(encoding="utf-8") for path in evidence_paths if path.exists())
        result = validate_article(raw, args.title, evidence=evidence)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"원고 검증 실패: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status: {result['status']}")
        for issue in result["issues"]:
            print(f"[{str(issue['severity']).upper()}] {issue['code']}: {issue['detail']}")
    return 1 if result["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
