FROM python:3.12-slim

RUN pip install --no-cache-dir "caproto>=1.3"

WORKDIR /sim
COPY simulator.py .

CMD ["python", "-u", "simulator.py"]
