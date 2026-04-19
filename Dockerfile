FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

RUN mkdir -p /tmp/gradio /tmp/media_parts
ENV GRADIO_TEMP_DIR=/tmp/gradio
ENV GRADIO_SERVER_NAME=0.0.0.0

EXPOSE 7863

CMD ["python", "app.py"]
