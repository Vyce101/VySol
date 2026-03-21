@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "MIN_PYTHON_MINOR=10"
set "MIN_NODE_MAJOR=18"
set "PYTHON_INSTALL_ID=Python.Python.3.11"
set "NODE_INSTALL_ID=OpenJS.NodeJS.LTS"
set "BACKEND_VENV=backend\venv"
set "BACKEND_REQ=backend\requirements.txt"
set "BACKEND_REQ_STAMP=%BACKEND_VENV%\.requirements.sha256"
set "FRONTEND_DEPS_SOURCE=frontend\package-lock.json"
if not exist "%FRONTEND_DEPS_SOURCE%" set "FRONTEND_DEPS_SOURCE=frontend\package.json"
set "FRONTEND_DEPS_STAMP=frontend\node_modules\.deps.sha256"
set "BACKEND_VENV_CREATED=0"
set "BACKEND_VENV_REBUILT=0"

echo ============================================
echo    VySol - Setup ^& Launch
echo ============================================
echo.

call :start_step_timer
echo [1/6] Checking Python...
call :ensure_python
if errorlevel 1 goto :fail
echo       Using Python: %PYTHON_EXE%
call :finish_step_timer

call :start_step_timer
echo [2/6] Checking Node.js and npm...
call :ensure_node
if errorlevel 1 goto :fail
echo       Using Node.js: %NODE_EXE%
echo       Using npm: %NPM_EXE%
call :finish_step_timer

call :start_step_timer
echo [3/6] Preparing backend virtual environment...
call :ensure_backend_venv
if errorlevel 1 goto :fail
call :finish_step_timer

call :start_step_timer
echo [4/6] Installing backend dependencies if needed...
call :ensure_backend_deps
if errorlevel 1 goto :fail
call :finish_step_timer

call :start_step_timer
echo [5/6] Installing frontend dependencies if needed...
call :ensure_frontend_deps
if errorlevel 1 goto :fail
call :finish_step_timer

call :start_step_timer
echo [6/6] Launching VySol...
echo.
echo       Backend:  http://localhost:8000
echo       Frontend: http://localhost:3000
echo.
echo       Press Ctrl+C to stop both servers.
echo       If ports 8000 or 3000 are already in use, stop those processes first.
echo ============================================
echo.
if defined VYSOL_SKIP_LAUNCH (
    echo       Status: launch skipped because VYSOL_SKIP_LAUNCH is set.
    call :finish_step_timer
    exit /b 0
)

start "VySol Backend" cmd /k "cd backend && venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

timeout /t 3 /nobreak >nul
start "" "http://localhost:3000"
call :finish_step_timer

cd frontend
call "%NPM_EXE%" run dev
pause
exit /b 0

:ensure_python
set "PYTHON_EXE="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, %MIN_PYTHON_MINOR%) else 1)" >nul 2>nul
if not errorlevel 1 (
    for /f "usebackq delims=" %%I in (`py -3 -c "import sys; print(sys.executable)"`) do set "PYTHON_EXE=%%I"
)
if not defined PYTHON_EXE (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, %MIN_PYTHON_MINOR%) else 1)" >nul 2>nul
    if not errorlevel 1 (
        for /f "usebackq delims=" %%I in (`python -c "import sys; print(sys.executable)"`) do set "PYTHON_EXE=%%I"
    )
)
if defined PYTHON_EXE exit /b 0

