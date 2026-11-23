# Troubleshooting

- **Application refuses to start because SECRET_KEY is weak/missing:** run `python -m app.cli init-env` from `backend` if no `.env` exists; if one exists, replace the value with a newly generated secret using `python -m app.cli gen-secret`. Do not paste secrets into chat.
- **Database revision is behind:** stop the app, back up the database, then run `python -m app.cli migrate` from `backend`.
- **Port 8000 is occupied:** stop the other local service or change the port in `start.bat` and update the Android API URL accordingly.
- **Admin login fails:** confirm that an administrator account was created. If an account is locked, an admin can unlock it using `python -m app.cli unlock-user <username>`; password reset is `python -m app.cli reset-password <username>`.
- **PDF upload rejected:** ensure it is a real PDF, smaller than 25 MiB, and uploaded with an admin/staff account.
- **PDF has no register candidates:** it may be image-only; install the optional OCR dependencies and Tesseract, then use the OCR endpoint. OCR output still needs manual review.
- **OCR fails:** check that the Tesseract executable and requested language packs are installed and available on PATH.
- **Hall allocation rejected:** confirm the hall is verified, the seat inventory contains the requested active seat, and capacity has not been reached.
- **Android cannot connect:** use `10.0.2.2` for the emulator; a physical device needs a reachable LAN host address, same network and firewall permission. The server defaults to loopback and is not exposed to LAN.
- **Windows scripts cannot find Python:** install Python 3.12+ with the Python launcher enabled, then rerun `install.bat`.

For security reasons, do not disable authentication, rate limits, file checks or database constraints to work around errors.
