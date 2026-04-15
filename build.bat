@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

echo ============================================
echo   Fool Code - Single EXE build (onefile)
echo ============================================
echo.

:: Check uv
where uv >nul 2>&1
if errorlevel 1 (
    echo [ERROR] uv not found. Install: https://docs.astral.sh/uv/
    goto :fail
)

:: Check frontend
if not exist "desktop-ui\dist\index.html" (
    echo [INFO] Frontend not built, building now...
    where npm >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] npm not found. Install Node.js first.
        goto :fail
    )
    cd desktop-ui
    call npm install
    call npm run build
    cd ..
    if not exist "desktop-ui\dist\index.html" (
        echo [ERROR] Frontend build failed.
        goto :fail
    )
    echo [OK] Frontend built.
) else (
    echo [OK] Frontend dist found.
)

:: Install deps
echo.
echo [INFO] Installing Python dependencies...
uv sync --inexact --extra build --extra desktop
if errorlevel 1 (
    echo [ERROR] uv sync failed.
    goto :fail
)
echo [OK] Dependencies installed.

:: Build Rust native module (fool_code_cu)
set "CU_COLLECT="

echo.
echo [INFO] Building Rust native module (fool_code_cu)...
where cargo >nul 2>&1
if errorlevel 1 (
    echo [WARN] cargo not found — skipping Rust build. Computer Use will be disabled.
    goto :after_rust
)

uv run pip install maturin >nul 2>&1
uv run maturin develop --release --manifest-path fool_code\computer_use\_native\Cargo.toml
if errorlevel 1 (
    echo [WARN] Rust native build failed — Computer Use will be disabled.
    goto :after_cu
)
echo [OK] fool_code_cu built.

:: Verify the package is importable
uv run python -c "import fool_code_cu; assert hasattr(fool_code_cu, 'screenshot'), 'missing screenshot'" >nul 2>&1
if errorlevel 1 (
    echo [WARN] fool_code_cu installed but not importable — Computer Use disabled.
) else (
    echo [OK] fool_code_cu verified.
    set "CU_COLLECT=--collect-all fool_code_cu"
)

:after_cu

:: Build Rust native module (magma_memory)
set "MM_COLLECT="

echo.
echo [INFO] Building Rust native module (magma_memory)...
uv run maturin develop --release --manifest-path fool_code\magma\_native\Cargo.toml
if errorlevel 1 (
    echo [WARN] magma_memory build failed — MAGMA episodic memory will be disabled.
    goto :after_rust
)
echo [OK] magma_memory built.

:: Verify the package is importable
uv run python -c "import magma_memory; assert hasattr(magma_memory, 'MagmaStore'), 'missing MagmaStore'" >nul 2>&1
if errorlevel 1 (
    echo [WARN] magma_memory installed but not importable — MAGMA disabled.
) else (
    echo [OK] magma_memory verified.
    set "MM_COLLECT=--collect-all magma_memory"
)

:after_rust

:: Clean old build
echo.
echo [INFO] Cleaning old build...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"
if exist "FoolCode.spec" del /q "FoolCode.spec"
if exist "%PROJECT_DIR%FoolCode.exe" del /q "%PROJECT_DIR%FoolCode.exe"
echo [OK] Cleaned.

:: Run PyInstaller
echo.
echo [INFO] Building single FoolCode.exe ...
uv run pyinstaller --name FoolCode --onefile --noconsole --icon "desktop-ui/柴犬.ico" ^
    --add-data "desktop-ui/dist;desktop-ui/dist" ^
    !CU_COLLECT! ^
    !MM_COLLECT! ^
    --hidden-import uvicorn.logging ^
    --hidden-import uvicorn.protocols.http ^
    --hidden-import uvicorn.protocols.http.auto ^
    --hidden-import uvicorn.protocols.http.h11_impl ^
    --hidden-import uvicorn.protocols.http.httptools_impl ^
    --hidden-import uvicorn.protocols.websockets ^
    --hidden-import uvicorn.protocols.websockets.auto ^
    --hidden-import uvicorn.protocols.websockets.wsproto_impl ^
    --hidden-import uvicorn.protocols.websockets.websockets_impl ^
    --hidden-import uvicorn.lifespan ^
    --hidden-import uvicorn.lifespan.on ^
    --hidden-import uvicorn.lifespan.off ^
    --hidden-import httptools ^
    --hidden-import webview ^
    --hidden-import websockets ^
    --hidden-import websockets.asyncio.server ^
    --hidden-import yaml ^
    --hidden-import fool_code.internal_mcp ^
    --hidden-import fool_code.internal_mcp.browser_mcp ^
    --hidden-import fool_code.internal_mcp.browser_mcp.__main__ ^
    --hidden-import PIL ^
    --hidden-import PIL.Image ^
    --collect-all webview ^
    --collect-all PIL ^
    run.py
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed.
    goto :fail
)
echo [OK] Build succeeded.

:: Copy exe to project root
echo.
echo [INFO] Copying FoolCode.exe to project root...
copy /y "dist\FoolCode.exe" "%PROJECT_DIR%FoolCode.exe"
if errorlevel 1 (
    echo [ERROR] Copy failed.
    goto :fail
)

echo.
echo ============================================
echo   Done. Output:
echo   %PROJECT_DIR%FoolCode.exe
echo ============================================
echo.
pause
exit /b 0

:fail
echo.
echo [BUILD FAILED]
echo.
pause
exit /b 1
