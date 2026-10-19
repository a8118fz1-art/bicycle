@echo off
cd /d %~dp0
cmd /k py -3.13 dyno_f1timer.py --plan 60B
