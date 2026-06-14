FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY src/ src/
COPY config/ config/
COPY data/seeds/ data/seeds/

RUN pip install --no-cache-dir .

RUN useradd --create-home appuser \
    && mkdir -p /app/data /app/output \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "scoredclub.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
