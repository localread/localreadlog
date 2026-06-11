# LocalReadLog

현재 버전: v0.1.13

현재 버전: **v0.1.11**

Windows 로컬에서 브라우저 방문기록을 읽어 웹툰/만화/소설/애니 최신 화수를 관리하는 도구입니다.

## 먼저 압축 풀기

ZIP 안에서 바로 실행하지 마세요.

1. ZIP 파일을 우클릭합니다.
2. `모두 압축 풀기`를 선택합니다.
3. 예를 들어 아래 위치에 풉니다.

```text
C:\LocalReadLog
```

압축을 푼 뒤 폴더 안의 실행 파일을 더블클릭하세요.

## 가장 먼저 Python 확인

PowerShell을 열고 Python이 있는지 확인합니다.

```powershell
python --version
```

`Python 3.x.x`가 나오면 바로 실행하면 됩니다.

안 나오면 PowerShell에서 설치합니다.

```powershell
winget install -e --id Python.Python.3.12
```

설치 후 PowerShell을 닫고 다시 열어 `python --version`을 다시 확인합니다.

## 뭘 누르면 됨?

처음 실행:

```text
01_Start_Background.vbs
```

문제가 생겨서 오류를 보고 싶을 때:

```text
02_Run_With_Window_For_Error_Check.bat
```

서버 끄기:

```text
05_Stop_Server.bat
```

Windows 시작 시 자동 실행 등록:

```text
03_Enable_Start_With_Windows.bat
```

Windows 시작 시 자동 실행 해제:

```text
04_Disable_Start_With_Windows.bat
```

모바일 접속이 안 될 때 Windows 방화벽 허용:

```text
06_Allow_Mobile_Access_Windows_Firewall.bat
```

방화벽 허용 규칙 제거:

```text
07_Remove_Mobile_Access_Windows_Firewall.bat
```

## 접속 주소

PC에서 보기:

```text
http://127.0.0.1:8787
```

백그라운드 실행은 실제로 열린 포트를 자동 확인한 뒤 브라우저를 엽니다.

안 열리면 아래 주소도 확인하세요.

```text
http://127.0.0.1:8877
http://127.0.0.1:18787
http://127.0.0.1:28787
```

모바일에서 보려면 PC와 휴대폰을 같은 Wi-Fi에 연결한 뒤, 서버의 `설정` 탭에 표시되는 **모바일 추천 주소**를 엽니다.

예시:

```text
http://192.168.0.12:8787
```

설정 탭의 주소는 링크로 열 수 있고, `복사` 버튼으로 복사할 수 있습니다. Hyper-V, WSL, Docker, VMware 같은 가상 어댑터 주소는 `모바일 접속용 아님`으로 따로 표시됩니다.

모바일 접속 체크:

```text
1. PC와 휴대폰이 같은 Wi-Fi인지 확인
2. 설정 탭의 모바일 주소를 휴대폰 브라우저에 입력
3. 안 되면 06_Allow_Mobile_Access_Windows_Firewall.bat 실행
4. 그래도 안 되면 공유기/AP 격리 기능 또는 VPN을 확인
```

모바일이나 다른 기기에서 접속할 때는 접속 비밀번호를 켜는 것을 권장합니다.

모바일에서 접속이 안 되면 Windows 방화벽이 막는 경우가 많습니다. 이때 `06_Allow_Mobile_Access_Windows_Firewall.bat`을 실행해 허용 규칙을 추가하세요. 관리자 권한 확인 창이 뜨면 허용하면 됩니다.

## 서버 화면에서 할 수 있는 것

- 현재 목록 / 삭제 목록 보기
- 작품 열기, 화수 선택, 분류 변경, 제목 수정, 삭제/복구
- 설정에서 사이트 추가, 사이트 ON/OFF, 사이트 우선순위 변경
- 설정에서 브라우저 ON/OFF
- 설정에서 접속 비밀번호 ON/OFF
- 설정에서 자동 업데이트 ON/OFF와 간격 변경
- 관리 탭에서 지금 업데이트
- 관리 탭에서 DB 백업/복원
- 관리 탭에서 DB 파일 가져오기
- 관리 탭에서 DB/CSV/HTML 내보내기
- 관리 탭에서 저장 위치, data 폴더, 백업 폴더, 로그 파일 열기
- 관리 탭에서 처음 실행 진단, 브라우저 기록 위치 확인
- 관리 탭에서 문제 있는 항목 점검 확인
- 로그 탭에서 최근 로그 확인

## 자동 업데이트

서버가 켜져 있으면 자동 업데이트가 동작합니다.
설정 탭에서 30분 / 1시간 / 3시간 / 6시간으로 바꿀 수 있습니다.
바로 갱신하고 싶으면 관리 탭의 `지금 업데이트`를 누르면 됩니다.

## 저장 위치

실행 후 데이터는 `data` 폴더에 저장됩니다.

```text
data/localreadlog_db.json
data/localreadlog_latest.csv
data/localreadlog_latest_mobile.html
data/localreadlog_latest_pc.html
data/localreadlog_manager_log.txt
data/backups/
```

기존 DB를 쓰려면 `data/localreadlog_db.json`으로 넣으면 됩니다.
다른 PC에서 내보낸 DB는 서버의 `관리` 탭에서 `DB 파일 가져오기`로 선택하면 됩니다.
저장 위치와 폴더 열기도 서버의 `관리` 탭에서 할 수 있습니다.

## 삭제 방법

1. `05_Stop_Server.bat` 실행
2. `04_Disable_Start_With_Windows.bat` 실행
3. LocalReadLog 폴더 삭제

## 중요한 보안 주의

LocalReadLog는 개인 PC와 로컬 네트워크용 도구입니다.
공유기 포트포워딩으로 외부 인터넷에 공개하지 마세요.
외부에서 접속 가능하게 열어두면 방문기록과 개인 DB가 노출될 수 있습니다.

## 속도가 느릴 때

설정/관리 화면이 느리면 모바일 주소 조회나 네트워크 어댑터 확인이 오래 걸리는 경우가 있습니다. v0.1.12부터 모바일 주소는 일정 시간 캐시되어 페이지가 매번 느려지지 않도록 개선했습니다.

그래도 느리면 먼저 `05_Stop_Server.bat`으로 종료한 뒤 `01_Start_Background.vbs`로 다시 실행하세요.

## GitHub에 올리면 안 되는 파일

아래 파일은 개인 방문기록이 들어갈 수 있으므로 올리지 마세요.

```text
data/
localreadlog_config.json
*.bak
__pycache__/
*.pyc
*.zip
```

ZIP 파일은 저장소 파일 목록에 올리지 말고 GitHub Releases에 첨부하는 것을 권장합니다.

## 변경 이력

변경 이력은 `CHANGELOG.md`를 확인하세요.


## v0.1.11 참고

일부 Windows 환경에서 모바일 주소를 표시할 때 PowerShell 네트워크 정보 조회 출력 인코딩이 달라 서버 화면이 멈출 수 있던 문제를 수정했습니다.
