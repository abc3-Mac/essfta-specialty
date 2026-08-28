FROM python:3.12-slim-bookworm

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

ENV SPECIALTY_DB=/data/specialty.db
VOLUME /data
EXPOSE 8792

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8792"]
