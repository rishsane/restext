FROM python:3.12-slim

WORKDIR /app

# Install dependencies from requirements.txt (bypasses pyproject.toml build system)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Install the package in editable mode
ENV PYTHONPATH=/app/src

EXPOSE 8000

CMD ["uvicorn", "restext.main:app", "--host", "0.0.0.0", "--port", "8000"]
