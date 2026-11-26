@echo off
py -3 -B "%~dp0integrations\clod\fire_lab.py" --terrain "%~dp0terrain\london-20m.json" --front-fx --light-data --split-fx --dense-fx --district-lights 24 --warm-smoke
if errorlevel 1 pause
