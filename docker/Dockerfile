FROM fishaudio/fish-speech:latest-dev
#RUN pip3 install RealtimeSTT --no-cache-dir
# WORKDIR /app
WORKDIR /opt/fish-speech
COPY stt-server ./stt-server
RUN chmod +x ./stt-server/entrypoint.sh
ENV GRADIO_SERVER_NAME="0.0.0.0"
EXPOSE 7860
# CMD ["./entrypoint.sh"]
CMD ["./stt-server/entrypoint.sh"]

#CMD ["python", "tools/run_webui.py", "--compile"]