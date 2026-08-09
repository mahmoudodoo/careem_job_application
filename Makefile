# Convenience targets. Windows users: run the `python review.py ...` commands directly,
# or use `make` from Git Bash / WSL.

PY ?= python

.PHONY: help demo scan review pair snippet serve test live-review install clean

help:
	@echo "make demo     - run all three challenges offline -> out/"
	@echo "make scan     - deterministic static pass over samples/"
	@echo "make review   - Challenge 1 with the CI gate (offline)"
	@echo "make pair     - Challenge 2 (offline)"
	@echo "make snippet  - Challenge 3 (offline)"
	@echo "make serve    - web UI on http://127.0.0.1:8000"
	@echo "make test     - unit tests (offline, no key)"
	@echo "make live-review - Challenge 1 against a live model (needs LLM_API_KEY)"

demo:
	$(PY) review.py demo --mock

scan:
	$(PY) review.py scan samples

review:
	$(PY) review.py review samples --mock --gate

pair:
	$(PY) review.py pair samples/eta_service.go --mock

snippet:
	$(PY) review.py snippet samples/snippet.go --mock

serve:
	$(PY) review.py serve --mock

test:
	$(PY) -m unittest discover -s tests -t . -v

live-review:
	$(PY) review.py review samples --gate --effort high

install:
	$(PY) -m pip install -e ".[live]"

clean:
	rm -rf out .pytest_cache **/__pycache__
