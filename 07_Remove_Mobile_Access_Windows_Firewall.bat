@echo off
setlocal
netsh advfirewall firewall delete rule name="LocalReadLog 8787" >nul
netsh advfirewall firewall delete rule name="LocalReadLog 8877" >nul
netsh advfirewall firewall delete rule name="LocalReadLog 18787" >nul
netsh advfirewall firewall delete rule name="LocalReadLog 28787" >nul
echo LocalReadLog 모바일 접속 방화벽 허용 규칙 제거 완료
pause
