FROM python:3.11-slim
RUN apt-get update && apt-get install -y chromium chromium-driver git curl ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && apt-get update && apt-get install -y nodejs && rm -rf /var/lib/apt/lists/*
WORKDIR /app/frontend
RUN npm install && npm run build:deploy
WORKDIR /app
RUN mkdir -p /app/aura/ui/static
ENV PYTHONPATH=/app
EXPOSE 7860
CMD ["python", "-m", "uvicorn", "aura.ui.server:app", "--host", "0.0.0.0", "--port", "7860"]
