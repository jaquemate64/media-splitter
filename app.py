import gradio as gr
import os
import re
import shutil
import tempfile
import subprocess
import zipfile
import requests
from pathlib import Path
from faster_whisper import WhisperModel

OUT_DIR = Path("/tmp/media_parts")
OUT_DIR.mkdir(parents=True, exist_ok=True)
MODEL_NAME = os.getenv("WHISPER_MODEL", "tiny")
DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
MODEL = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)

def safe_name(name):
    name = os.path.basename(str(name))
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return name or "archivo"

def download_url(url):
    url = (url or "").strip()
    if not url:
        return None
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    suffix = os.path.splitext(url.split("?")[0])[1] or ".bin"
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    with open(path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
    return path

def split_media(input_path, minutes):
    input_path = Path(input_path)
    stem = safe_name(input_path.stem)

    job_dir = OUT_DIR / stem
    if job_dir.exists():
        shutil.rmtree(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)

    out_pattern = str(job_dir / f"{stem}_part_%03d.ts")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-map", "0",
        "-c", "copy",
        "-f", "segment",
        "-segment_time", str(int(minutes) * 60),
        "-reset_timestamps", "1",
        "-segment_format", "mpegts",
        out_pattern,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    parts = sorted(job_dir.glob(f"{stem}_part_*.ts"))
    if not parts:
        raise RuntimeError("No se generaron partes.")

    zip_path = job_dir / f"{stem}_parts.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in parts:
            z.write(p, arcname=p.name)

    return str(zip_path), [str(p) for p in parts]

def transcribe_file(file_path, language):
    segments, info = MODEL.transcribe(
        file_path,
        language=None if language == "Auto" else language,
        vad_filter=True
    )
    text_parts = []
    for segment in segments:
        t = (segment.text or "").strip()
        if t:
            text_parts.append(t)
    return " ".join(text_parts).strip()

def process(file_path, url, minutes, language, progress=gr.Progress()):
    path = None

    if file_path:
        path = str(file_path)
    elif url and url.strip():
        path = download_url(url)

    if not path:
        return "Sube un archivo o pega una URL directa.", None, None, None

    try:
        progress(0.05, desc="Dividiendo archivo")
        zip_path, parts = split_media(path, minutes)

        transcripts = []
        total_parts = max(len(parts), 1)

        for idx, part in enumerate(parts, 1):
            progress((idx - 1) / total_parts, desc=f"Transcribiendo parte {idx}/{total_parts}")
            transcript = transcribe_file(part, language)
            transcripts.append(f"### Parte {idx}\n{Path(part).name}\n\n{transcript}\n")

        full_text = "\n".join(transcripts).strip()
        progress(1.0, desc="Terminado")
        return f"Listo: {len(parts)} partes generadas y transcritas.", zip_path, parts, full_text

    except subprocess.CalledProcessError as e:
        err = e.stderr.decode("utf-8", errors="ignore") if e.stderr else str(e)
        return f"Error FFmpeg:\n{err}", None, None, None
    except Exception as e:
        return f"Error: {str(e)}", None, None, None

with gr.Blocks(title="Media Studio") as demo:
    gr.Markdown("# Media Studio")
    gr.Markdown("Sube un archivo de audio/video o pega un enlace directo. La app lo dividirá en partes y lo transcribirá automáticamente.")

    with gr.Row():
        file_in = gr.File(label="Sube audio o video", type="filepath")
        url_in = gr.Textbox(label="O pega una URL directa", placeholder="https://.../archivo.mp4")

    with gr.Row():
        minutes = gr.Slider(1, 15, value=5, step=1, label="Minutos por parte")
        language = gr.Dropdown(["Auto", "es", "en", "pt", "fr", "it", "de"], value="Auto", label="Idioma")

    btn = gr.Button("Procesar y transcribir")

    status = gr.Textbox(label="Estado")
    zip_out = gr.File(label="ZIP descargable")
    parts_out = gr.Files(label="Partes generadas")
    transcript_out = gr.Textbox(label="Transcripción completa", lines=18)

    btn.click(
        fn=process,
        inputs=[file_in, url_in, minutes, language],
        outputs=[status, zip_out, parts_out, transcript_out]
    )

demo.queue().launch(
    server_name="0.0.0.0",
    server_port=7863,
    share=False
)
