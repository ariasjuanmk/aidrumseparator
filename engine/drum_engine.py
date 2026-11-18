#!/usr/bin/env python3
"""AI Drum Separation VST - motor de separacion de bateria (audio-separator).

Subcomandos:
  probe        Informa que hay instalado (audio-separator, torch, CUDA, ffmpeg).
  separate     Separa una pista de bateria en 4 stems (kick, snare, toms, cymbals)
               usando CUDA si esta disponible y, si no, CPU.
  fetch-model  Descarga el modelo DrumSep (lo usa el instalador).
  setup        Crea un entorno virtual propio e instala torch (CUDA si hay GPU
               NVIDIA), audio-separator y el resto de dependencias.

Protocolo de salida (una linea por mensaje, stdout, UTF-8):
  PROBE  {json}
  STATUS texto
  PROGRESS 0-100
  RESULT {json}
  ERROR  texto
  LOG    texto

Basado en el ReaScript "Drum Separation v2" de Oliver Tkach (MIT, 2026): mismo
modelo y misma logica de unir hh + ride + crash en un unico stem "cymbals".
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import traceback

try:  # salida en UTF-8 y sin buffer, para que el plugin lea en vivo
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

DEFAULT_MODEL = "MDX23C-DrumSep-aufr33-jarredou.ckpt"
STEMS = ["kick", "snare", "toms", "cymbals"]
CYMBAL_PARTS = ("hh", "ride", "crash", "cymbal", "hihat", "hi-hat")
# Ruedas de PyTorch con CUDA, de mas nueva a mas vieja.
CUDA_INDEXES = ["cu130", "cu129", "cu128", "cu126", "cu124", "cu118"]
# Version minima de "CUDA Version" (nvidia-smi) que necesita cada rueda.
CUDA_MIN_DRIVER = {"cu130": (13, 0), "cu129": (12, 9), "cu128": (12, 8),
                   "cu126": (12, 6), "cu124": (12, 4), "cu118": (11, 8)}
EXTRA_DEPS = ["soundfile", "librosa", "numpy"]


def emit(tag: str, payload: str = "") -> None:
    print(f"{tag} {payload}".rstrip(), flush=True)


def models_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "AIDrumSeparator", "models")


# --------------------------------------------------------------------------
# probe
# --------------------------------------------------------------------------
def cmd_probe(_args) -> int:
    info = {
        "python": ".".join(map(str, sys.version_info[:3])),
        "python_ok": (3, 10) <= sys.version_info[:2] <= (3, 12),
        "separator": False,
        "torch": None,
        "cuda": False,
        "gpu": None,
        "nvidia_gpu_present": shutil.which("nvidia-smi") is not None,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "soundfile": False,
    }
    try:
        import importlib.metadata as md
        md.version("audio-separator")
        info["separator"] = True
    except Exception:
        pass
    try:
        import torch
        info["torch"] = torch.__version__
        info["cuda"] = bool(torch.cuda.is_available())
        if info["cuda"]:
            info["gpu"] = torch.cuda.get_device_name(0)
    except Exception:
        pass
    try:
        import soundfile  # noqa: F401
        info["soundfile"] = True
    except Exception:
        pass
    emit("PROBE", json.dumps(info))
    return 0


# --------------------------------------------------------------------------
# progreso: audio-separator usa tqdm sobre stderr
# --------------------------------------------------------------------------
class ProgressTee:
    """Reemplaza sys.stderr y traduce las barras de tqdm a lineas PROGRESS."""

    PCT = re.compile(r"(\d+)%\|")

    def __init__(self, passes: int):
        self.passes = max(1, passes)
        self.index = 0
        self.last = -1
        self.buf = ""

    def write(self, s):
        self.buf += s
        parts = re.split(r"[\r\n]", self.buf)
        self.buf = parts.pop()
        for part in parts:
            m = self.PCT.search(part)
            if not m:
                if part.strip():
                    emit("LOG", part.strip()[:300])
                continue
            pct = int(m.group(1))
            if pct < self.last:  # empezo otra pasada (shifts > 1)
                self.index = min(self.index + 1, self.passes - 1)
            self.last = pct
            overall = (self.index + pct / 100.0) / self.passes
            emit("PROGRESS", str(int(min(99, overall * 100))))
        return len(s)

    def flush(self):
        pass

    def isatty(self):
        return False


# --------------------------------------------------------------------------
# clasificacion de las salidas del modelo
# --------------------------------------------------------------------------
TAG = re.compile(r"_\(([^)]*)\)_")


def classify(filename: str) -> str | None:
    """Devuelve 'kick', 'snare', 'toms', 'cymbals' o None segun el nombre del archivo."""
    base = os.path.basename(filename)
    m = TAG.search(base)
    # el tag "_(Kick)_" es lo fiable; si no esta, se busca en el nombre sin la ruta
    text = (m.group(1) if m else base).lower()
    if "kick" in text:
        return "kick"
    if "snare" in text:
        return "snare"
    if "tom" in text:
        return "toms"
    if any(p in text for p in CYMBAL_PARTS):
        return "cymbals"
    return None


def cmd_fetch_model(args) -> int:
    try:
        from audio_separator.separator import Separator
    except Exception as exc:
        emit("ERROR", f"audio-separator no esta instalado: {exc}")
        return 12
    os.makedirs(models_dir(), exist_ok=True)
    real = sys.stderr
    sys.stderr = ProgressTee(passes=1)
    try:
        emit("STATUS", "Descargando el modelo DrumSep...")
        sep = Separator(output_dir=os.path.join(models_dir(), "_tmp"), output_format="WAV",
                        model_file_dir=models_dir())
        sep.load_model(model_filename=args.model)
    except Exception as exc:
        sys.stderr = real
        emit("ERROR", f"No se pudo descargar el modelo: {exc}")
        return 16
    finally:
        sys.stderr = real
    shutil.rmtree(os.path.join(models_dir(), "_tmp"), ignore_errors=True)
    emit("PROGRESS", "100")
    return 0


# --------------------------------------------------------------------------
# separate
# --------------------------------------------------------------------------
def rerun_on_cpu(args) -> int:
    cmd = [sys.executable, "-u", os.path.abspath(__file__), "separate", args.input,
           "--out", args.out, "--model", args.model, "--device", "cpu", "--no-retry"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace")
    for line in p.stdout:
        print(line.rstrip("\n"), flush=True)
    return p.wait()


def cmd_separate(args) -> int:
    if args.device == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"   # antes de importar torch

    if not os.path.isfile(args.input):
        emit("ERROR", f"No existe el archivo: {args.input}")
        return 15

    real_stderr = sys.stderr
    sys.stderr = ProgressTee(passes=1)   # antes de crear el Separator (su logger captura stderr)
    try:
        try:
            import torch
            import soundfile as sf
            import numpy as np
            from audio_separator.separator import Separator
        except Exception as exc:
            sys.stderr = real_stderr
            emit("ERROR", f"Faltan dependencias (audio-separator/torch/soundfile): {exc}")
            return 12

        cuda = bool(torch.cuda.is_available()) and args.device != "cpu"
        gpu_name = torch.cuda.get_device_name(0) if cuda else None
        if cuda:
            emit("STATUS", f"Separando con CUDA ({gpu_name})...")
        elif args.device == "cuda":
            emit("STATUS", "No hay CUDA disponible: usando CPU (mas lento)...")
        else:
            emit("STATUS", "Separando con CPU (mas lento que con GPU NVIDIA)...")
        device = "cuda" if cuda else "cpu"

        out_dir = os.path.join(args.out, "stems")
        raw_dir = os.path.join(args.out, "raw")
        shutil.rmtree(out_dir, ignore_errors=True)
        shutil.rmtree(raw_dir, ignore_errors=True)
        os.makedirs(out_dir, exist_ok=True)
        os.makedirs(raw_dir, exist_ok=True)
        os.makedirs(models_dir(), exist_ok=True)

        try:
            emit("STATUS", "Cargando modelo DrumSep (la primera vez se descarga)...")
            sep = Separator(output_dir=raw_dir, output_format="WAV", model_file_dir=models_dir())
            sep.load_model(model_filename=args.model)
            emit("STATUS", f"Separando bateria con {'CUDA' if cuda else 'CPU'}...")
            outputs = sep.separate(args.input)
        except Exception as exc:
            sys.stderr = real_stderr
            if cuda and not args.no_retry:
                emit("STATUS", f"CUDA fallo ({str(exc)[:80]}). Reintentando en CPU...")
                return rerun_on_cpu(args)
            emit("ERROR", f"Fallo la separacion: {exc}")
            traceback.print_exc(file=sys.stdout)
            return 18
    finally:
        sys.stderr = real_stderr

    # --- renombrar y mezclar ------------------------------------------------
    emit("STATUS", "Ordenando stems...")
    found: dict[str, list[str]] = {k: [] for k in STEMS}
    for out in outputs or []:
        path = out if os.path.isabs(out) and os.path.exists(out) else os.path.join(raw_dir, os.path.basename(out))
        if not os.path.exists(path):
            continue
        kind = classify(path)
        if kind:
            found[kind].append(path)

    samplerate = 44100
    length = 0
    channels = 2
    audio: dict[str, "np.ndarray"] = {}
    for kind in STEMS:
        mix = None
        for p in found[kind]:
            data, sr = sf.read(p, always_2d=True, dtype="float32")
            samplerate = int(sr)
            channels = data.shape[1]
            if mix is None:
                mix = data
            else:
                n = min(len(mix), len(data))
                mix = mix[:n] + data[:n]
        if mix is not None:
            audio[kind] = mix
            length = max(length, len(mix))

    if not audio:
        emit("ERROR", "El modelo no devolvio stems de bateria reconocibles. "
                      "Usa una pista de bateria aislada y el modelo DrumSep.")
        return 19

    saved = []
    for kind in STEMS:
        data = audio.get(kind)
        if data is None:   # stem ausente: silencio, asi siempre hay 4 archivos
            data = np.zeros((length, channels), dtype="float32")
        elif len(data) < length:
            data = np.pad(data, ((0, length - len(data)), (0, 0)))
        peak = float(np.abs(data).max()) if data.size else 0.0
        if peak > 1.0:   # al sumar hh+ride+crash puede pasar de 0 dBFS
            data = data / (peak * 1.01)
        sf.write(os.path.join(out_dir, f"{kind}.wav"), data, samplerate, subtype="PCM_24")
        saved.append(kind)
    shutil.rmtree(raw_dir, ignore_errors=True)

    result = {
        "stems_dir": out_dir,
        "stems": saved,
        "samplerate": samplerate,
        "device": device,
        "gpu": gpu_name,
        "bpm": 0,
        "key": "",
        "hz": 0,
    }
    with open(os.path.join(args.out, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f)
    emit("PROGRESS", "100")
    emit("RESULT", json.dumps(result))
    return 0


# --------------------------------------------------------------------------
# setup: entorno virtual propio con torch (CUDA si hay GPU NVIDIA) + audio-separator
# --------------------------------------------------------------------------
def venv_python(venv: str) -> str:
    if os.name == "nt":
        return os.path.join(venv, "Scripts", "python.exe")
    return os.path.join(venv, "bin", "python")


def run_logged(cmd) -> int:
    emit("LOG", " ".join(cmd))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    for line in p.stdout:
        line = line.strip()
        if line:
            emit("LOG", line[:300])
    return p.wait()


def driver_cuda_version():
    """Lee 'CUDA Version: X.Y' de nvidia-smi (la CUDA maxima que soporta el driver)."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe], capture_output=True, text=True, timeout=20).stdout
        m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", out)
        return (int(m.group(1)), int(m.group(2))) if m else None
    except Exception:
        return None


