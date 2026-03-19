FROM python:3.12-slim

WORKDIR /app

# Install build dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools>=75 wheel

# Copy project files and install
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .

# Copy remaining files (config, etc.)
COPY . .

EXPOSE 8000

CMD ["uvicorn", "restext.main:app", "--host", "0.0.0.0", "--port", "8000"]
