# 프로젝트 범위와 비범위

## 문제 정의

이미지 수집부터 캡셔닝, 학습, ComfyUI 검증까지의 정보가 폴더명, 셸 히스토리, workflow JSON, 파일명에 흩어지면 같은 결과를 재현하거나 체크포인트를 공정하게 비교하기 어렵다. 이 프로젝트는 대용량 파일 자체를 Git으로 관리하는 도구가 아니라, 각 파일의 정체성과 관계, 실행 조건, 사람의 판단을 보존하는 개인용 실험 관리 시스템이다.

## 제품 목표

### 데이터셋 관리

- 원본 이미지를 변경하지 않고 수집 출처와 해시를 등록한다.
- 정확 중복은 SHA-256, 유사 중복은 perceptual hash 기반 후보로 제시한다.
- WD 계열 태거와 JoyCaption 계열 VLM의 실행 설정 및 원문 출력을 보존한다.
- 자동 캡션, 사람 편집본, 승인 상태를 서로 다른 revision으로 남긴다.
- 승인된 특정 asset revision과 caption revision만으로 불변 스냅샷을 봉인한다.
- 스냅샷은 canonical manifest와 digest로 재현 가능해야 한다.

### LoRA 학습 관리

- 홈서버에서 학습 작업을 정의하고 DGX Spark Agent가 lease 방식으로 가져간다.
- Anima base model, 데이터셋 스냅샷, 설정, seed, 엔진 source revision과 실행 환경을 고정한다.
- 로그, 지표, 체크포인트, 최종 LoRA와 변환 결과의 provenance를 연결한다.
- 학습 엔진 고유 옵션은 보존하되 공통 실행 수명주기로 정규화한다.
- 첫 어댑터 후보는 `sorryhyun/anima_lora`, 두 번째 후보는 Anima 지원 `sd-scripts`이다.

### ComfyUI 결과 관리

- 생성 이미지에서 prompt와 workflow 메타데이터를 읽고 원본 JSON을 보존한다.
- base model, LoRA, checkpoint, strength, seed, sampler, scheduler, steps, CFG, 해상도를 가능한 범위에서 정규화한다.
- 같은 평가 세트에서 학습 실행 및 체크포인트별 결과를 비교한다.
- 정성 평가와 메모를 남기고, 생성 결과를 데이터셋 후보로 되돌릴 수 있다.

## 사용자와 운영 가정

- 단일 사용자 개인 시스템이다.
- Web/API/Worker는 홈서버에, 실행 Agent는 DGX Spark에 독립 배포한다.
- NAS는 두 실행 영역에서 접근 가능하되 mount path는 서로 다를 수 있다.
- 서비스 간 네트워크는 신뢰 가능한 사설망 또는 VPN 안에 있고, Agent는 API로 outbound 연결할 수 있다.
- 학습과 모델 다운로드는 장시간 실행되며 재시도와 부분 실패가 정상 상황이다.

## 첫 번째 제품 범위

- 한 명의 사용자와 하나 이상의 실행 Agent
- 로컬 파일 또는 감시 폴더 기반 이미지 ingest
- SHA-256 정확 중복과 한 종류 이상의 perceptual hash 유사 중복
- WD, JoyCaption 어댑터와 수동 캡션 편집
- 데이터셋 snapshot seal/export
- 하나의 검증된 Anima 학습 어댑터와 두 번째 어댑터용 contract
- ComfyUI PNG 및 별도 workflow JSON ingest
- 체크포인트 비교 세트와 수동 평가

## 의도적으로 제외하는 범위

- 모델 학습 알고리즘 자체의 재구현
- ComfyUI를 대체하는 생성 UI 또는 범용 workflow 편집기
- 공개 SaaS, 다중 사용자 조직, 결제, 공개 갤러리
- 자동 저작권 판정, 자동 NSFW 차단 또는 법률 자문
- 사람 승인 없는 완전 자동 재학습 루프
- Git LFS를 포함한 Git 기반 대용량 artifact 보관
- NAS 백업 제품 자체의 구현
- Kubernetes 또는 분산 GPU 스케줄러
- `qortlr100/homeserver`에 들어갈 프로덕션 배포 manifest
- 모델 레지스트리 공개 배포와 외부 공유

## 성공 기준

다음 질문에 UI 또는 export된 manifest만으로 답할 수 있어야 한다.

1. 이 LoRA는 어떤 원본 이미지와 어떤 캡션 revision으로 학습했는가?
2. 당시 base model, engine commit, dependency lock, 설정, seed는 무엇인가?
3. 특정 checkpoint 결과는 어떤 ComfyUI workflow와 생성 설정에서 만들어졌는가?
4. 비교 이미지 간에 의도적으로 달라진 변수는 무엇인가?
5. 생성 결과가 후속 데이터셋에 들어갔다면 누가 어떤 이유로 승인했는가?

## 법적·안전 경계

- 수집 출처, 사용 조건, 모델 라이선스와 제한을 metadata로 기록할 수 있어야 한다.
- 시스템이 라이선스 적합성을 보증하지는 않으며, 사용자가 실행 전 확인한다.
- Anima와 파생 LoRA의 비상업 조건은 실행 manifest에 base model license reference로 남긴다.
- 외부 이미지와 비밀 토큰은 기본적으로 외부 API에 전송하지 않는다. 원격 caption provider를 추가할 경우 명시적 opt-in과 감사 기록이 필요하다.
