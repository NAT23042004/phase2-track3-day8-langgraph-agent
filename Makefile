.PHONY: install test lint typecheck run-scenarios grade-local export-graph demo-extensions streamlit-ui clean

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

install:
	$(PYTHON) -m pip install -e '.[dev,sqlite]'

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check src tests

typecheck:
	$(PYTHON) -m mypy src

run-scenarios:
	$(PYTHON) -m langgraph_agent_lab.cli run-scenarios --config configs/lab.yaml --output outputs/metrics.json

grade-local:
	$(PYTHON) -m langgraph_agent_lab.cli validate-metrics --metrics outputs/metrics.json

export-graph:
	$(PYTHON) -m langgraph_agent_lab.cli export-graph --output outputs/extensions/graph.mmd

demo-extensions:
	$(PYTHON) -m langgraph_agent_lab.cli demo-sqlite --database outputs/extensions/checkpoints.db --output outputs/extensions/sqlite_evidence.json
	$(PYTHON) -m langgraph_agent_lab.cli demo-time-travel --database outputs/extensions/time_travel.db --output outputs/extensions/time_travel_evidence.json
	$(PYTHON) -m langgraph_agent_lab.cli demo-hitl --database outputs/extensions/hitl.db --output outputs/extensions/hitl_evidence.json
	$(PYTHON) -m langgraph_agent_lab.cli demo-crash-resume --database outputs/extensions/crash_resume.db --output outputs/extensions/crash_resume_evidence.json

streamlit-ui:
	$(PYTHON) -m streamlit run src/langgraph_agent_lab/ui_streamlit.py --server.port 8501

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov dist build *.egg-info outputs/*.json
