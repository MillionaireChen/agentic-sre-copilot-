ENV := /var/tmp/fls/sre
PY  := $(ENV)/venv/bin/python

.PHONY: up down status test ingest eval vllm

up:
	bash scripts/stack.sh start

down:
	bash scripts/stack.sh stop

status:
	bash scripts/stack.sh status

test:
	$(PY) -m pytest tests/ -q

ingest:
	CUDA_VISIBLE_DEVICES=0 $(PY) -m backend.rag.ingest

eval:
	$(PY) -m eval.run_eval

vllm:
	bash scripts/stack.sh start vllm
