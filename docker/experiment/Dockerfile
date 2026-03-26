FROM docker.io/fishaudio/fish-speech:latest-dev
RUN pip3 install RealtimeSTT --no-cache-dir
COPY services services
ENTRYPOINT ["bash", "./services/entrypoint.sh"]