#!/usr/bin/env python3
"""Collect one Naver blog once for reviewed Goldhand information references.

The output is an intake packet, not a permanent knowledge store. It intentionally
keeps source prose only in the requested output file so an agent can paraphrase
eligible medical information into the curated information-doctor library.
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus, urlparse

import requests
from bs4 import BeautifulSoup


LIST_URL = "https://blog.naver.com/PostTitleListAsync.naver"
MOBILE_POST_URL = "https://m.blog.naver.com/{blog_id}/{log_no}"
USER_AGENT = "Mozilla/5.0 GoldhandInformationDoctorIntake/1.0"
BLOG_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

CONTACT_BOUNDARY = re.compile(
    r"(?:전화\s*문의|네이버\s*(?:톡톡|예약)|오시는\s*길|진료\s*시간|"
    r"상담\s*문의|예약\s*문의|주소\s*[:：]|대표전화|카카오톡)",
    re.I,
)
HARD_EXCLUDE = re.compile(
    r"(?:진료\s*(?:안내|일정|시간)|휴진|정상\s*진료|공휴일|명절|설\s*연휴|추석|"
    r"찾아오시는\s*길|오시는\s*길|주차\s*안내|업무협약|기부|봉사|학술대회|"
    r"이벤트|상품권|소비쿠폰|맛집|팝업\s*리뷰|원장\s*이야기|한의원\s*소개)",
    re.I,
)
CASE_OR_RESULT = re.compile(
    r"(?:치험|실례|사례|후기|완전히\s*개선|치료된|호전된|완화한|"
    r"환자(?:들)?의\s*공통점|\d+%\s*개선|\d+회\s*만에|회복\s*속도\s*\d+배)",
    re.I,
)
CLINIC_SELECTION = re.compile(
    r"(?:잘하는\s*(?:곳|한의원)|한의원\s*(?:고르는|선택)\s*(?:법|기준)|"
    r"과잉\s*진료|장점\s*\(|선택한\s*이유)",
    re.I,
)
SOURCE_SPECIFIC = re.compile(
    r"(?:엑소웨이브|미주안|미주란|라디쥬|퓨라셀|쿨쎄라|린다이어트|"
    r"라인약침|라라샷|스파인\s*MT|보폐고\s*엔오|보폐고엔오|극초단파|공명파)",
    re.I,
)
INFORMATION_SIGNALS = (
    "원인",
    "증상",
    "주의",
    "관리",
    "예방",
    "검사",
    "구분",
    "차이",
    "부작용",
    "복용",
    "생활습관",
    "운동",
    "스트레칭",
    "통증",
    "후유증",
    "보험",
    "적용",
    "언제",
    "왜",
    "방법",
    "치료",
)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).replace("\u200b", " ")).strip()


def parse_date(value: str) -> date:
    parts = [int(part) for part in re.findall(r"\d+", value)[:3]]
    if len(parts) != 3:
        raise ValueError(f"날짜를 읽을 수 없습니다: {value}")
    return date(*parts)


def blog_id_from(value: str) -> str:
    candidate = value.strip()
    if "://" in candidate:
        parsed = urlparse(candidate)
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.netloc.lower() not in {"blog.naver.com", "m.blog.naver.com"} or not parts:
            raise ValueError(f"지원하지 않는 네이버 블로그 주소입니다: {value}")
        candidate = parts[0]
    if BLOG_ID_RE.fullmatch(candidate) is None:
        raise ValueError(f"지원하지 않는 네이버 블로그 ID입니다: {candidate}")
    return candidate


def get_with_backoff(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    attempts: int = 6,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.get(url, params=params, timeout=40)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.isdigit() else min(30.0, 2.0 ** (attempt + 1))
                time.sleep(delay)
                continue
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "utf-8"
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(min(20.0, 1.5 ** (attempt + 1)))
    raise RuntimeError(f"공개 페이지 읽기 실패: {url}: {last_error or 'HTTP 429'}")


def load_post_list(session: requests.Session, blog_id: str, cutoff: date) -> tuple[list[dict[str, Any]], int]:
    selected: list[dict[str, Any]] = []
    total_count = 0
    page = 1
    while True:
        response = get_with_backoff(
            session,
            LIST_URL,
            params={
                "blogId": blog_id,
                "viewdate": "",
                "currentPage": page,
                "categoryNo": 0,
                "parentCategoryNo": "",
                "countPerPage": 30,
            },
        )
        data = json.loads(response.text.replace("\\'", "'"))
        total_count = int(data.get("totalCount", total_count or 0))
        posts = data.get("postList", [])
        if not posts:
            break
        reached_older = False
        for post in posts:
            published = parse_date(str(post.get("addDate", "")))
            if published >= cutoff:
                selected.append(post)
            else:
                reached_older = True
        if reached_older or len(selected) >= total_count:
            break
        page += 1
        time.sleep(0.4)
    return selected, total_count


def post_root(soup: BeautifulSoup) -> Any:
    return (
        soup.select_one(".se-main-container")
        or soup.select_one(".se_component_wrap")
        or soup.select_one("#postViewArea")
        or soup.select_one(".post_ct")
    )


def extract_paragraphs(soup: BeautifulSoup) -> list[str]:
    root = post_root(soup)
    if root is None:
        return []
    selectors = (
        ".se-text-paragraph",
        ".se_textarea p",
        ".se_textarea",
        "#postViewArea p",
    )
    nodes: list[Any] = []
    for selector in selectors:
        nodes = list(root.select(selector))
        if nodes:
            break
    if not nodes:
        nodes = [root]
    paragraphs: list[str] = []
    for node in nodes:
        value = clean(node.get_text(" ", strip=True))
        if not value:
            continue
        if CONTACT_BOUNDARY.search(value):
            break
        if re.fullmatch(r"https?://\S+", value):
            continue
        if value not in paragraphs:
            paragraphs.append(value)
    return paragraphs


def automatic_decision(title: str, body: str) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if HARD_EXCLUDE.search(title):
        return "exclude", ["notice-event-location-or-clinic-introduction"]
    if CASE_OR_RESULT.search(title):
        return "exclude", ["case-testimonial-or-outcome-led"]
    if CLINIC_SELECTION.search(title):
        return "exclude", ["clinic-selection-or-marketing-led"]
    if SOURCE_SPECIFIC.search(title):
        return "exclude", ["source-specific-product-device-or-program-led"]
    compact_body_length = len(re.sub(r"\s+", "", body))
    signal_count = sum(1 for signal in INFORMATION_SIGNALS if signal in f"{title} {body}")
    if compact_body_length < 350:
        reasons.append("body-too-short-for-information-learning")
    if signal_count < 2:
        reasons.append("insufficient-health-information-signals")
    if SOURCE_SPECIFIC.search(body) and signal_count < 5:
        reasons.append("body-dominated-by-source-specific-offering")
    if reasons:
        return "review", reasons
    return "candidate", ["general-health-information-present"]


def collect_post(
    session: requests.Session,
    blog_id: str,
    meta: dict[str, Any],
) -> dict[str, Any]:
    log_no = str(meta.get("logNo", ""))
    title = html_lib.unescape(unquote_plus(str(meta.get("title", ""))))
    published = parse_date(str(meta.get("addDate", ""))).isoformat()
    response = get_with_backoff(session, MOBILE_POST_URL.format(blog_id=blog_id, log_no=log_no))
    soup = BeautifulSoup(response.text, "html.parser")
    paragraphs = extract_paragraphs(soup)
    if not paragraphs:
        raise RuntimeError(f"본문 텍스트를 찾지 못했습니다: {blog_id}/{log_no}")
    body = "\n".join(paragraphs)
    decision, reasons = automatic_decision(title, body)
    normalized = clean(body)
    return {
        "id": f"NAVER-{blog_id}-{log_no}",
        "sourceBlogId": blog_id,
        "sourceTitle": title,
        "sourceUrl": f"https://blog.naver.com/{blog_id}/{log_no}",
        "publishedAt": published,
        "categoryNo": str(meta.get("categoryNo", "")),
        "contentHash": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "automaticDecision": decision,
        "automaticReasons": reasons,
        "informationSignalCount": sum(1 for signal in INFORMATION_SIGNALS if signal in f"{title} {body}"),
        "nonWhitespaceCharacters": len(re.sub(r"\s+", "", body)),
        "paragraphs": paragraphs,
        "sourceUsePolicy": {
            "temporarySourceProseOnly": True,
            "mustParaphraseBeforePermanentStorage": True,
            "generalInformationOnly": True,
            "sourceClinicFactsBlocked": True,
            "sourceSentencesBlocked": True,
            "sourceCasesAndResultsBlocked": True,
            "sourceProgramsProductsEquipmentBlocked": True,
            "structureMasterMutationBlocked": True,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blog", required=True, help="Naver blog URL or blog ID")
    parser.add_argument("--cutoff", default="2000-01-01")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--delay", type=float, default=0.7)
    parser.add_argument("--maximum-posts", type=int)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        blog_id = blog_id_from(args.blog)
        cutoff = date.fromisoformat(args.cutoff)
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"})
        posts, total_count = load_post_list(session, blog_id, cutoff)
        if args.maximum_posts is not None:
            posts = posts[: max(0, args.maximum_posts)]
        existing: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        if args.resume and args.output.exists():
            previous = json.loads(args.output.read_text(encoding="utf-8"))
            existing = [item for item in previous.get("posts", []) if isinstance(item, dict)]
        seen = {str(item.get("sourceUrl", "")) for item in existing}
        for index, post in enumerate(posts):
            url = f"https://blog.naver.com/{blog_id}/{post.get('logNo', '')}"
            if url in seen:
                continue
            try:
                existing.append(collect_post(session, blog_id, post))
            except Exception as exc:  # noqa: BLE001 - intake must preserve each failure
                failures.append({"sourceUrl": url, "error": str(exc)})
            if index + 1 < len(posts):
                time.sleep(max(0.0, args.delay))
        existing.sort(key=lambda item: (str(item.get("publishedAt", "")), str(item.get("sourceUrl", ""))), reverse=True)
        counts: dict[str, int] = {}
        for item in existing:
            decision = str(item.get("automaticDecision", "review"))
            counts[decision] = counts.get(decision, 0) + 1
        packet = {
            "schemaVersion": 1,
            "intakeRole": "temporary-agent-review-only",
            "sourceBlogId": blog_id,
            "sourceBlogUrl": f"https://blog.naver.com/{blog_id}",
            "collectedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sourceTotalCount": total_count,
            "requestedPostCount": len(posts),
            "fetchedPostCount": len(existing),
            "failureCount": len(failures),
            "automaticDecisionCounts": counts,
            "failures": failures,
            "posts": existing,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, UnicodeError, ValueError, RuntimeError, requests.RequestException, json.JSONDecodeError) as exc:
        print(f"정보 레퍼런스 수집 실패: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": "pass" if not failures else "partial",
                "blogId": blog_id,
                "listed": len(posts),
                "fetched": len(existing),
                "failed": len(failures),
                "decisions": counts,
                "output": str(args.output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
