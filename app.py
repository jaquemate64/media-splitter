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

    return job_dir, parts

def make_zip(job_dir, stem):
    zip_path = job_dir / f"{stem}_parts.zip"
    parts = sorted(job_dir.glob(f"{stem}_part_*.ts"))
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in parts:
            z.write(p, arcname=p.name)
    return str(zip_path)

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

def process_whole(file_path, url, language, progress=gr.Progress()):
    path = None

    if file_path:
        path = str(file_path)
    elif url and url.strip():
        path = download_url(url)

    if not path:
        return "Sube un archivo o pega una URL directa.", None, None, None, []

    try:
        progress(0.1, desc="Transcribiendo archivo completo")
        transcript = transcribe_file(path, language)
        progress(1.0, desc="Terminado")
        return "Listo: archivo completo transcrito.", None, None, transcript, []

    except Exception as e:
        return f"Error: {str(e)}", None, None, None, []

def process_parts(file_path, url, minutes, language, progress=gr.Progress()):
    path = None

    if file_path:
        path = str(file_path)
    elif url and url.strip():
        path = download_url(url)

    if not path:
        return "Sube un archivo o pega una URL directa.", None, None, None, [], gr.update(interactive=False)

    try:
        input_path = Path(path)
        stem = safe_name(input_path.stem)

        progress(0.05, desc="Dividiendo archivo")
        job_dir, parts = split_media(path, minutes)
        zip_path = make_zip(job_dir, stem)

        transcripts = []
        results = []

        total = max(len(parts), 1)
        for idx, part in enumerate(parts, 1):
            progress((idx - 1) / total, desc=f"Transcribiendo parte {idx}/{total}")
            try:
                transcript = transcribe_file(part, language)
                transcripts.append(f"### Parte {idx}\n{Path(part).name}\n\n{transcript}\n")
                results.append(f"Parte {idx}: OK")
            except Exception as e:
                transcripts.append(f"### Parte {idx}\n{Path(part).name}\n\nERROR: {str(e)}\n")
                results.append(f"Parte {idx}: ERROR")

        full_text = "\n".join(transcripts).strip()
        ready = all("OK" in r for r in results)
        progress(1.0, desc="Terminado")

        return (
            f"Listo: {len(parts)} partes procesadas.",
            zip_path,
            [str(p) for p in parts],
            full_text,
            results,
            gr.update(interactive=ready)
        )

    except Exception as e:
        return f"Error: {str(e)}", None, None, None, [], gr.update(interactive=False)

def retry_part(file_path, url, minutes, language, part_name, progress=gr.Progress()):
    if not part_name:
        return "Selecciona una parte para reintentar.", None, None, None, [], gr.update(interactive=False)

    try:
        path = None
        if file_path:
            path = str(file_path)
        elif url and url.strip():
            path = download_url(url)

        if not path:
            return "Sube un archivo o pega una URL directa.", None, None, None, [], gr.update(interactive=False)

        input_path = Path(path)
        stem = safe_name(input_path.stem)
        job_dir = OUT_DIR / stem

        part_path = job_dir / part_name
        if not part_path.exists():
            return f"No existe la parte: {part_name}", None, None, None, [], gr.update(interactive=False)

        progress(0.2, desc=f"Reintentando {part_name}")
        transcript = transcribe_file(str(part_path), language)
        progress(1.0, desc="Reintento terminado")

        return (
            f"Reintento OK: {part_name}",
            None,
            None,
            f"### {part_name}\n\n{transcript}\n",
            [f"{part_name}: OK"],
            gr.update(interactive=True)
        )

    except Exception as e:
        return f"Error al reintentar: {str(e)}", None, None, None, [f"{part_name}: ERROR"], gr.update(interactive=False)

with gr.Blocks(title="Media Studio") as demo:
    gr.Markdown("# Media Studio")
    gr.Markdown("Sube un archivo o pega un enlace directo. Puedes procesar todo junto o por partes con reintentos.")

    with gr.Row():
        file_in = gr.File(label="Sube audio o video", type="filepath")
        url_in = gr.Textbox(label="O pega una URL directa", placeholder="https://.../archivo.mp4")

    mode = gr.Dropdown(
        ["Todo junto", "Por partes"],
        value="Por partes",
        label="Modo de procesamiento"
    )

    with gr.Row():
        minutes = gr.Slider(1, 15, value=5, step=1, label="Minutos por parte")
        language = gr.Dropdown(["Auto", "es", "en", "pt", "fr", "it", "de"], value="Auto", label="Idioma")

    with gr.Row():
        btn_whole = gr.Button("Procesar todo junto")
        btn_parts = gr.Button("Dividir y procesar por partes")
        btn_retry = gr.Button("Reintentar parte", interactive=False)
        btn_send = gr.Button("Enviar", interactive=False)

    part_selector = gr.Dropdown([], label="Parte a reintentar", interactive=True)

    status = gr.Textbox(label="Estado")
    zip_out = gr.File(label="ZIP descargable")
    parts_out = gr.Files(label="Partes generadas")
    transcript_out = gr.Textbox(label="Transcripción completa", lines=18)
    part_results = gr.Textbox(label="Estado por parte", lines=10)

    btn_whole.click(
        fn=process_whole,
        inputs=[file_in, url_in, language],
        outputs=[status, zip_out, parts_out, transcript_out, part_results]
    )

    btn_parts.click(
        fn=process_parts,
        inputs=[file_in, url_in, minutes, language],
        outputs=[status, zip_out, parts_out, transcript_out, part_results, btn_send]
    ).then(
        lambda files: gr.Dropdown(choices=files if files else [], value=None, interactive=True),
        inputs=parts_out,
        outputs=part_selector
    )

    btn_retry.click(
        fn=retry_part,
        inputs=[file_in, url_in, minutes, language, part_selector],
        outputs=[status, zip_out, parts_out, transcript_out, part_results, btn_send]
    )

demo.queue().launch(
    server_name="0.0.0.0",
    server_port=7863,
    share=False
)
