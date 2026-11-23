# LOCAL SUBSTITUTE for nginx:1.27-alpine (Ubuntu nginx 1.24). NOT an official image.
FROM local-substitute/python-ubuntu:3.12.3
LABEL substitute="true" substitutes="nginx:1.27-alpine" official="false"
RUN apt-get update && apt-get install -y --no-install-recommends nginx-light gettext-base \
 && rm -rf /var/lib/apt/lists/* /etc/nginx/sites-enabled/default /etc/nginx/conf.d/*
COPY entrypoint.sh /usr/local/bin/substitute-entrypoint.sh
RUN chmod +x /usr/local/bin/substitute-entrypoint.sh
EXPOSE 80 443
ENTRYPOINT ["/usr/local/bin/substitute-entrypoint.sh"]
