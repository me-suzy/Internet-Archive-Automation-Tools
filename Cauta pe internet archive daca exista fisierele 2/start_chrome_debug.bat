@echo off
REM =======================================================
REM Start Chrome Debug Mode pentru Internet Archive Duplicate Checker
REM =======================================================

echo ========================================
echo Starting Chrome in Debug Mode...
echo ========================================

REM Setez calea către executabilul Chrome
set "CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe"

REM Setez directorul de profil Chrome
set "PROFILE_DIR=C:\Users\%USERNAME%\AppData\Local\Google\Chrome\User Data\Default"

REM Verific dacă Chrome există la calea specificată
if not exist "%CHROME_PATH%" (
    echo ❌ Chrome nu a fost găsit la calea: %CHROME_PATH%
    echo Asigură-te că ai instalat Chrome sau modifică variabila CHROME_PATH.
    pause
    exit /B 1
)

echo Chrome Path: %CHROME_PATH%
echo Profile Dir: %PROFILE_DIR%
echo.
echo ATENȚIE: Închide toate ferestrele Chrome înainte de a continua!
echo.
pause

echo Pornesc Chrome cu remote debugging pe portul 9222...
start "" "%CHROME_PATH%" --remote-debugging-port=9222 --user-data-dir="%PROFILE_DIR%"
echo.
echo ✅ Chrome a fost pornit în modul debug!
echo Acum poți rula scriptul Python.
pause
