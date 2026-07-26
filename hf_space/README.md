---
title: EmotionOS Inference
colorFrom: red
colorTo: gray
sdk: gradio
sdk_version: 6.8.0
python_version: "3.10"
app_file: app.py
pinned: false
short_description: Persona-directed emotional voice inference
license: mit
models:
  - ResembleAI/chatterbox
---

# EmotionOS Inference

This Space is the GPU inference service for EmotionOS. It uses Chatterbox
Multilingual V3 for English and Hindi speech, optional consented reference-voice
matching, and Persona-derived emotion controls.

## API

Every Gradio Space exposes its functions as an API. EmotionOS calls the
`/generate` endpoint through `gradio_client`.

The base model downloads inside the Space at build/runtime. Model weights are
not committed to this repository and do not need to be downloaded to the
EmotionOS web server.

## ZeroGPU

After creating the Space, select **ZeroGPU** in the Space hardware settings.
GPU work is restricted to the function decorated with `@spaces.GPU`.

Generated audio contains Chatterbox's PerTh watermark. Only use reference voices
that you own or have permission to use.
