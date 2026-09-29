FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

CMD sh -c "python manage.py migrate && python manage.py collectstatic --noinput && gunicorn cap_online.wsgi:application --bind 0.0.0.0:${PORT:-8000}"