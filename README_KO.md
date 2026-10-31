<div align="center">

<img src="viewatlas_assets/viewatlas_mark.png" alt="ViewAtlas 로고" width="190" />

# ViewAtlas
**Substance 3D Painter용 무료 카메라 북마크 및 스크린샷 플러그인**

[English](README.md) · [한국어](README_KO.md) · [Gumroad 무료 다운로드](https://9870424699986.gumroad.com/l/vbncosi)

</div>

ViewAtlas는 Adobe Substance 3D Painter에서 카메라 시점을 저장하고 여러 각도의 스크린샷을 촬영할 수 있게 도와주는 무료 Python 플러그인입니다. 시리얼 번호나 온라인 인증이 필요하지 않습니다.

## 주요 기능

- 최대 **10개의 카메라 북마크** 저장 및 복원
- 저장한 시점의 썸네일 미리보기
- 지정한 3D 뷰포트 영역 스크린샷 촬영
- 여러 카메라 시점을 자동 촬영하고 이미지 레이아웃으로 합치기
- 파일명, 출력 폴더, 지원되는 이미지 형식 지정
- 북마크 JSON 내보내기·가져오기
- 다국어 UI 및 간결한 탭 구성
- 전체·시점별 뷰포트 표시 옵션 (자동 채널 전환은 실험적 기능)

## 실제 사용 화면

[Gumroad에서 실제 ViewAtlas 작업 화면과 촬영 결과 보기](https://9870424699986.gumroad.com/l/vbncosi)

## 설치 방법 (Windows)

1. GitHub의 **Code → Download ZIP** 또는 [Gumroad](https://9870424699986.gumroad.com/l/vbncosi)에서 파일을 받습니다.
2. `viewatlas_v15.py` 파일과 `viewatlas_assets` 폴더를 아래 Python 플러그인 디렉터리에 함께 복사합니다.

   ```text
   C:\Users\<사용자이름>\Documents\Adobe\Adobe Substance 3D Painter\python\plugins
   ```

3. `.py` 파일과 `viewatlas_assets` 폴더가 같은 위치에 있어야 합니다.
4. Substance 3D Painter를 재시작하고 **Window** 메뉴에서 ViewAtlas를 실행합니다. Painter 버전에 따라 메뉴 위치는 달라질 수 있습니다.

> 기존 ViewAtlas `.py` 파일이 있으면 플러그인 폴더 밖으로 옮겨 중복 실행을 막으세요. 기존 북마크는 프로젝트에 저장되지만, 버전 변경 전에 프로젝트 백업을 권장합니다.

## 호환성 및 참고 사항

- **Painter 9.0:** 필요한 카메라 API가 없어 카메라 북마크 미지원
- **Painter 9.1~10.0:** PySide2/Qt5 대응 코드는 있으나 해당 버전에서 실제 실행 미검증
- **Painter 10.1~12.x:** PySide6/Qt6 대응 코드는 있으나 모든 버전에서 실사용 검증 완료 상태는 아님
- **채널 자동 변경은 실험적 기능**이며 버전과 단축키 등에 따라 다르게 동작할 수 있습니다.
- 촬영 해상도는 **현재 뷰포트 화면 해상도**이며, 고해상도 Iray 렌더 자동화는 지원하지 않습니다.
- 이미지 저장 형식은 Qt 이미지 플러그인 환경에 따라 달라질 수 있습니다.

## 다운로드 및 문의

**[Gumroad에서 무료 다운로드](https://9870424699986.gumroad.com/l/vbncosi)**

오류가 발생하면 GitHub Issues에 사용한 Painter 버전, 문제 발생 순서, 오류 내용을 남겨주세요. 스크린샷의 계정·로컬 경로는 가려주세요.

ViewAtlas는 Adobe의 공식 제품이 아닌 독립 서드파티 플러그인입니다.

**무료 다운로드 및 사용이 가능합니다.** 소스 코드의 수정·재배포에 대한 별도 라이선스는 지정되지 않았습니다.