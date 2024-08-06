FROM python:3.11

RUN export DEBIAN_FRONTEND=noninteractive \
    && apt update \
    && apt upgrade -y \
    && apt install -y python3-pip \
    && apt install -y ca-certificates curl

ARG FOLDERNAME=redfish_exporter

RUN mkdir /${FOLDERNAME}
RUN mkdir /${FOLDERNAME}/collectors

WORKDIR /${FOLDERNAME}

RUN pip3 install --upgrade pip
COPY requirements.txt /${FOLDERNAME}
RUN pip3 install --no-cache-dir -r requirements.txt

COPY *.py /${FOLDERNAME}/
COPY collectors/ /${FOLDERNAME}/collectors/
COPY config.yml /${FOLDERNAME}/

LABEL source_repository="https://github.com/nathanlcarlson/redfish-exporter"
LABEL maintainer="Nathan Carlson"

ENTRYPOINT ["/usr/local/bin/python3", "/redfish_exporter/main.py", "-c", "/redfish_exporter/config.yml"]
