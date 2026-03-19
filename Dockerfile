FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir setuptools wheel

COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .

COPY . .

EXPOSE 8000

CMD ["uvicorn", "restext.main:app", "--host", "0.0.0.0", "--port", "8000"]
