FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the source code
COPY src/ src/

RUN mkdir -p /app/documents && chmod 777 /app/documents

# Expose port 8080
ENV PORT=8080

# Run the application
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8080"]
