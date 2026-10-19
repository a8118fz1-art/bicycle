@echo off
rem 離線安裝 pywinauto（dyno_f1timer 只需要它；wheel 是 cp313 win_amd64，必須用 Python 3.13 64 位元）
cd /d %~dp0
py -3.13 -m pip install --no-index --find-links=. pywinauto
py -3.13 -c "import pywinauto, tomllib, sys; print('OK', sys.version)"
pause