call :require_winget || exit /b 1
echo       Status: supported Python not found, installing via winget...
winget install --id %PYTHON_INSTALL_ID% -e --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo ERROR: Failed to install Python automatically. Install Python 3.%MIN_PYTHON_MINOR% or newer and re-run this script.
    exit /b 1
)
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, %MIN_PYTHON_MINOR%) else 1)" >nul 2>nul
if not errorlevel 1 (
    for /f "usebackq delims=" %%I in (`py -3 -c "import sys; print(sys.executable)"`) do set "PYTHON_EXE=%%I"
)
if not defined PYTHON_EXE (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, %MIN_PYTHON_MINOR%) else 1)" >nul 2>nul
    if not errorlevel 1 (
        for /f "usebackq delims=" %%I in (`python -c "import sys; print(sys.executable)"`) do set "PYTHON_EXE=%%I"
    )
)
if defined PYTHON_EXE exit /b 0
echo ERROR: Python installation finished, but no supported Python was detected in this session.
exit /b 1

:ensure_node
call :detect_node_tools
if not errorlevel 1 exit /b 0

call :require_winget || exit /b 1
echo       Status: supported Node.js not found, installing via winget...
winget install --id %NODE_INSTALL_ID% -e --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo ERROR: Failed to install Node.js automatically. Install Node.js %MIN_NODE_MAJOR% or newer and re-run this script.
    exit /b 1
)
call :detect_node_tools
if not errorlevel 1 exit /b 0

echo       Status: refreshing environment and retrying Node.js detection...
call :refresh_path_for_current_session
call :detect_node_tools
if not errorlevel 1 exit /b 0

echo ERROR: Node.js installation finished, but no supported Node.js/npm was detected in this session.
exit /b 1

:detect_node_tools
set "NODE_EXE="
set "NPM_EXE="
node -e "const major = parseInt(process.versions.node.split('.')[0], 10); process.exit(major >= %MIN_NODE_MAJOR% ? 0 : 1)" >nul 2>nul
if not errorlevel 1 (
    for /f "usebackq delims=" %%I in (`where node 2^>nul`) do (
        set "NODE_EXE=%%I"
        goto :node_path_found
    )
)
:node_path_found
for /f "usebackq delims=" %%I in (`where npm.cmd 2^>nul`) do (
    set "NPM_EXE=%%I"
    goto :npm_path_found
)
:npm_path_found
if defined NODE_EXE if defined NPM_EXE exit /b 0
exit /b 1

:refresh_path_for_current_session
set "MACHINE_PATH="
set "USER_PATH="
where refreshenv >nul 2>nul
if not errorlevel 1 (
    call refreshenv >nul 2>nul
)
for /f "tokens=2,*" %%A in ('reg query "HKLM\System\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul ^| findstr /R /I "Path"') do set "MACHINE_PATH=%%B"
for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul ^| findstr /R /I "Path"') do set "USER_PATH=%%B"
if defined USER_PATH if defined MACHINE_PATH (
    set "PATH=!USER_PATH!;!MACHINE_PATH!;%PATH%"
    exit /b 0
)
if defined USER_PATH (
    set "PATH=!USER_PATH!;%PATH%"
    exit /b 0
)
if defined MACHINE_PATH (
    set "PATH=!MACHINE_PATH!;%PATH%"
)
exit /b 0

:ensure_backend_venv
set "TARGET_VENV_MM="
set "CURRENT_VENV_MM="
set "BACKEND_VENV_CREATED=0"
set "BACKEND_VENV_REBUILT=0"
call :get_python_minor_version "%PYTHON_EXE%" TARGET_VENV_MM
if not defined TARGET_VENV_MM (
    echo ERROR: Failed to detect the selected Python version.
    exit /b 1
)

