# notes fixture

A tiny JSON notes service for the verification-init test. Start it with
`python3 app.py --port 8765 --data /tmp/notes-data`, then `GET /health`,
`POST /notes` with `{"text": "..."}` and `GET /notes`.
