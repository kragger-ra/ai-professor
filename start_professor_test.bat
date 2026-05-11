@echo off
rem Test launch of AI Professor.
rem  --warmup   : Prof speaks demo phrases at startup so we can hear TTS pipeline.
rem  --no-stt   : disable microphone listener; interact via Gradio textbox instead.
rem Use Gradio at http://localhost:22228 to type student messages and toggle modes.

cd /d "%~dp0"
call start_professor.bat --warmup --no-stt
