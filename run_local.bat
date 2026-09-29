@echo off
setlocal
if not exist venv (
  py -m venv venv
)
call venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
set DEBUG=True
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
