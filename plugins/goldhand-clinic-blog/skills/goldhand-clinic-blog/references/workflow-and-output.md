# 금손 블로그 작업 순서와 출력

## 전체 순서

```text
버전 표시
→ 주제 확정
→ 숫자형 제목 5개 제안 또는 사용자 제목 확정
→ 선택한 주제에 대해 중요하게 생각하는 N가지 인터뷰와 답변 대기
→ 사용자 핵심 내용 확정
→ 필요한 보충 정보와 의료 경계 정리
→ 생활어 메모
→ 단일 구조 평문
→ 구조 검사
→ 독립 생활어·제목 검수
→ 사용자 핵심 내용 중심 여부 별도 검수
→ 내부 최종 평문 동결
→ 네이버 순정 HTML·이미지·디자인 자동 제작
→ 최종 검증과 결과 제시
```

메인키워드, SEO, 글자 수는 기본 단계가 아니다.
제목 확정 다음에 [사용자 핵심 내용 인터뷰](topic-priority-interview.md)를 한다. 주제 원문과 제목의 N가지를 사용해 질문하고 기다린다. 답변과 필요한 누락·충돌 확인이 끝난 뒤에는 승인이나 제작 선택을 묻지 않는다.

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

- 인터뷰 답변의 각 핵심 내용을 번호 답의 중심으로 정한 뒤, 저장 정보 박사에서 그 내용을 설명하는 주제·제목 관련 정보만 조회한다.
- 사용자 내용의 의미·강도·순서를 보존한다. 자료에 맞춰 사용자 항목을 대체하거나 도입·결론에만 덧붙이지 않는다.
- 여러 자료의 같은 뜻은 합친다.
- 부족한 경우에만 한국어 자료를 보충한다.
- 다른 업체의 사실·사례·문장·CTA는 사용하지 않는다.
- 금손 사실은 `clinic-facts.md`만 사용한다.
- 정보 출처는 글 구조를 결정하지 않는다.

## 인터뷰 답변 뒤 자동 진행

제목 확정 뒤 인터뷰 답변을 받고, 사용자가 중요하게 생각하는 내용을 중심으로 평문을 내부 검수용으로 작성한다. `평문 승인 대기`를 출력하거나 평문·이미지·HTML 진행 여부를 묻지 않고 최종 제작까지 이어간다.

## 최종 제작

1. 내부 검수를 통과한 제목과 문장을 동결한다.
2. 공감 질문을 네이버 순정 인용구로 바꾼다.
3. `[금손한의원 소개]` 블록을 같은 위치의 순정 표로 바꾼다.
4. 번호 답을 순정 소제목으로 표시한다.
5. 정리와 CTA를 글의 마지막으로 유지한다.
6. 이미지·강조·모바일 줄바꿈은 블록 순서를 바꾸지 않는 범위에서만 적용한다.
7. CTA 뒤에 운영정보 표, 지도, 관련 글을 자동 추가하지 않는다.

제작 때문에 문장을 바꿔야 하면 내부 평문 단계로 돌아가 구조 검사와 독립 생활어 검수를 다시 한 뒤 제작을 계속한다. 이미지 도구가 없거나 생성·게시가 실패하면 질문하지 않고 이미지 없는 완성본으로 끝낸다.

## 검증

내부 평문 검증:

```bash
python3 scripts/topic_priority_interview.py --topic "선택한 주제" --title "확정 제목" --input user-priorities.json --article article.txt --review independent-review.json
python3 scripts/validate_title.py --title "확정 제목" --answer-count N --json
python3 scripts/validate_information_article_structure.py --input article.txt --title "확정 제목" --json
python3 scripts/validate_natural_korean.py --input article.txt --title "확정 제목" --json
python3 scripts/validate_independent_natural_review.py --input independent-review.json --json
python3 scripts/validate_closing_set.py --input article-1.txt article-2.txt article-3.txt --json
```

최종 제작 검증:

```bash
python3 scripts/validate_information_article_structure.py --input article.html --title "확정 제목" --html --json
python3 scripts/topic_priority_interview.py --topic "선택한 주제" --title "확정 제목" --input user-priorities.json --article article.html --html --review independent-review.json
python3 scripts/validate_article.py --input article.html --title "확정 제목" --json
python3 scripts/validate_goldhand_voice.py --input article.html --json
python3 scripts/build_naver_copy_page.py --title "확정 제목" --article-html article.html
python3 scripts/validate_html.py --input "생성된 HTML 경로"
```