if exist "%BACKEND_VENV%\Scripts\python.exe" (
    call :get_python_minor_version "%BACKEND_VENV%\Scripts\python.exe" CURRENT_VENV_MM
    if not defined CURRENT_VENV_MM (
        if not exist "%BACKEND_VENV%\pyvenv.cfg" (
            echo       Status: backend venv is missing pyvenv.cfg, attempting repair...
            call :repair_backend_pyvenv_cfg "%BACKEND_VENV%\pyvenv.cfg" "%PYTHON_EXE%" "!TARGET_VENV_MM!"
            call :get_python_minor_version "%BACKEND_VENV%\Scripts\python.exe" CURRENT_VENV_MM
        )
        if defined CURRENT_VENV_MM if /I "!CURRENT_VENV_MM!"=="!TARGET_VENV_MM!" (
            echo       Status: repaired backend venv metadata, skipping rebuild.
            exit /b 0
        )
        echo       Status: backend venv is unusable, rebuilding...
        set "BACKEND_VENV_REBUILT=1"
    ) else if /I not "!CURRENT_VENV_MM!"=="!TARGET_VENV_MM!" (
        echo       Status: rebuilding backend venv for Python !TARGET_VENV_MM! ^(found !CURRENT_VENV_MM!^)...
        set "BACKEND_VENV_REBUILT=1"
    ) else (
        echo       Status: skipping rebuild, existing backend venv matches Python !TARGET_VENV_MM!.
        exit /b 0
    )
) else (
    if exist "%BACKEND_VENV%" (
        echo       Status: backend venv is incomplete, recreating...
    ) else (
        echo       Status: creating backend virtual environment...
    )
) 

if "!BACKEND_VENV_REBUILT!"=="1" (
    if "!BACKEND_VENV_REBUILT!"=="1" (
        echo       Status: rebuilding backend virtual environment...
    )
    if exist "%BACKEND_VENV%" (
        "%PYTHON_EXE%" -m venv --clear "%BACKEND_VENV%"
    ) else (
        "%PYTHON_EXE%" -m venv "%BACKEND_VENV%"
    )
    if errorlevel 1 (
        echo ERROR: Failed to rebuild the backend virtual environment.
        exit /b 1
    )
    set "BACKEND_VENV_CREATED=1"
    exit /b 0
)

if not exist "%BACKEND_VENV%\Scripts\python.exe" (
    "%PYTHON_EXE%" -m venv "%BACKEND_VENV%"
    if errorlevel 1 (
        echo ERROR: Failed to create backend virtual environment.
        exit /b 1
    )
    set "BACKEND_VENV_CREATED=1"
    exit /b 0
)

echo       Status: skipping rebuild, existing backend venv is ready.
exit /b 0

:ensure_backend_deps
set "BACKEND_HASH="
set "BACKEND_STORED_HASH="
set "BACKEND_STAMP_STATE=missing"
call :compute_sha256 "%BACKEND_REQ%" BACKEND_HASH
if errorlevel 1 exit /b 1
call :ensure_backend_pip
if errorlevel 1 exit /b 1
call :read_hash_stamp "%BACKEND_REQ_STAMP%" BACKEND_STORED_HASH
if defined BACKEND_STORED_HASH (
    set "BACKEND_STAMP_STATE=valid"
    call :is_valid_hash BACKEND_STORED_HASH
    if errorlevel 1 set "BACKEND_STAMP_STATE=invalid"
)

if /I "!BACKEND_STORED_HASH!"=="!BACKEND_HASH!" if /I "!BACKEND_STAMP_STATE!"=="valid" (
    echo       Status: skipping backend pip install ^(requirements unchanged^).
    exit /b 0
)

if "!BACKEND_VENV_CREATED!"=="1" (
    echo       Status: installing backend dependencies into the new virtual environment...
    goto :install_backend_deps
)
if "!BACKEND_VENV_REBUILT!"=="1" (
    echo       Status: installing backend dependencies after rebuilding the virtual environment...
    goto :install_backend_deps
)

if /I "!BACKEND_STAMP_STATE!"=="valid" (
    echo       Status: installing backend dependencies ^(requirements changed^).
    goto :install_backend_deps
)

call :backend_dependencies_present
if not errorlevel 1 (
    echo       Status: repairing backend dependency stamp without reinstalling.
    call :write_hash_stamp "%BACKEND_REQ_STAMP%" "!BACKEND_HASH!"
    exit /b 0
)

