FROM python:3.12-slim
WORKDIR /srv/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py index.html explore.html app.js home.js style.css ./
ENV DATA_DIR=/data
EXPOSE 8000
RUN useradd --system appuser
USER appuser
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]
