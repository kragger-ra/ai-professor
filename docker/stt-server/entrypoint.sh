#!/bin/bash

CUDA_ENABLED=${CUDA_ENABLED:-true}
DEVICE=""

if [ "${CUDA_ENABLED}" != "true" ]; then
    DEVICE="--device cpu"
fi
echo "hello world, DEVICE: ${DEVICE}"
exec python tools/run_webui.py ${DEVICE} --compile

# python /app/stt-server/stt_run.py
