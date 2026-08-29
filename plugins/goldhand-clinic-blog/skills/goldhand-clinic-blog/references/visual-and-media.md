# 승인 뒤 네이버 제작 계약

이 문서는 사용자가 평문을 승인한 뒤에만 읽는다. 글 구조와 문장을 만드는 문서가 아니다. 구조의 유일한 기준은 `information-delivery-structure.md`다.

## 절대 보존값

- 승인된 제목과 평문은 띄어쓰기와 조사까지 고치지 않는다.
- 블록 순서는 `공감 질문 → 금손한의원 소개 표 → 3분 해결 예고 → 번호 답 n개 → 전체 정리 → CTA` 그대로다.
- `[금손한의원 소개]`와 고정 행만 같은 위치의 네이버 순정 표로 바꾼다.
- CTA가 최종 콘텐츠 블록이다. 운영정보 표, 지도, 관련 글, FAQ, 이미지, 추가 요약을 CTA 뒤에 붙이지 않는다.
- 제작 중 문장 수정이 필요하면 자동으로 고치지 않고 평문 단계로 돌아가 다시 승인받는다.

## HTML 역할

승인된 평문을 `<article data-goldhand-type="정보전달형">` 하나로 조립한다.

```text
blockquote[data-reference-role="reader-question"] 2개 이상
table[data-native-table-purpose="credential"] 1개
[data-reference-role="solution-preview"] 1개
[data-reference-role="section-heading"] 제목 숫자만큼
[data-reference-role="closing-summary"] 1개
[data-reference-role="cta"] 1개이자 마지막
```

- 제목은 네이버 제목 입력란에 별도로 넣고 article 안에 중복하지 않는다.
- 소개 표는 `assets/goldhand-value-proof-library.json`의 제목과 고정 행을 그대로 사용한다.
- 번호 소제목의 역할값은 제목 숫자와 정확히 일치해야 한다.
- 지정된 역할 외의 글 블록을 만들지 않는다.

## 네이버 순정 표현

- 공감 질문은 네이버 순정 인용구로 조립한다.
- 번호 답은 네이버 순정 소제목으로 조립한다.
- 표는 실제 행과 열이 있는 순정 표만 사용한다.
- 모바일 줄바꿈은 승인 문장의 단어와 순서를 바꾸지 않고 시각적 줄만 나눈다.
- 강조는 읽는 데 실제로 도움이 되는 짧은 구절에만 사용하며, 개수를 맞추려고 문장을 고치지 않는다.
- 외부 업체의 클래스, 로고, 사진, 색상, 지도, 연락처를 복사하지 않는다.

## 이미지

- 이미지는 사용자가 승인한 뒤에만 계획하고 생성한다.
- 이미지가 필요하면 해당 번호 소제목의 설명 안에 배치한다. 소개 표와 해결 예고 사이, 전체 정리와 CTA 사이, CTA 뒤에는 넣지 않는다.
- 이미지 수를 맞추기 위해 문장을 추가하거나 설명 순서를 바꾸지 않는다.
- 실제 금손 사진은 `assets/media-library.json`에서 사용 가능한 것으로 표시된 자산만 쓴다.
- 생성 이미지와 실제 사진을 다른 한의원의 치료 장면이나 성과 증거처럼 보이게 만들지 않는다.
- 이미지 생성이나 게시가 실패하면 승인된 평문을 유지한 채 이미지 없는 결과로 전환할 수 있다.

## 제작 검증

```bash
python3 scripts/validate_information_article_structure.py --input article.html --title "확정 제목" --html --json
python3 scripts/validate_article.py --input article.html --title "확정 제목" --json
python3 scripts/validate_goldhand_voice.py --input article.html --json
python3 scripts/validate_html.py --input article.html
```

검사기는 승인된 문장을 고치는 도구가 아니다. 구조나 HTML 문제가 발견되면 조립을 고치고, 문장 자체의 수정이 필요하면 사용자 승인 단계로 돌아간다.
