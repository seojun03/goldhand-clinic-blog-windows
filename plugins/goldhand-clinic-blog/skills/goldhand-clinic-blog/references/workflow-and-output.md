# 금손 블로그 작업 순서와 출력

## 전체 순서

```text
버전 표시
→ 주제 확정
→ 숫자형 제목 5개 제안 또는 사용자 제목 확정
→ 정보와 의료 경계 정리
→ 생활어 메모
→ 단일 구조 평문
→ 구조 검사
→ 독립 생활어 검수
→ 제목과 평문 제시
→ 사용자 승인
→ 승인 뒤 제작
```

메인키워드, SEO, 글자 수는 기본 단계가 아니다.

## 평문 구조

평문은 [information-delivery-structure.md](information-delivery-structure.md)의 순서만 사용한다.

```text
제목
→ 독자 질문 인용구 2개 이상
→ 금손한의원 소개 표 내용
→ 3분 해결 예고와 독자 보상
→ 번호 답 n개
→ 허용된 마무리 역할 A 또는 B로 쓴 정리
→ 같은 역할을 이어받은 CTA
```

평문에는 표의 위치와 고정 문구를 확인할 수 있도록 다음 형식을 사용한다.

```text
[금손한의원 소개]
고정 행 1
고정 행 2
...
```

HTML, 이미지, 모바일 줄바꿈은 넣지 않는다.

마무리 역할 A는 `구체적인 내용이 도움이 되었길 바란다는 말 → 문맥에 맞게 새로 쓴 감사 → 일반적인 설명이라는 경계와 중립적인 직접 진료 권유`다. 역할 B는 `제목과 같은 n가지가 주는 이득 또는 피할 실수 → 중립적인 다음 행동 → 문맥에 맞게 새로 쓴 감사`다. 둘 다 같은 `정리 → CTA` 구조 안에서만 사용한다. 감사 예시는 문장 템플릿이 아니며, 마지막 두 블록에는 병원명과 예약·문의 유도를 넣지 않는다.

## 정보 수집

- 저장 정보 박사에서 주제와 제목에 맞는 일반 정보 원자만 조회한다.
- 여러 자료의 같은 뜻은 합친다.
- 부족한 경우에만 한국어 자료를 보충한다.
- 다른 업체의 사실·사례·문장·CTA는 사용하지 않는다.
- 금손 사실은 `clinic-facts.md`만 사용한다.
- 정보 출처는 글 구조를 결정하지 않는다.

## 사용자 승인 전

제목과 평문만 보여 주고 `평문 승인 대기` 상태로 멈춘다. 사용자가 수정하면 전체 구조 검사와 독립 생활어 검수를 다시 한다.

## 승인 뒤 제작

1. 승인된 제목과 문장을 동결한다.
2. 공감 질문을 네이버 순정 인용구로 바꾼다.
3. `[금손한의원 소개]` 블록을 같은 위치의 순정 표로 바꾼다.
4. 번호 답을 순정 소제목으로 표시한다.
5. 정리와 CTA를 글의 마지막으로 유지한다.
6. 이미지·강조·모바일 줄바꿈은 블록 순서를 바꾸지 않는 범위에서만 적용한다.
7. CTA 뒤에 운영정보 표, 지도, 관련 글을 자동 추가하지 않는다.

제작 때문에 문장을 바꿔야 하면 평문 단계로 돌아가 다시 승인받는다.

## 검증

승인 전:

```bash
python3 scripts/validate_title.py --title "확정 제목" --answer-count N --json
python3 scripts/validate_information_article_structure.py --input article.txt --title "확정 제목" --json
python3 scripts/validate_natural_korean.py --input article.txt --title "확정 제목" --json
python3 scripts/validate_independent_natural_review.py --input independent-review.json --json
python3 scripts/validate_closing_set.py --input article-1.txt article-2.txt article-3.txt --json
```

승인 뒤:

```bash
python3 scripts/validate_information_article_structure.py --input article.html --title "확정 제목" --html --json
python3 scripts/validate_article.py --input article.html --title "확정 제목" --json
python3 scripts/validate_goldhand_voice.py --input article.html --json
python3 scripts/build_naver_copy_page.py --title "확정 제목" --article-html article.html
python3 scripts/validate_html.py --input "생성된 HTML 경로"
```
