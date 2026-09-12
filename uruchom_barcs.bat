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

rem Szukamy dzialajacego interpretera Pythona po kolei, zamiast trzymac na
rem sztywno sciezke jednego, konkretnego uzytkownika/instalacji (taka
rem sciezka dzialalaby tylko na jednym komputerze) - kazda z ponizszych
rem opcji jest sprawdzana po kolei i uzywamy pierwszej, ktora zadziala:
rem   1) launcher "py" (standard przy instalacji z python.org),
rem   2) "python" widoczny w PATH,
rem   3) Python 3.13 z Microsoft Store, ktory instaluje sie zawsze pod
rem      %LOCALAPPDATA% biezacego uzytkownika (wiec dziala dla kazdego,
rem      nie tylko dla oryginalnego autora tego skryptu).
rem PYTHON_EXE trzyma TYLKO nazwe/sciezke programu (bez argumentow), a
rem ewentualny argument launchera ("-3") jest osobno w PYTHON_LAUNCHER_ARG -
rem dzieki temu kazde wywolanie nizej moze bezpiecznie uzywac
rem "%PYTHON_EXE%" %PYTHON_LAUNCHER_ARG% ... niezaleznie od tego, ktora
rem z trzech opcji ponizej zostala znaleziona (gdyby "py -3" trzymac w
rem jednej zmiennej i wziac w cudzyslow, cmd.exe szukalby programu o
rem nazwie doslownie "py -3", ktory nie istnieje).
set "PYTHON_EXE="
set "PYTHON_LAUNCHER_ARG="
set "STORE_PYTHON=%LOCALAPPDATA%\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe"

rem Przebieg 1: komputer moze miec zainstalowanych kilka Pythonow naraz
rem (np. z python.org, Microsoft Store i osobno w Program Files) - zamiast
rem brac "pierwszy z brzegu", sprawdzamy najpierw, czy ktorys z nich ma JUZ
rem zainstalowane wymagane biblioteki, i uzywamy tego. Unika to sytuacji, w
rem ktorej wybierzemy interpreter bez streamlit/pandas/plotly tylko dlatego,
rem ze jest wyzej w PATH.
where py >nul 2>nul && (
    py -3 -c "import streamlit, pandas, plotly" >nul 2>nul && (
        set "PYTHON_EXE=py"
        set "PYTHON_LAUNCHER_ARG=-3"
    )
)
if not defined PYTHON_EXE (
    where python >nul 2>nul && (
        python -c "import streamlit, pandas, plotly" >nul 2>nul && set "PYTHON_EXE=python"
    )
)
if not defined PYTHON_EXE (
    if exist "%STORE_PYTHON%" (
        "%STORE_PYTHON%" -c "import streamlit, pandas, plotly" >nul 2>nul && set "PYTHON_EXE=%STORE_PYTHON%"
    )
)

rem Przebieg 2: zaden interpreter nie ma jeszcze wymaganych bibliotek -
rem bierzemy pierwszy, ktory w ogole dziala, a instalacja brakujacych
rem pakietow nastapi automatycznie w kroku ponizej.
if not defined PYTHON_EXE (
    where py >nul 2>nul && (
        py -3 -c "import sys" >nul 2>nul && (
            set "PYTHON_EXE=py"
            set "PYTHON_LAUNCHER_ARG=-3"
        )
    )
)
if not defined PYTHON_EXE (
    where python >nul 2>nul && (
        python -c "import sys" >nul 2>nul && set "PYTHON_EXE=python"
    )
)
if not defined PYTHON_EXE (
    if exist "%STORE_PYTHON%" set "PYTHON_EXE=%STORE_PYTHON%"
)

if not defined PYTHON_EXE (
    echo [BLAD] Nie znaleziono zadnego interpretera Pythona ^(sprawdzono: py,
    echo   python w PATH, oraz Python 3.13 z Microsoft Store^).
    echo.
    echo Zainstaluj Pythona 3.11+ ^(np. z python.org lub Microsoft Store^),
    echo a nastepnie uruchom recznie, np.:
    echo   C:\sciezka\do\python.exe -m pip install -r requirements.txt
    echo   C:\sciezka\do\python.exe -m streamlit run app.py
    echo.
    pause
    exit /b 1
)

echo Sprawdzam, czy wymagane biblioteki sa zainstalowane...
"%PYTHON_EXE%" %PYTHON_LAUNCHER_ARG% -c "import streamlit, pandas, plotly" 2>nul
if errorlevel 1 (
    echo Brakuje bibliotek - instaluje z requirements.txt...
    "%PYTHON_EXE%" %PYTHON_LAUNCHER_ARG% -m pip install -r requirements.txt
)

echo.
echo ============================================================
echo   Uruchamiam BARCS - Financial Intelligence Platform
echo   Po starcie otworz w przegladarce: http://localhost:8501
echo   (Streamlit zwykle otwiera te strone automatycznie)
echo   Aby zatrzymac aplikacje: zamknij to okno albo wcisnij Ctrl+C
echo ============================================================
echo.

"%PYTHON_EXE%" %PYTHON_LAUNCHER_ARG% -m streamlit run app.py

pause
