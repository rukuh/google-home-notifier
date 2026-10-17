FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8091

CMD ["gunicorn", "--bind", "0.0.0.0:8091", "app:app", "--workers", "1", "--threads", "2"]
