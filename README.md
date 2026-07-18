# 주요 상승 종목 시계열 대시보드

AWAKEPLUS의 오늘의 주도주 TOP15, 국내 신고가 핵심, 국내 신고가 전체 데이터를 누적해 시장 주도 테마와 반복 등장 종목을 관찰하는 대시보드입니다.

## 매일 자동 업데이트 구조

- 실행 시간: 한국시간 평일 16:20
- 수집 대상: `todaytop15`, `board/sin`, `board/allnewhigh`
- 저장 위치: `awakeplus/data/*.csv`
- 화면 파일: `dashboard/dashboard.html`

GitHub Actions가 실행되면 새 데이터를 수집하고, 중복을 제거한 뒤 대시보드 파일을 자동 갱신해 다시 저장소에 반영합니다.

## 로그인 데이터가 필요한 경우

AWAKEPLUS가 로그인 세션을 요구하면 GitHub 저장소의 Secrets에 `AWAKEPLUS_COOKIE`를 추가해야 합니다.

## 수동 실행

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_awakeplus_update.ps1
```
