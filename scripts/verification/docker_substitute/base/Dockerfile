# LOCAL SUBSTITUTE for python:3.12-slim. NOT an official image. Used only for verification where registries are unreachable.
FROM local-substitute/ubuntu-noble-minbase:test
LABEL substitute="true" substitutes="python:3.12-slim" built-from="debootstrap noble (archive.ubuntu.com)" official="false"
COPY sources.list /etc/apt/sources.list
# Optional: if your network re-signs HTTPS with its own CA, put that CA (PEM, *.crt) into extra-ca/ before building. Empty is fine.
COPY extra-ca/ /usr/local/share/ca-certificates/
RUN update-ca-certificates
# Ubuntu differences that the official python image does not have (absorbed here so backend/Dockerfile stays unchanged):
ENV PIP_BREAK_SYSTEM_PACKAGES=1 PIP_CERT=/etc/ssl/certs/ca-certificates.crt REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
RUN ln -s /usr/bin/python3 /usr/local/bin/python
