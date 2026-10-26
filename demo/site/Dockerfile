FROM python:3.11-slim

WORKDIR /app

# Run as non-root user
RUN useradd -m -u 1000 demouser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py index.html ./

ENV PYTHONUNBUFFERED=1

USER demouser

EXPOSE 8090

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8090"]
