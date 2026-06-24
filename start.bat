@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d %~dp0

echo Emergency Contact System starting...
echo.

if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
) else (
    echo venv が見つかりません。先に python -m venv venv と pip install -r requirements.txt を実行してください。
    pause
    exit /b 1
)

if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        set "ENV_KEY=%%A"
        set "ENV_VALUE=%%B"
        if not "!ENV_KEY!"=="" if not "!ENV_KEY:~0,1!"=="#" set "!ENV_KEY!=!ENV_VALUE!"
    )
)

if "%PUBLIC_URL_MODE%"=="" set "PUBLIC_URL_MODE=dynamic"
if "%CLOUDFLARED_TUNNEL_NAME%"=="" set "CLOUDFLARED_TUNNEL_NAME=emergency"

echo Mode: %PUBLIC_URL_MODE%

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo 既存の8000番ポート利用プロセスを停止します: %%P
    taskkill /PID %%P /F >nul 2>&1
)

taskkill /IM cloudflared.exe /F >nul 2>&1

start "Emergency Contact System FastAPI" cmd /k "call venv\Scripts\activate.bat && uvicorn main:app --host 0.0.0.0 --port 8000 --reload"
echo FastAPI起動完了

timeout /t 3 /nobreak >nul

where cloudflared >nul 2>&1
if errorlevel 1 (
    echo cloudflared が見つかりません。外部公開とPush通知には cloudflared の導入が必要です。
) else (
    if /I "%PUBLIC_URL_MODE%"=="fixed" (
        echo Cloudflare: Named Tunnel %CLOUDFLARED_TUNNEL_NAME%
        start "Emergency Contact System Cloudflare" cmd /k "cloudflared tunnel run %CLOUDFLARED_TUNNEL_NAME% > cloudflared.log 2>&1"
        echo Cloudflare Named Tunnel起動完了
    ) else (
        set "PUBLIC_URL_MODE=dynamic"
        echo Cloudflare: TryCloudflare temporary URL
        del current_url.txt >nul 2>&1
        del cloudflared.log >nul 2>&1
        start "Emergency Contact System Cloudflare" cmd /k "cloudflared tunnel --url http://localhost:8000 > cloudflared.log 2>&1"
        echo TryCloudflare起動完了
        set "CURRENT_URL="
        for /L %%I in (1,1,30) do (
            if not defined CURRENT_URL (
                for /f "usebackq delims=" %%U in (`powershell -NoProfile -Command "$m = Select-String -Path 'cloudflared.log' -Pattern 'https://[A-Za-z0-9.-]+\.trycloudflare\.com' -AllMatches -ErrorAction SilentlyContinue | ForEach-Object { $_.Matches.Value } | Select-Object -Last 1; if ($m) { $m }"`) do set "CURRENT_URL=%%U"
                if defined CURRENT_URL (
                    echo !CURRENT_URL!>current_url.txt
                    echo Cloudflare URL: !CURRENT_URL!
                ) else (
                    timeout /t 1 /nobreak >nul
                )
            )
        )
        if not defined CURRENT_URL (
            echo Cloudflare URLを自動取得できませんでした。cloudflared.log を確認してください。
        )
    )
)

start http://127.0.0.1:8000

echo.
echo ローカルURL: http://127.0.0.1:8000
echo 終了する場合は、開いたFastAPIとCloudflareの各ターミナルを閉じてください。
echo.
pause
