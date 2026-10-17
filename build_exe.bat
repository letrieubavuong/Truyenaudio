@echo off
chcp 65001 >nul
echo ===================================================
echo     DỰ ÁN TRUYỆNAUDIO - ĐÓNG GÓI TỆP THỰC THI (.EXE)
echo ===================================================
echo.

tasklist /fi "imagename eq TruyenAudio.exe" 2>nul | findstr /i "TruyenAudio.exe" >nul
if %ERRORLEVEL% EQU 0 (
    echo [!] CẢNH BÁO: 'TruyenAudio.exe' đang được mở!
    echo     Vui lòng đóng ứng dụng trước khi đóng gói lại để tránh lỗi quyền ghi đè file.
    echo.
    set /p "CHOICE=Bạn có muốn tự động tắt TruyenAudio.exe để tiếp tục không? (Y/N): "
    if /i "%CHOICE%"=="Y" (
        taskkill /f /im TruyenAudio.exe >nul 2>&1
        timeout /t 1 /nobreak >nul
    ) else (
        echo [X] Đã hủy quá trình đóng gói.
        pause
        exit /b 1
    )
)

if not exist ".venv\Scripts\pyinstaller.exe" (
    echo [*] Đang tạo môi trường ảo và cài đặt thư viện cần thiết...
    python -m venv .venv
    .venv\Scripts\pip install -r requirements.txt pyinstaller
)

echo [*] Đang biên dịch ứng dụng với PyInstaller...
.venv\Scripts\pyinstaller --clean -y TruyenAudio.spec

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ===================================================
    echo [✓] ĐÓNG GÓI THÀNH CÔNG!
    echo Tệp thực thi nằm tại: dist\TruyenAudio.exe
    echo ===================================================
) else (
    echo.
    echo [!] Quá trình đóng gói gặp lỗi. Vui lòng kiểm tra thông báo phía trên.
)
pause
