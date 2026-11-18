# AI Drum Separation (prototipo 0.1.2, solo Windows)

Plugin VST3 que separa una **pista de batería** en 4 stems — **Kick, Snare, Toms, Cymbals** — con el
modelo DrumSep (MDX23C, vía `audio-separator`) y los reproduce sincronizados con el DAW.
Usa **CUDA** si hay GPU NVIDIA con PyTorch compatible y, si no, **CPU** (más lento).

> **Estado:** el código está escrito pero **todavía no fue compilado ni probado**. Se espera que el primer
> build en GitHub Actions muestre algún error de compilación para corregir.

## Cómo funciona

1. Cargá el plugin como **instrumento** (VSTi) en una pista.
2. Soltá (o "Elegir archivo...") una pista de batería **aislada**. Si tenés una canción completa, sacá primero la batería
   (por ejemplo con el plugin *AI Stem Splitter*, stem "drums").
3. "Separar" lanza el motor Python (`engine/drum_engine.py`, embebido en el `.vst3`) en segundo plano.
4. Los stems quedan en `%LOCALAPPDATA%\AIDrumSeparator\cache\...` (si repetís el mismo archivo no se reprocesa).
5. Salidas estéreo: **Mix** (con mute / solo / ganancia) y **1 Kick, 2 Snare, 3 Toms, 4 Cymbals** sin procesar
   (se activan desde el DAW). Cymbals = hi-hat + ride + crash sumados.
6. También podés arrastrar cada stem (botón "arrastrar") o todos a la línea de tiempo.
7. **Offset**: desplaza los stems respecto al inicio del proyecto (ponelo igual a la posición del clip original).

### Motor y CUDA
- Menú **Motor > Instalar motor**: crea un venv en `%LOCALAPPDATA%\AIDrumSeparator\venv` y elige la rueda de PyTorch CUDA
  más nueva compatible con tu driver (según `nvidia-smi`); verifica que `torch.cuda.is_available()` sea verdadero y, si no, usa CPU.
- Si CUDA falla en ejecución (p. ej. poca VRAM), reintenta en CPU.
- Python soportado: 3.10 a 3.12. FFmpeg es recomendable (`winget install ffmpeg`).
- Modelo: `MDX23C-DrumSep-aufr33-jarredou.ckpt` (se descarga la primera vez).

## Instalador (Windows)
El workflow genera `AIDrumSeparator-Setup-<version>.exe` (Inno Setup): copia el plugin a
`C:\Program Files\Common Files\VST3\AI Drum Separation.vst3` e instala el motor para tu usuario
(descarga Python 3.12.10 desde python.org si no hay uno compatible). Registro: `%LOCALAPPDATA%\AIDrumSeparator\install.log`.
El instalador no está firmado (SmartScreen avisará).

## Compilar
**GitHub Actions:** subí esta carpeta a un repo, creá `.github/workflows/build-windows.yml` (viene en el zip) y corré el workflow.
Artefactos: `AIDrumSeparator-Setup` (instalador) y `AI-Drum-Separation-VST3-Windows` (solo el `.vst3`).

**Local:** Visual Studio 2022 (C++), CMake 3.22+, Inno Setup 6.
```
cmake -B build -A x64
cmake --build build --config Release --target AIDrumSeparator_VST3
```

## Licencias y créditos
- Basado en el ReaScript **Drum Separation v2** de **Oliver Tkach** (MIT, ver `LICENSE`, que debe conservarse).
- Modelo DrumSep: aufr33 / jarredou. Motor: `audio-separator` (MIT).
- **JUCE** se usa bajo GPLv3 (o licencia comercial): si distribuís el plugin, debe cumplir la GPL.
