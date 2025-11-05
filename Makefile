# Virtual environment settings
PYTHON = python3.11

VENV = venv
VENV_ACTIVATE = $(VENV)/bin/activate

# IssueFS specific settings
MOUNTPOINT ?= /tmp/jira

.PHONY: help venv install clean build all version setup run mount umount

## Create virtual environment
venv:
	@if [ -n "$$VIRTUAL_ENV" ]; then \
		if [ "$$VIRTUAL_ENV" = "$(shell pwd)/$(VENV)" ]; then \
			echo "Project virtual environment is already active."; \
		else \
			echo "ERROR: Another virtual environment is active: $$VIRTUAL_ENV"; \
			echo "Please deactivate it first or use 'deactivate' command."; \
			echo "Expected: $(shell pwd)/$(VENV)"; \
			exit 1; \
		fi; \
	elif [ ! -d "$(VENV)" ]; then \
		echo "Creating virtual environment..."; \
		$(PYTHON) -m venv $(VENV); \
		echo "Virtual environment created successfully!"; \
	else \
		echo "Virtual environment exists but not active."; \
	fi

	@echo "Ensuring pip is up to date..."; 
	@. $(VENV_ACTIVATE) && pip install --upgrade pip > /dev/null

## Show this help message
help:  
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Development Targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ''
	@echo 'IssueFS Targets:'
	@echo '  setup          Complete IssueFS setup (install deps)'
	@echo '  run            Run the filesystem (MOUNTPOINT=/tmp/jira)'
	@echo '  mount          Alias for run'
	@echo '  umount         Unmount the filesystem'
	@echo ''
	@echo 'Examples:'
	@echo '  make setup                    # First time setup'
	@echo '  make run                      # Mount at /tmp/jira'
	@echo '  make run MOUNTPOINT=/mnt/jira # Mount at custom location'

## Install the package in development mode
install: venv  
	. $(VENV_ACTIVATE) && pip install -q --upgrade pip
	. $(VENV_ACTIVATE) && pip install -q -r requirements.txt
	@echo "✓ Dependencies installed"

## Clean build artifacts and virtual environment
clean:  
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	rm -rf $(VENV)/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

## Build source and wheel distributions
build: install  
	. $(VENV_ACTIVATE) && python -m build

## Run full pipeline: clean, build
all: clean build  

version: venv
	@. $(VENV_ACTIVATE) && python --version

## === IssueFS specific targets ===

## Complete setup for IssueFS
setup: install
	@echo ""
	@echo "=== IssueFS Setup Complete ==="
	@echo ""
	@echo "Make sure you have a .env file with:"
	@echo "  - JIRA_API_TOKEN (your JIRA API token)"
	@echo "  - JIRA_URL (your JIRA instance URL)"
	@echo ""

## Run the IssueFS filesystem
run: install
	@if [ ! -d "$(MOUNTPOINT)" ]; then \
		echo "Creating mount point: $(MOUNTPOINT)"; \
		mkdir -p "$(MOUNTPOINT)"; \
	fi
	@echo ""
	@echo "=== Starting IssueFS ==="
	@echo "Mount point: $(MOUNTPOINT)"
	@echo ""
	@echo "Usage instructions:"
	@echo "  1. In another terminal, create a folder:"
	@echo "     mkdir $(MOUNTPOINT)/my_query"
	@echo ""
	@echo "  2. Edit the configuration:"
	@echo "     nano $(MOUNTPOINT)/my_query/config.yaml"
	@echo ""
	@echo "  3. Set 'enabled: true' and add your JQL query, e.g.:"
	@echo "     enabled: true"
	@echo "     jira:"
	@echo "       - jql: 'project = MYPROJECT AND type = Bug'"
	@echo ""
	@echo "  4. List issues:"
	@echo "     ls $(MOUNTPOINT)/my_query/"
	@echo ""
	@echo "  5. Read an issue:"
	@echo "     cat $(MOUNTPOINT)/my_query/ISSUE-123.txt"
	@echo ""
	@echo "Press Ctrl+C to stop the filesystem"
	@echo ""
	@. $(VENV_ACTIVATE) && python issuefs.py "$(MOUNTPOINT)"

## Alias for run
mount: run

## Unmount the filesystem
umount:
	@echo "Unmounting filesystem from $(MOUNTPOINT)..."
	@if mountpoint -q "$(MOUNTPOINT)" 2>/dev/null; then \
		fusermount -u "$(MOUNTPOINT)" && echo "✓ Filesystem unmounted"; \
	else \
		echo "Filesystem is not mounted at $(MOUNTPOINT)"; \
	fi
