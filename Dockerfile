FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl docker.io git openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 9000

CMD ["uvicorn", "webhook:app", "--host", "0.0.0.0", "--port", "9000"]
