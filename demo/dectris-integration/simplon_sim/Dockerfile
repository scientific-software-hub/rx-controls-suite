FROM python:3.12-slim

RUN pip install --no-cache-dir "fastapi>=0.110" "uvicorn[standard]>=0.29" "pyzmq>=26" "cbor2>=5.6"

WORKDIR /sim
COPY state.py app.py .

EXPOSE 8080 31001

CMD ["python", "-u", "app.py"]
