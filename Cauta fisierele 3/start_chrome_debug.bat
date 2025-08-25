@echo off
REM Start Chrome Debug Mode pentru Internet Archive Duplicate Checker
REM Acest fișier pornește Chrome cu remote debugging activat

echo ========================================
echo Starting Chrome in Debug Mode...
echo ========================================

REM Setează calea către Chrome
set CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"

REM Setează profilul utilizatorului
set PROFILE_DIR="C:/Users/necul/AppData/Local/Google/Chrome/User Data/Default"

REM Verifică dacă Chrome există la calea specificată
if not exist %CHROME_PATH% (
    echo ERROR: Chrome nu a fost găsit la: %CHROME_PATH%
    echo Verifică și actualizează calea în acest fișier batch!
    pause
    exit /b 1
)

echo Chrome Path: %CHROME_PATH%
echo Profile Dir: %PROFILE_DIR%
echo.
echo NOTĂ: Închide toate ferestrele Chrome înainte de a continua!
echo.
pause

REM Pornește Chrome cu remote debugging pe portul 9222
echo Starting Chrome with remote debugging on port 9222...
%CHROME_PATH% --remote-debugging-port=9222 --user-data-dir=%PROFILE_DIR%

echo.
echo Chrome a fost pornit în modul debug!
echo Acum poți rula scriptul Python.
pause