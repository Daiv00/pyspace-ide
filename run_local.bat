@echo off
REM Локальный запуск PySpace IDE (Windows).
setlocal
cd /d "%~dp0"

if not exist .venv (
  echo Создаём виртуальное окружение .venv
  python -m venv .venv
)

call .venv\Scripts\activate.bat

echo Устанавливаем зависимости
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

set PYSPACE_ENV=development
if "%PYSPACE_SECRET%"=="" set PYSPACE_SECRET=dev-secret-not-for-production
if "%PYSPACE_ADMIN_USER%"=="" set PYSPACE_ADMIN_USER=admin
if "%PYSPACE_ADMIN_PASSWORD%"=="" set PYSPACE_ADMIN_PASSWORD=admin12345
if "%PORT%"=="" set PORT=8080

echo.
echo   PySpace IDE  ^-^>  http://127.0.0.1:%PORT%
echo   Логин: %PYSPACE_ADMIN_USER%   Пароль: %PYSPACE_ADMIN_PASSWORD%
echo   Внимание: настоящий терминал (PTY) на Windows недоступен, всё остальное работает.
echo.

python -m flask --app wsgi:app run --host 0.0.0.0 --port %PORT% --reload
endlocal
