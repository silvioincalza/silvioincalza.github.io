# silvioincalza.github.io

My portfolio site: https://silvioincalza.github.io

It shows who I am, what I work with, and helper2.ai as a case study. The decision pages are built from the
architecture decision records of [helper2.ai](https://github.com/silvioincalza/helper2.ai): a short summary I write,
the flowchart, then the full record as it is in that repository.

## How it works

- `content/site.json` holds everything I write by hand: profile, skills, experience, the case study, the chosen
  diagrams and the chosen decisions with their summaries.
- `scripts/build.py` reads `site.json` and the helper2.ai docs and writes a static site to `_site/`. No JavaScript,
  no cookies, no external fonts.
  Markdown is rendered as CommonMark with GitHub tables, so lists and nesting look as they do on GitHub. Raw HTML in
  the records is not rendered.
- A link to a decision or diagram that is published here stays on this site. Every other link goes to the file on
  GitHub. Diagrams listed in `diagrams_not_copied` are never copied.
- `.github/workflows/pages.yml` builds on every pull request, and deploys to GitHub Pages on `main` and once a day,
  so a change to a published record in helper2.ai shows up the next morning.

## Build locally

Prerequisites: Python 3.10 or newer, a helper2.ai checkout next to this one.

```bash
pip install -r requirements.txt
python3 scripts/build.py --source ../helper2.ai --ref origin/main --out _site
python3 -m http.server -d _site 8000     # http://localhost:8000
```

Without `--ref` the build reads the working tree of the checkout.

The build fails when a chosen decision or diagram no longer exists in helper2.ai.

## Add or change a decision

Add an entry to `decisions` in `content/site.json`: the ADR number, a group, the flowchart file name, and three short
sentences (problem, decision, why it matters). Build locally and check the page.

## Licence

My text in this repository is mine, all rights reserved. The decision records and diagrams come from helper2.ai under
Apache-2.0.
