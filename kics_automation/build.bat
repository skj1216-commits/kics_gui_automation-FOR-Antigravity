@echo off
echo ===========================================
echo KICS Automation Build Script
echo ===========================================

echo 1. Installing Requirements...
pip install -r requirements.txt
playwright install chromium

echo.
echo 2. Building Executable...
REM PyInstaller를 사용하여 하나의 실행 파일로 빌드
REM Playwright 바이너리 포함 처리는 복잡하므로, 가장 좋은 방법은
REM 인터넷이 연결된 PC에서 폴더(dist\main) 전체를 복사해서 폐쇄망에 가져가는 것입니다.
pyinstaller --noconfirm --onedir --windowed --add-data "config.json;." "main.py"

echo.
echo Build Complete.
echo 'dist\main' 폴더를 폐쇄망 PC로 복사하세요.
pause