echo       Status: backend dependency stamp is !BACKEND_STAMP_STATE!, installing dependencies...
:install_backend_deps
"%BACKEND_VENV%\Scripts\python.exe" -m pip install -r "%BACKEND_REQ%" --disable-pip-version-check --quiet
if errorlevel 1 (
    echo ERROR: pip install failed.
    exit /b 1
)
call :write_hash_stamp "%BACKEND_REQ_STAMP%" "!BACKEND_HASH!"
echo       Status: backend dependencies ready.
exit /b 0

:ensure_frontend_deps
set "FRONTEND_HASH="
set "FRONTEND_STORED_HASH="
set "FRONTEND_STAMP_STATE=missing"
call :compute_sha256 "%FRONTEND_DEPS_SOURCE%" FRONTEND_HASH
if errorlevel 1 exit /b 1
call :read_hash_stamp "%FRONTEND_DEPS_STAMP%" FRONTEND_STORED_HASH
if defined FRONTEND_STORED_HASH (
    set "FRONTEND_STAMP_STATE=valid"
    call :is_valid_hash FRONTEND_STORED_HASH
    if errorlevel 1 set "FRONTEND_STAMP_STATE=invalid"
)

if exist "frontend\node_modules" if /I "!FRONTEND_STORED_HASH!"=="!FRONTEND_HASH!" if /I "!FRONTEND_STAMP_STATE!"=="valid" (
    echo       Status: skipping npm install ^(dependencies unchanged^).
    exit /b 0
)

if not exist "frontend\node_modules" (
    echo       Status: installing frontend dependencies ^(node_modules missing^).
    goto :install_frontend_deps
)

if /I "!FRONTEND_STAMP_STATE!"=="valid" (
    echo       Status: installing frontend dependencies ^(dependency lock changed^).
    goto :install_frontend_deps
)

call :frontend_dependencies_present
if not errorlevel 1 (
    echo       Status: repairing frontend dependency stamp without reinstalling.
    call :write_hash_stamp "%FRONTEND_DEPS_STAMP%" "!FRONTEND_HASH!"
    exit /b 0
)

echo       Status: frontend dependency stamp is !FRONTEND_STAMP_STATE!, installing dependencies...
:install_frontend_deps
pushd frontend
call "%NPM_EXE%" install
if errorlevel 1 (
    popd
    echo ERROR: npm install failed.
    exit /b 1
)
popd
if not exist "frontend\node_modules" (
    echo ERROR: npm install finished but node_modules was not created.
    exit /b 1
)
call :write_hash_stamp "%FRONTEND_DEPS_STAMP%" "!FRONTEND_HASH!"
echo       Status: frontend dependencies ready.
exit /b 0

:backend_dependencies_present
"%BACKEND_VENV%\Scripts\python.exe" -m pip show fastapi uvicorn pydantic networkx chromadb google-genai httpx python-multipart python-dotenv >nul 2>nul
if errorlevel 1 exit /b 1
exit /b 0

:ensure_backend_pip
"%BACKEND_VENV%\Scripts\python.exe" -m pip --version >nul 2>nul
if not errorlevel 1 exit /b 0
echo       Status: bootstrapping pip in the backend virtual environment...
"%BACKEND_VENV%\Scripts\python.exe" -m ensurepip --upgrade >nul 2>nul
if errorlevel 1 (
    echo       Status: ensurepip failed, refreshing the backend virtual environment...
    if exist "%BACKEND_VENV%" (
        "%PYTHON_EXE%" -m venv --upgrade-deps "%BACKEND_VENV%" >nul 2>nul
    ) else (
        "%PYTHON_EXE%" -m venv "%BACKEND_VENV%" >nul 2>nul
    )
)
"%BACKEND_VENV%\Scripts\python.exe" -m pip --version >nul 2>nul
if errorlevel 1 (
    echo ERROR: Failed to bootstrap pip in the backend virtual environment.
    exit /b 1
)
exit /b 0

