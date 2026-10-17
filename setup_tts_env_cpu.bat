@echo off
chcp 65001 >nul
echo =======================================================================
echo   THIẾT LẬP MÔI TRƯỜNG PYTHON RIÊNG CHO VIENEU-TTS (CHẾ ĐỘ CPU / ONNX)
echo =======================================================================
echo.
echo Lưu ý: VieNeu-TTS tối ưu nhất trên Python 3.10 - 3.12 (có sẵn wheel trên Windows).
echo Kịch bản này sẽ tạo môi trường ảo "venv_tts" độc lập trong thư mục dự án
echo để tránh xung đột thư viện với ứng dụng chính hoặc bản EXE đóng gói.
echo.

set PYTHON_CMD=
where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    for %%v in (3.11 3.12 3.10) do (
        py -%%v --version >nul 2>&1
        if %ERRORLEVEL% equ 0 (
            set PYTHON_CMD=py -%%v
            echo [✓] Đã tìm thấy Python %%v qua trình khởi chạy py.
            goto :found_python
        )
    )
)

where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set PYTHON_CMD=python
    echo [!] Dùng python mặc định trên hệ thống.
    goto :found_python
)

echo [X] Không tìm thấy Python 3.10 - 3.12 trên máy!
echo Vui lòng cài đặt Python 3.11 từ python.org trước khi chạy kịch bản này.
pause
exit /b 1

:found_python
echo [*] Đang khởi tạo môi trường venv_tts...
%PYTHON_CMD% -m venv venv_tts
if %ERRORLEVEL% neq 0 (
    echo [X] Lỗi khi tạo môi trường venv_tts.
    pause
    exit /b 1
)

echo [*] Nâng cấp pip và cài đặt vieneu (v3.8.3) cho CPU...
call venv_tts\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install "vieneu==3.8.3" onnxruntime soundfile

echo.
echo [*] Kiểm tra môi trường TTS vừa tạo:
python core\tts_runner.py --check-env

echo.
echo =======================================================================
echo   HOÀN TẤT THIẾT LẬP MÔI TRƯỜNG TTS (CPU)!
echo   Đường dẫn Python: %~dp0venv_tts\Scripts\python.exe
echo   Ứng dụng Truyenaudio sẽ tự động nhận diện môi trường này khi mở Tab Audio.
echo =======================================================================
pause
