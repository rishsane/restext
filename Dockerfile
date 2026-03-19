FROM python:3.12-slim

WORKDIR /app

# Upgrade pip and install build tools
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir "setuptools>=75" wheel

# Copy and install dependencies
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir --no-build-isolation .

# Copy remaining files
COPY . .

EXPOSE 8000

CMD ["uvicorn", "restext.main:app", "--host", "0.0.0.0", "--port", "8000"]
