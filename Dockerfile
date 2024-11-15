FROM python:3.13.0-alpine3.20

RUN pip install --upgrade pip
ADD requirements.txt .
RUN pip install --requirement requirements.txt
ADD namespace-admission.py .
EXPOSE 8000
CMD [ "gunicorn", "-w4", "-b 0.0.0.0", "namespace-admission:app" ]
