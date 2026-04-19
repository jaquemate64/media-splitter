from pathlib import Path
req = 'gradio\nrequests\nfaster-whisper\n'
docker = '''FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

RUN mkdir -p /tmp/gradio /tmp/media_parts
ENV GRADIO_TEMP_DIR=/tmp/gradio
ENV GRADIO_SERVER_NAME=0.0.0.0
ENV WHISPER_MODEL=tiny
ENV WHISPER_DEVICE=cpu
ENV WHISPER_COMPUTE_TYPE=int8

EXPOSE 7863

CMD ["python", "app.py"]
'''
Path('output').mkdir(exist_ok=True)
Path('output/requirements.txt').write_text(req, encoding='utf-8')
Path('output/Dockerfile').write_text(docker, encoding='utf-8')
print('written requirements and Dockerfile')
