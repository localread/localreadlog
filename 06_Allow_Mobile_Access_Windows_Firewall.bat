@echo off
setlocal
netsh advfirewall firewall add rule name="LocalReadLog 8787" dir=in action=allow protocol=TCP localport=8787 >nul
netsh advfirewall firewall add rule name="LocalReadLog 8877" dir=in action=allow protocol=TCP localport=8877 >nul
netsh advfirewall firewall add rule name="LocalReadLog 18787" dir=in action=allow protocol=TCP localport=18787 >nul
netsh advfirewall firewall add rule name="LocalReadLog 28787" dir=in action=allow protocol=TCP localport=28787 >nul
echo LocalReadLog 모바일 접속 방화벽 허용 완료
pause
