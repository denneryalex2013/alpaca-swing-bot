FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY storage/ ./storage/
COPY monthly_report.py .

CMD ["python", "-m", "app.main"]
