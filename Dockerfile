FROM --platform=$BUILDPLATFORM python:3.11-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --target=/deps -r requirements.txt

FROM gcr.io/distroless/python3-debian12:nonroot

COPY --from=builder /deps /app/deps
COPY *.py /app/

WORKDIR /app

ENV PYTHONPATH=/app/deps

EXPOSE 443

ENTRYPOINT ["python3", "-m", "gunicorn", "-w4", \
    "--certfile=/certs/tls.crt", \
    "--keyfile=/certs/tls.key", \
    "--ca-certs=/certs/ca.crt", \
    "--bind=0.0.0.0:443", "--access-logfile=/dev/stdout"]
CMD ["namespace-admission:operator"]
