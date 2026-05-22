.PHONY: install demo test clean

install:
	pip install -e .[dev]

demo:
	mre demo --root .

test:
	pytest -q

clean:
	rm -rf artifacts/*.csv artifacts/*.json artifacts/*.md artifacts/*.joblib data/demo .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
