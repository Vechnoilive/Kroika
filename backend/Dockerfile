FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements-stage3.txt requirements-stage4.txt requirements-stage5.txt requirements-stage6.txt pyproject.toml ./
COPY schemas ./schemas
COPY src ./src
COPY pattern-engine ./pattern-engine
COPY backend ./backend

RUN python -m pip install --no-cache-dir -r requirements-stage6.txt \
    && python -m pip install --no-cache-dir --no-deps -e . -e ./pattern-engine -e ./backend

RUN useradd --create-home --uid 10001 kroika \
    && mkdir -p /app/data \
    && chown -R kroika:kroika /app

USER kroika
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "kroika_backend.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
