## 무엇을 바꿨나요

<!-- 무엇을, 왜 바꿨는지 적어주세요. 배경을 알면 리뷰가 빨라집니다. -->

## 어떻게 확인했나요

<!-- 실제로 돌려본 것을 적어주세요. 어느 플랫폼에서 테스트했는지도 알려주시면 좋습니다. -->

## 검증

- [ ] `python -m pytest -c backend/pytest.ini backend/tests` — 기준선 `194 passed, 29 skipped` 유지
- [ ] `npx tsc --noEmit -p tsconfig.json` 통과
- [ ] `npm run build` 통과

## 확인

- [ ] API 계약(엔드포인트·필드명·페이로드 구조)을 바꾸지 않았습니다. <!-- 배포된 구버전 exe가 같은 API를 호출합니다. 필드 추가는 괜찮습니다. -->
- [ ] 건드린 파일의 줄바꿈 방식을 유지했습니다. <!-- 저장소 대부분이 CRLF입니다. -->
- [ ] UI를 바꿨다면 원시 색 대신 `index.css`의 `@theme` 토큰을 썼습니다.

자세한 규칙은 [CONTRIBUTING.md](../CONTRIBUTING.md)에 있습니다.
