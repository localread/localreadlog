## 화면 예시


### 현재 목록

<img src="docs/screenshots/current-list.png" width="900" alt="현재 목록 화면">

현재 기록된 작품을 확인하고, 열기 / 화수선택 / 분류 / 제목수정 / 삭제를 할 수 있습니다.

### 삭제 목록

<img src="docs/screenshots/deleted-list.png" width="900" alt="삭제 목록 화면">

삭제한 항목을 확인하고, 복구하거나 완전삭제할 수 있습니다.

### 설정 - 사이트 관리

<img src="docs/screenshots/settings-sites.png" width="900" alt="사이트 관리 화면">

사이트 ON/OFF, 사이트명 수정, 기본 분류 변경, 사이트 우선순위 조정이 가능합니다.

### 설정 - 분류 관리

<img src="docs/screenshots/settings-categories.png" width="900" alt="분류 관리 화면">

웹툰 / 만화 / 망가 / 소설 / 애니 / 기타 같은 분류를 추가하거나 이름을 수정할 수 있습니다.

### 관리 화면

<img src="docs/screenshots/manage.png" width="900" alt="관리 화면">

백업, 내보내기, 정리 같은 관리 기능을 사용할 수 있습니다.

### 모바일 화면

<img src="docs/screenshots/mobile-view.png" width="420" alt="모바일 화면">

같은 네트워크에서 모바일 브라우저로 접속해 목록을 확인할 수 있습니다.



# LocalReadLog

Windows 로컬에서 브라우저 방문기록을 읽어 웹툰/만화/소설/애니 최신 화수를 관리하는 도구입니다.

현재 버전: **v0.1.21**

## 1. 먼저 압축 풀기

ZIP 안에서 바로 실행하지 마세요.

권장 위치:

```text
C:\LocalReadLog
```

압축을 완전히 푼 뒤 아래 실행 파일을 사용하세요.

## 2. Python 확인

PowerShell에서 확인합니다.

```powershell
python --version
```

`Python 3.x.x`가 나오면 바로 실행하면 됩니다.

안 나오면 설치합니다.

```powershell
winget install -e --id Python.Python.3.12
```

설치 후 PowerShell을 닫고 다시 열어 `python --version`을 다시 확인하세요.

## 3. 실행 파일

| 할 일                   | 실행 파일                                          |
| --------------------- | ---------------------------------------------- |
| 백그라운드 실행              | `01_Start_Background.vbs`                      |
| 오류 확인용 실행             | `02_Run_With_Window_For_Error_Check.bat`       |
| Windows 시작 시 자동 실행 등록 | `03_Enable_Start_With_Windows.bat`             |
| Windows 시작 시 자동 실행 해제 | `04_Disable_Start_With_Windows.bat`            |
| 서버 종료                 | `05_Stop_Server.bat`                           |
| 모바일 접속 방화벽 허용         | `06_Allow_Mobile_Access_Windows_Firewall.bat`  |
| 모바일 접속 방화벽 허용 규칙 제거   | `07_Remove_Mobile_Access_Windows_Firewall.bat` |

서버가 자동으로 열리지 않거나 오류가 발생하면
`02_Run_With_Window_For_Error_Check.bat`를 실행해서 오류 내용을 확인하세요.


## 4. 접속 주소

PC에서 열기:

```text
http://127.0.0.1:8787
```

8787이 안 열리면 아래 주소도 확인하세요.

```text
http://127.0.0.1:8877
http://127.0.0.1:18787
http://127.0.0.1:28787
```

모바일에서 보려면 PC와 휴대폰이 같은 Wi-Fi에 있어야 합니다. 서버 화면의 `설정` 탭에 표시되는 **모바일 추천 주소**를 휴대폰 브라우저에서 열면 됩니다.

모바일 접속이 안 되면 `06_Allow_Mobile_Access_Windows_Firewall.bat`을 관리자 권한으로 실행하세요.

## 5. 주요 기능

- Whale / Edge / Chrome / Firefox 방문기록 스캔
- 작품별 최신 화수 관리
- 화수/장/회/챕터 번호가 없는 방문기록은 최신 화수로 기록하지 않음
- 웹툰 / 만화 / 망가 / 소설 / 애니 / 기타 분류
- 사이트 ON/OFF 및 우선순위 설정
- 브라우저 ON/OFF 설정
- 모바일 접속 지원
- 접속 비밀번호 ON/OFF
- 자동 업데이트
- DB 백업 / 복원 / 가져오기 / 내보내기
- CSV / HTML 내보내기
- 백그라운드 실행 및 Windows 시작 시 자동 실행

## 6. 데이터 저장 위치

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

## 7. 보안 주의

LocalReadLog는 개인 PC와 로컬 네트워크용 도구입니다.

공유기 포트포워딩으로 외부 인터넷에 공개하지 마세요. 방문기록과 개인 DB가 노출될 수 있습니다.

모바일이나 다른 기기에서 접속할 때는 접속 비밀번호 사용을 권장합니다.

개인 데이터는 `data` 폴더에 저장됩니다. `.gitignore`에 포함되어 있으므로 저장소에는 소스 파일만 올리면 됩니다.

## 8. 삭제 방법

1. `05_Stop_Server.bat` 실행
2. `04_Disable_Start_With_Windows.bat` 실행
3. LocalReadLog 폴더 삭제
