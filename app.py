import gradio as gr
import os
import re
import shutil
import tempfile
import subprocess
import zipfile
import requests
from pathlib import Path

OUT_DIR = Path("/tmp/media_parts")
OUT_DIR.mkdir(parents=True, exist_ok=True)

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
    ext = input_path.suffix or ".bin"

    job_dir = OUT_DIR / stem
    if job_dir.exists():
        shutil.rmtree(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)

    out_pattern = str(job_dir / f"{stem}_part_%03d{ext}")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-f", "segment",
        "-segment_time", str(int(minutes) * 60),
        "-c", "copy",
        "-reset_timestamps", "1",
        out_pattern,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    parts = sorted(job_dir.glob(f"{stem}_part_*{ext}"))
    if not parts:
        raise RuntimeError("No se generaron partes.")

    zip_path = job_dir / f"{stem}_parts.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in parts:
            z.write(p, arcname=p.name)

    return str(zip_path), [str(p) for p in parts]

def process(file_obj, url, minutes):
    path = None

    if file_obj:
        path = file_obj.name if hasattr(file_obj, "name") else str(file_obj)
    elif url and url.strip():
        path = download_url(url)

    if not path:
        return "Sube un archivo o pega una URL directa.", None, None

    try:
        zip_path, parts = split_media(path, minutes)
        return f"Listo: {len(parts)} partes generadas.", zip_path, parts
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode("utf-8", errors="ignore") if e.stderr else str(e)
        return f"Error FFmpeg:\\n{err}", None, None
    except Exception as e:
        return f"Error: {str(e)}", None, None

with gr.Blocks(title="Media Studio") as demo:
    gr.Markdown("# Media Studio")
    gr.Markdown("Sube un archivo de audio/video o pega un enlace directo. La app lo dividirá en partes y devolverá un ZIP.")

    with gr.Row():
        file_in = gr.File(label="Sube audio o video", file_types=["audio", "video"])
        url_in = gr.Textbox(label="O pega una URL directa", placeholder="https://.../archivo.mp4")

    minutes = gr.Slider(1, 15, value=5, step=1, label="Minutos por parte")
    btn = gr.Button("Procesar")

    status = gr.Textbox(label="Estado")
    zip_out = gr.File(label="ZIP descargable")
    parts_out = gr.Files(label="Partes generadas")

    btn.click(
        fn=process,
        inputs=[file_in, url_in, minutes],
        outputs=[status, zip_out, parts_out]
    )

demo.queue().launch(
    server_name="0.0.0.0",
    server_port=7863,
    share=False
)
