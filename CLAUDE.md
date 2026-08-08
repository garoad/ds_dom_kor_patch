# NitroPacker / Days of Memories 한글화 프로젝트 — 폴더/기록 규칙

이 프로젝트에서 작업할 때는 아래 규칙을 항상 지킬 것. 컨텍스트 컴팩팅으로 대화 기록이 요약되어도
이 파일은 매 세션 자동으로 다시 로드되므로, 규칙 자체를 잊지 않도록 반드시 여기 최우선으로 따를 것.

## 1. 작업 기록은 `analysis/ANALYSIS_NOTES.md`에 남긴다

새로운 발견, 버그 수정, 확정된 코드/문자 매핑, 시행착오 등 "이 세션에서 무엇을 왜 했는가"에 해당하는
내용은 전부 `analysis/ANALYSIS_NOTES.md`에 append할 것. 대화가 끝나고 컴팩팅되면 대화 내용 자체는
사라지므로, 다음 세션에서 참고할 수 있는 유일한 진본은 이 파일과 auto-memory(`project_dom_hangulization.md`)
뿐이다. 작업을 마칠 때마다(중간에 끊기더라도) 그 시점까지의 진행 상황을 이 파일에 기록해둘 것 —
세션이 끝날 때 한 번에 몰아서 쓰지 말고, 발견/수정이 확정되는 즉시 기록.

## 2. 한글패치에 필요한 최종 산출물만 커밋/관리한다

- 파이프라인 스크립트 (`analysis/`): `mes_codec.py`, `speaker_map.py`, `translate_io.py`,
  `mes_translate_extract.py`, `mes_translate_reinsert.py`, `apply_font_art.py`, `lz10.py` 등
- 웹 툴 소스 코드 (`webtool/`): `server/`, `public/`, `package.json`, `tool.sh` 등 핵심 파일 (`node_modules/`, `workspace/`, 로그/임시파일 제외)
- 최종 데이터: `font_map_full.json`, `font_map_kr.json`, `tool.md`, `README.md`
- 기록: `ANALYSIS_NOTES.md`

1회성 조사/디버그 스크립트, 검증용 렌더링 이미지, 실험적 프로브 결과물은 커밋 대상에 두지 말 것.

## 3. 테스트/조사용 임시 자료는 프로젝트 루트의 `temp/`에 둔다 (`analysis/` 안이 아님)

`temp/`는 `analysis/`의 하위 폴더가 아니라 프로젝트 루트(워크스페이스 내 `temp/`,
`unpack/`·`analysis/`와 같은 층)에 둔다. 다음 유형은 전부 여기에 저장한다:
- 코드 확인용 1회성 스크립트 (예: `scan_all_codes_v8.py`, `render_tilestrip.py`)
- 그 스크립트들이 만들어내는 결과물 (`tilestrip_*.png`, `probe_*.png` 등)
- 실험적 프로브, 중간 검증 스크립트

`render_tilestrip.py`처럼 반복적으로 쓰는 조사 도구 자체도 `temp/`에 스크립트로 남겨두고, 매번
만들어내는 출력 이미지도 같은 곳에 둘 것 (분석이 끝났다고 최종 산출물 쪽으로 옮기지 말 것 — 최종
산출물은 위 2번 목록뿐). `temp/`의 스크립트는 `analysis/`의 `mes_codec.py` 등을 import하므로
실행 시 `PYTHONPATH=analysis`를 지정할 것(예: `export PYTHONPATH=analysis && python3 temp/render_tilestrip.py <hex>`).

## 4. 폰트 매핑 테이블 및 한글 타일 예산 엄격 준수

- **원문용/한글용 폰트 맵 분리**:
  - `analysis/font_map_full.json`: 순수 원본 일어/한자 매핑 테이블 (원문 추출 및 디코딩용). **절대 한글 글자를 덮어쓰지 말 것.**
  - `analysis/font_map_kr.json`: 한글 완성형 코드 매핑 테이블 (한글 텍스트 역인코딩 및 타일 렌더링용).
- **한글 타일 예산 상한 (1,559자)**:
  - 안전한 한글 할당 예산은 **정확히 1,559자** (한자 단독 소유 타일 1,359개 + 2×2 미사용 빈 슬롯 200개)로 제한된다.
  - 가나, 특수문자, 숫자, 제어코드 슬롯을 침범하는 2,350자 전체 완성형 할당은 시스템 기호 및 연출 파괴를 일으키므로 **절대 금지**한다.

## Why

작업 세션 중간에 컨텍스트가 컴팩팅되면 대화 기록의 세부사항(정확한 코드값, 수정 근거, 검증 과정)이
손실될 수 있다. `ANALYSIS_NOTES.md`와 폴더 구조 자체를 진본으로 유지해야 다음 세션이(혹은 컴팩팅
이후의 같은 세션이) 온전히 이어서 작업할 수 있다. 폴더가 섞이면(임시 파일이 최종 산출물과
뒤섞이면) 어느 게 신뢰할 수 있는 결과물인지 알 수 없게 되어 같은 조사를 반복하게 된다.
