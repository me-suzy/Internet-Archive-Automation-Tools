@echo off
REM Pornește Chrome pe profilul Default cu remote debugging activat
set CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"
set PROFILE_DIR="C:/Users/necul/AppData/Local/Google/Chrome/User Data/Default"

REM Asigură-te că nu mai e deja un Chrome deschis pe acel profil
%CHROME_PATH% --remote-debugging-port=9222 --user-data-dir=%PROFILE_DIR%
