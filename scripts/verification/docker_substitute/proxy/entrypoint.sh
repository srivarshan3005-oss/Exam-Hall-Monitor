#!/bin/bash
set -e
: "${DOMAIN_NAME:?DOMAIN_NAME is required}"
envsubst '$DOMAIN_NAME' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf
# DECLARED TEST-ONLY DEVIATION: nginx 1.24 does not know "http2 on;" (needs >= 1.25.1). The pinned production image is 1.27.
sed -i 's/^\([[:space:]]*\)http2 on;/\1# http2 on;  (disabled in the nginx<1.25.1 substitute)/' /etc/nginx/conf.d/default.conf
exec nginx -g 'daemon off;'
