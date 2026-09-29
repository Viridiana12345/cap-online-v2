if (-not (Test-Path "venv")) { py -m venv venv }
& .\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
$env:DEBUG="True"
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
