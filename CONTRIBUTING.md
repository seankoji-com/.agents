# Contributing

Start with [the architecture](docs/architecture.md) and [contributor guide](docs/contributing.md).
Small fixes, stronger failure-path tests, and reproducible provider results are welcome.

Run the standard-library suite with `python3 scripts/run_tests.py` (parallel), or
`python3 -m unittest discover -s tests -v` (serial, same tests).
For documentation, install `requirements-docs.txt` in a virtual environment and run
`python3 scripts/check_docs.py` and `python3 -m mkdocs build --strict`.

Issue forms and the PR template are inherited from
[seankoji-com/.github](https://github.com/seankoji-com/.github). Include what failed,
the smallest reproduction, and how you verified the change. Do not publish private
transcripts, credentials, or personal configuration.
