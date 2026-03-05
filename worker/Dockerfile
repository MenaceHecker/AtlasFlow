FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir .

COPY app /app/app

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "app.main"]