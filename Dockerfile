ARG ROASTDESK_RUNTIME_IMAGE=python:3.12-slim
FROM ${ROASTDESK_RUNTIME_IMAGE}
USER root
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOST=0.0.0.0 PORT=8000 ROASTDESK_DATA=/var/lib/roastdesk
WORKDIR /opt/roastdesk
COPY requirements.txt scripts/check_dependencies.py ./
RUN (python check_dependencies.py || python -m pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: -r requirements.txt) \
    && python check_dependencies.py && python -m pip check
COPY roastdesk ./roastdesk
COPY image_lab ./image_lab
COPY static ./static
COPY templates ./templates
RUN useradd -U -u 11545 survey && install -d -o survey -g survey /var/lib/roastdesk
USER survey
EXPOSE 8000
CMD ["python", "-m", "roastdesk"]
