FROM python:3.10.15-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt 

EXPOSE 22230

CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "22230", "--reload"] 

RUN mkdir -p data 