:frontend_dependencies_present
if not exist "frontend\node_modules\next\package.json" exit /b 1
if not exist "frontend\node_modules\react\package.json" exit /b 1
if not exist "frontend\node_modules\react-dom\package.json" exit /b 1
exit /b 0

:repair_backend_pyvenv_cfg
for %%I in ("%~2") do set "PYTHON_HOME=%%~dpI"
if "!PYTHON_HOME:~-1!"=="\" set "PYTHON_HOME=!PYTHON_HOME:~0,-1!"
>"%~1" (
    echo home = !PYTHON_HOME!
    echo include-system-site-packages = false
    echo version = %~3
    echo executable = %~2
)
exit /b 0

:get_python_minor_version
set "%~2="
set "PY_VERSION_FILE=%TEMP%\vysol-python-version-%RANDOM%%RANDOM%.tmp"
call "%~1" -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" > "%PY_VERSION_FILE%" 2>nul
if errorlevel 1 goto :get_python_minor_version_cleanup
if exist "%PY_VERSION_FILE%" set /p "%~2="<"%PY_VERSION_FILE%"
:get_python_minor_version_cleanup
if exist "%PY_VERSION_FILE%" del "%PY_VERSION_FILE%" >nul 2>nul
exit /b 0

:compute_sha256
set "%~2="
set "HASH_TARGET=%~f1"
for /f "usebackq delims=" %%H in (`powershell -NoProfile -Command "$ErrorActionPreference='Stop'; (Get-FileHash -Algorithm SHA256 -LiteralPath '%HASH_TARGET%').Hash.ToUpperInvariant()" 2^>nul`) do (
    set "%~2=%%H"
    goto :compute_sha256_done
)
:compute_sha256_done
if defined %~2 exit /b 0
echo ERROR: Failed to compute SHA256 for %~1.
exit /b 1

:read_hash_stamp
set "%~2="
if not exist "%~1" exit /b 0
set /p "%~2="<"%~1"
exit /b 0

:write_hash_stamp
>"%~1" echo %~2
exit /b 0

:is_valid_hash
set "HASH_VALUE=!%~1!"
if not defined HASH_VALUE exit /b 1
echo(!HASH_VALUE!| findstr /R /I "^[0-9A-F][0-9A-F]*$" >nul || exit /b 1
if "!HASH_VALUE:~63,1!"=="" exit /b 1
if not "!HASH_VALUE:~64,1!"=="" exit /b 1
exit /b 0

:start_step_timer
call :timestamp_centis STEP_START_CS
exit /b 0

:finish_step_timer
call :timestamp_centis STEP_END_CS
set /a STEP_ELAPSED_CS=STEP_END_CS-STEP_START_CS
if !STEP_ELAPSED_CS! lss 0 set /a STEP_ELAPSED_CS+=24*60*60*100
set /a STEP_ELAPSED_S=STEP_ELAPSED_CS/100
set /a STEP_ELAPSED_REM=STEP_ELAPSED_CS%%100
if !STEP_ELAPSED_REM! lss 10 set "STEP_ELAPSED_REM=0!STEP_ELAPSED_REM!"
echo       Completed in !STEP_ELAPSED_S!.!STEP_ELAPSED_REM!s.
exit /b 0

:timestamp_centis
set "NOW=%time: =0%"
set /a "%~1=(((1%NOW:~0,2%-100)*60 + (1%NOW:~3,2%-100))*60 + (1%NOW:~6,2%-100))*100 + (1%NOW:~9,2%-100)"
exit /b 0

:require_winget
where winget >nul 2>nul
if errorlevel 1 (
    echo ERROR: winget was not found. Install the missing prerequisite manually and re-run VySol.bat.
    exit /b 1
)
exit /b 0

:fail
echo.
echo Setup failed. Fix the error above and run VySol.bat again.
pause
exit /b 1
