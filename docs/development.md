# Development

```bash
pip install -e ".[dev]"
pytest                  # run the unit tests
pytest --cov            # with coverage
```

The test suite covers config validation, the tile registry, the composer
(layouts, palette resolution, sample terrain build), the velocity map
(sample coverage, goal-directed vectors, tile-mode direction), and a smoke
test that compiles a generated terrain through MuJoCo end-to-end.