def candidate_indexes():
    ver = driver_cuda_version()
    if ver is None:
        return list(CUDA_INDEXES)
    ok = [t for t in CUDA_INDEXES if CUDA_MIN_DRIVER[t] <= ver]
    return ok or ["cu118"]


def torch_has_cuda(py: str) -> bool:
    return subprocess.run([py, "-c", "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)"],
                          capture_output=True).returncode == 0


# El indice de PyTorch no tiene todas las dependencias de torch (con --index-url pip falla, p. ej.,
# al compilar typing-extensions): torch/torchaudio van sin dependencias y estas se instalan desde PyPI.
TORCH_DEPS = ["filelock", "typing-extensions", "sympy", "networkx", "jinja2", "fsspec", "setuptools"]


def install_torch_cuda(py: str, tag: str) -> int:
    rc = run_logged([py, "-m", "pip", "install", "--no-deps", "--upgrade", "--force-reinstall",
                     "torch", "torchaudio", "--index-url", f"https://download.pytorch.org/whl/{tag}"])
    if rc != 0:
        return rc
    return run_logged([py, "-m", "pip", "install", *TORCH_DEPS])



def cmd_setup(args) -> int:
    if not ((3, 10) <= sys.version_info[:2] <= (3, 12)):
        emit("ERROR", "Se necesita Python 3.10, 3.11 o 3.12.")
        return 11
    venv = args.venv
    py = venv_python(venv)

    emit("STATUS", "Creando entorno virtual...")
    emit("PROGRESS", "5")
    if not os.path.isfile(py):
        if run_logged([sys.executable, "-m", "venv", venv]) != 0:
            emit("ERROR", "No se pudo crear el entorno virtual.")
            return 20

    emit("STATUS", "Actualizando pip...")
    run_logged([py, "-m", "pip", "install", "--upgrade", "pip"])
    emit("PROGRESS", "10")

    have_nvidia = shutil.which("nvidia-smi") is not None and not args.cpu_only
    gpu_ok = False
    if have_nvidia:
        for tag in candidate_indexes():
            emit("STATUS", f"Instalando PyTorch con CUDA ({tag})... (varios GB)")
            rc = install_torch_cuda(py, tag)
            if rc == 0 and torch_has_cuda(py):
                gpu_ok = True
                break
            emit("LOG", f"{tag}: no quedo CUDA operativo, pruebo otra rueda")
    if not gpu_ok:
        emit("STATUS", "Instalando PyTorch (CPU)...")
        if run_logged([py, "-m", "pip", "install", "torch", "torchaudio", "--upgrade", "--force-reinstall"]) != 0:
            emit("ERROR", "No se pudo instalar PyTorch.")
            return 21
    emit("PROGRESS", "65")

    emit("STATUS", "Instalando audio-separator y dependencias...")
    extra = "gpu" if gpu_ok else "cpu"
    if run_logged([py, "-m", "pip", "install", f"audio-separator[{extra}]>=0.22.4"]) != 0:
        emit("ERROR", "No se pudo instalar audio-separator.")
        return 22
    if run_logged([py, "-m", "pip", "install", *EXTRA_DEPS]) != 0:
        emit("ERROR", "No se pudieron instalar las dependencias.")
        return 23
    # audio-separator[gpu] puede arrastrar un torch distinto: si perdio CUDA, avisar
    if gpu_ok and not torch_has_cuda(py):
        emit("STATUS", "Aviso: PyTorch perdio CUDA al instalar audio-separator; se usara la CPU.")
    emit("PROGRESS", "100")
    emit("RESULT", json.dumps({"python": py}))
    return 0


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe")

    sp = sub.add_parser("separate")
    sp.add_argument("input")
    sp.add_argument("--out", required=True, help="carpeta de salida (cache)")
    sp.add_argument("--model", default=DEFAULT_MODEL)
    sp.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    sp.add_argument("--no-retry", action="store_true", help=argparse.SUPPRESS)
    # el plugin puede pasar opciones del plugin 1; se ignoran
    sp.add_argument("--quality", default=None, help=argparse.SUPPRESS)
    sp.add_argument("--two-stems", default=None, help=argparse.SUPPRESS)
    sp.add_argument("--precision", default=None, help=argparse.SUPPRESS)
    sp.add_argument("--jobs", default=None, help=argparse.SUPPRESS)

    fm = sub.add_parser("fetch-model")
    fm.add_argument("--model", default=DEFAULT_MODEL)

    st = sub.add_parser("setup")
    st.add_argument("--venv", required=True)
    st.add_argument("--cpu-only", action="store_true")

    args = ap.parse_args()
    try:
        return {"probe": cmd_probe, "separate": cmd_separate, "setup": cmd_setup,
                "fetch-model": cmd_fetch_model}[args.cmd](args)
    except SystemExit:
        raise
    except Exception as exc:
        emit("ERROR", f"Error inesperado: {exc}")
        traceback.print_exc(file=sys.stdout)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
