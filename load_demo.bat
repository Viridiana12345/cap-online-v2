@echo off
call venv\Scripts\activate
set DEBUG=True
python manage.py seed_demo
pause
