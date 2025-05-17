# RPStrength Exporter

This script fetches and converts your RP Strength mesocycle training data into Obsidian-compatible Markdown files.

## Example usage

```bash
python rpstrength.py \
  --headers conf/headers.txt \
  --frontmatter conf/frontmatter.md \
  --muscle-groups conf/muscle_groups.json
```

If you don't provide `--index` or `--exercises`, they will be automatically retrieved from the API and cached locally as `mesocycles.json` and `exercises.json`. Markdown files will be saved to the `output/` directory.
