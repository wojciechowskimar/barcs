@echo off
setlocal

rem BARCS - uruchamianie aplikacji Streamlit na Windows.
rem
rem Naprawia blad "'streamlit' is not recognized as an internal or
rem external command" - ten blad pojawia sie, gdy skrypt streamlit.exe
rem (instalowany przez pip do katalogu Scripts danej instalacji Pythona)
rem nie jest widoczny w zmiennej PATH. Ten plik omija problem calkowicie:
rem zamiast wywolywac "streamlit" jako samodzielna komende, uruchamia go
rem jako modul ("python -m streamlit") przez PELNA, jawnie wskazana
rem sciezke do interpretera Pythona, w ktorym streamlit jest zainstalowany.

cd /d "%~dp0"

set "PYTHON_EXE=C:\Users\mwojciechowski\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [BLAD] Nie znaleziono interpretera Pythona pod sciezka:
    echo   %PYTHON_EXE%
    echo.
    echo Twoja instalacja Pythona jest najwyrazniej pod inna sciezka.
    echo Sprawdz ja komenda:  where python
    echo a nastepnie zainstaluj zaleznosci i uruchom recznie, np.:
    echo   C:\sciezka\do\python.exe -m pip install -r requirements.txt
    echo   C:\sciezka\do\python.exe -m streamlit run app.py
    echo.
    pause
    exit /b 1
)

echo Sprawdzam, czy wymagane biblioteki sa zainstalowane...
"%PYTHON_EXE%" -c "import streamlit, pandas, plotly" 2>nul
if errorlevel 1 (
    echo Brakuje bibliotek - instaluje z requirements.txt...
    "%PYTHON_EXE%" -m pip install -r requirements.txt
)

echo.
echo ============================================================
echo   Uruchamiam BARCS - Financial Intelligence Platform
echo   Po starcie otworz w przegladarce: http://localhost:8501
echo   (Streamlit zwykle otwiera te strone automatycznie)
echo   Aby zatrzymac aplikacje: zamknij to okno albo wcisnij Ctrl+C
echo ============================================================
echo.

"%PYTHON_EXE%" -m streamlit run app.py

pause
