FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bench ./bench
COPY banding ./banding
EXPOSE 8000
# Two workers: the service is stateless and holds no database connections, so
# there is nothing to coordinate. The sample market is regenerated per request
# from a fixed seed, which keeps workers agreeing without shared state.
CMD ["gunicorn","banding.wsgi:application","--bind","0.0.0.0:8000","--workers","2","--timeout","30"]
