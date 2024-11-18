FROM python:3.13.0-alpine3.20

RUN pip install --upgrade pip
ADD requirements.txt .
RUN pip install --requirement requirements.txt
ADD *.py .
EXPOSE 443

ENTRYPOINT [ "gunicorn", "-w4", \
    "--certfile=/certs/tls.crt", \
    "--keyfile=/certs/tls.key", \
    "--ca-certs=/certs/ca.crt",\
    "--bind=0.0.0.0:443", "--access-logfile=/dev/stdout"]
CMD [ "namespace-admission:operator" ]
