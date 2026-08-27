FROM python:3.12-slim

RUN pip install --no-cache-dir "fastapi>=0.110" "uvicorn[standard]>=0.29"

WORKDIR /sim
COPY app.py .

EXPOSE 8090

CMD ["python", "-u", "app.py"]
