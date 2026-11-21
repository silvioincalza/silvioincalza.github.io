#!/usr/bin/env python3
"""Builds the portfolio site from content/site.json and the helper2.ai docs.

The docs are read from a helper2.ai checkout, either from the working tree or
from a git ref (--ref), so a local build can use origin/main without a checkout.

    python3 scripts/build.py --source ../helper2.ai --ref origin/main --out _site
"""
import argparse
import html
import json
import posixpath
import re
import shutil
import subprocess
import sys
from pathlib import Path

from markdown_it import MarkdownIt
from mdit_py_plugins.anchors import anchors_plugin

ROOT = Path(__file__).resolve().parent.parent
DECISIONS_DIR = "docs/architecture/decisions"
DIAGRAMS_DIR = "docs/architecture/diagrams"
HREF = re.compile(r'(href|src)="([^"]+)"')
# CommonMark with GitHub tables, raw HTML off: the same lists and nesting as GitHub shows.
MARKDOWN = (MarkdownIt("commonmark", {"html": False}).enable("table").enable("strikethrough")
            .use(anchors_plugin, min_level=2, max_level=4))
CSP = ("default-src 'none'; img-src 'self'; style-src 'self'; "
       "base-uri 'none'; form-action 'none'")


class Source:
    """Reads files of the helper2.ai repository, from a git ref or from disk."""

    def __init__(self, path: Path, ref: str | None):
        self.path = path
        self.ref = ref

    def read_bytes(self, rel: str) -> bytes:
        if self.ref:
            return subprocess.run(["git", "-C", str(self.path), "show", f"{self.ref}:{rel}"],
                                  check=True, capture_output=True).stdout
        return (self.path / rel).read_bytes()

    def read_text(self, rel: str) -> str:
        return self.read_bytes(rel).decode("utf-8")

    def list_dir(self, rel: str) -> list[str]:
        if self.ref:
            out = subprocess.run(["git", "-C", str(self.path), "ls-tree", "--name-only",
                                  f"{self.ref}:{rel}"], check=True, capture_output=True, text=True).stdout
            return out.split()
        return sorted(p.name for p in (self.path / rel).iterdir())


class Site:
    def __init__(self, config: dict, source: Source, out: Path):
        self.config = config
        self.source = source
        self.out = out
        self.blob = f"https://github.com/{config['source_repo']}/blob/{config['source_branch']}"
        self.adr_files = {name[4:8]: name for name in source.list_dir(DECISIONS_DIR)
                          if re.match(r"ADR-\d{4}-.+\.md$", name)}
        self.diagram_files = set(source.list_dir(DIAGRAMS_DIR))
        self.picks = {d["id"]: d for d in config["decisions"]}
        self.copied: set[str] = set()
        self.titles: dict[str, str] = {}
        self.errors: list[str] = []

    # --- helpers -----------------------------------------------------------

    def adr_page(self, adr_id: str) -> str:
        return self.adr_files[adr_id][4:-3] + ".html"  # "0031-guide-pipeline.html"

    def copy_diagram(self, name: str) -> str:
        if name not in self.diagram_files:
            self.errors.append(f"missing diagram {name}")
            return ""
        if name not in self.copied:
            target = self.out / "diagrams" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.source.read_bytes(f"{DIAGRAMS_DIR}/{name}"))
            self.copied.add(name)
        return name

    def rewrite_link(self, base_dir: str, url: str) -> str:
        """Keeps a link inside the site when the target is published here, else points to GitHub."""
        if re.match(r"^(https?:|mailto:|#)", url):
            return url
        path, _, anchor = url.partition("#")
        anchor = f"#{anchor}" if anchor else ""
        target = posixpath.normpath(posixpath.join(base_dir, path))
        name = posixpath.basename(target)
        if posixpath.dirname(target) == DECISIONS_DIR and name[4:8] in self.picks and name.startswith("ADR-"):
            return self.adr_page(name[4:8]) + anchor
        if (posixpath.dirname(target) == DIAGRAMS_DIR and name.endswith(".svg")
                and name not in self.config.get("diagrams_not_copied", [])):
            return "../diagrams/" + self.copy_diagram(name)
        return f"{self.blob}/{target}{anchor}"

    def render_markdown(self, text: str, base_dir: str) -> str:
        body = MARKDOWN.render(text)
        return HREF.sub(lambda m: f'{m.group(1)}="{html.escape(self.rewrite_link(base_dir, html.unescape(m.group(2))))}"',
                        body)

    def page(self, title: str, description: str, body: str, depth: int, path: str, up: str | None = None) -> str:
        up = "../" * depth if up is None else up
        p = self.config["person"]
        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<meta name="referrer" content="strict-origin-when-cross-origin">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description)}">
<link rel="canonical" href="{self.config['base_url']}/{path}">
<link rel="stylesheet" href="{up}assets/style.css">
<link rel="icon" href="{up}assets/favicon.svg" type="image/svg+xml">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="top"><div class="wrap">
<a class="brand" href="{up}index.html"><span class="tile" aria-hidden="true">SI</span>{html.escape(p['name'])}</a>
<nav aria-label="Main"><a href="{up}index.html#work">helper2.ai</a><a href="{up}index.html#decisions">Decisions</a><a href="{up}index.html#contact">Contact</a></nav>
</div></header>
<main id="main">
{body}
</main>
<footer class="wrap foot">
<p>© {html.escape(p['name'])}. Decision records and diagrams come from
<a href="https://github.com/{self.config['source_repo']}">{self.config['source_repo']}</a> (Apache-2.0) and are rebuilt from its main branch.</p>
<p>No cookies, no tracking, no scripts.</p>
</footer>
</body>
</html>
"""

    # --- pages -------------------------------------------------------------

    def build_decision(self, pick: dict) -> None:
        adr_id = pick["id"]
        if adr_id not in self.adr_files:
            self.errors.append(f"missing ADR {adr_id}")
            return
        rel = f"{DECISIONS_DIR}/{self.adr_files[adr_id]}"
        text = self.source.read_text(rel)
        first, _, rest = text.partition("\n")
        title = re.sub(r"^#\s*", "", first).strip()          # "0031 — Guide pipeline"
        name = title.split("—", 1)[-1].strip()
        self.titles[adr_id] = name
        diagram = self.copy_diagram(pick["diagram"])
        e = html.escape
        body = f"""<article class="wrap adr">
<p class="eyebrow"><a href="../index.html#decisions">Decisions</a> · {e(pick['group'])} · ADR {e(adr_id)}</p>
<h1>{e(name)}</h1>
<section class="summary" aria-label="Summary">
<div><h2>Problem</h2><p>{e(pick['problem'])}</p></div>
<div><h2>Decision</h2><p>{e(pick['decision'])}</p></div>
<div><h2>Why it matters</h2><p>{e(pick['why'])}</p></div>
</section>
<figure class="diagram"><a href="../diagrams/{e(diagram)}"><img src="../diagrams/{e(diagram)}" alt="Flowchart for ADR {e(adr_id)}: {e(name)}" loading="lazy"></a>
<figcaption>Flowchart. Open it full size for detail.</figcaption></figure>
<p class="source">The full record follows, as written in the repository. <a href="{self.blob}/{rel}">Read it on GitHub</a>.</p>
<div class="prose">
{self.render_markdown(rest, DECISIONS_DIR)}
</div>
</article>"""
        path = f"decisions/{self.adr_page(adr_id)}"
        self.write(path, self.page(f"{name} · ADR {adr_id} · {self.config['person']['name']}",
                                   pick["problem"], body, 1, path))

    def build_index(self) -> None:
        c, p, e = self.config, self.config["person"], html.escape
        cs = c["case_study"]
        about = "".join(f"<p>{e(t)}</p>" for t in p["about"])
        skills = "".join(f'<div class="card"><h3>{e(s["area"])}</h3><ul>'
                         + "".join(f"<li>{e(i)}</li>" for i in s["items"]) + "</ul></div>" for s in c["skills"])
        approach = "".join(f'<div class="card"><h3>{e(a["title"])}</h3><p>{e(a["text"])}</p></div>'
                           for a in cs["approach"])
        diagrams = "".join(
            f'<figure class="diagram"><a href="diagrams/{e(self.copy_diagram(d["file"]))}">'
            f'<img src="diagrams/{e(d["file"])}" alt="{e(d["title"])} diagram of helper2.ai" loading="lazy"></a>'
            f'<figcaption><strong>{e(d["title"])}.</strong> {e(d["text"])}</figcaption></figure>'
            for d in c["diagrams"])
        groups: dict[str, list[dict]] = {}
        for d in c["decisions"]:
            groups.setdefault(d["group"], []).append(d)
        decisions = ""
        for group, items in groups.items():
            cards = ""
            for d in items:
                if d["id"] not in self.adr_files:
                    continue
                name = self.titles[d["id"]]
                cards += (f'<a class="card link" href="decisions/{self.adr_page(d["id"])}">'
                          f'<span class="num">ADR {e(d["id"])}</span><h4>{e(name)}</h4>'
                          f'<p>{e(d["decision"])}</p></a>')
            decisions += f'<h3 class="group">{e(group)}</h3><div class="grid">{cards}</div>'
        links = [("GitHub", p["links"]["github"]), ("LinkedIn", p["links"]["linkedin"])]
        if p["links"]["email"]:
            links.append(("Email", "mailto:" + p["links"]["email"]))
        contact = "".join(f'<li><a href="{e(u)}">{e(n)}</a></li>' for n, u in links if u)
        total = len(self.adr_files)
        body = f"""<section class="hero"><div class="wrap">
<p class="eyebrow">{e(p['role'])} · {e(p['location'])}</p>
<h1>{e(p['headline'])}</h1>
<p class="lead">Backend, architecture and AI systems, with 15+ years in banking and fintech.</p>
<p class="cta"><a class="btn" href="#work">See the helper2.ai case study</a><a class="btn ghost" href="#contact">Contact</a></p>
</div></section>
<section class="wrap about" aria-labelledby="about-h"><h2 id="about-h">About</h2>{about}</section>
<section class="wrap" aria-labelledby="skills-h"><h2 id="skills-h">What I work with</h2><div class="grid">{skills}</div></section>
<section class="band" id="work" aria-labelledby="work-h"><div class="wrap">
<p class="eyebrow">Case study</p>
<h2 id="work-h">{e(cs['name'])}: {e(cs['tagline'])}</h2>
<p class="lead">{e(cs['problem'])}</p>
<p><a href="{e(cs['url'])}">{e(cs['url'])}</a> · <a href="https://github.com/{c['source_repo']}">source on GitHub</a></p>
<div class="grid two">{approach}</div>
<p class="stack"><strong>Stack.</strong> {e(cs['stack'])}</p>
<h3>Architecture</h3>
<div class="figures">{diagrams}</div>
</div></section>
<section class="wrap" id="decisions" aria-labelledby="dec-h">
<h2 id="dec-h">Selected decisions</h2>
<p class="lead">{len(c['decisions'])} of the {total} architecture decision records of helper2.ai. Each one has the context, the decision, the alternatives, the consequences and a flowchart.</p>
{decisions}
<p><a href="{self.blob}/{DECISIONS_DIR}/README.md">All {total} records on GitHub</a></p>
</section>
<section class="wrap" id="contact" aria-labelledby="contact-h"><h2 id="contact-h">Contact</h2>
<ul class="contact">{contact}</ul></section>"""
        self.write("index.html", self.page(f"{p['name']} · {p['role']}", p["headline"], body, 0, ""))

    def build_static(self) -> None:
        shutil.copytree(ROOT / "assets", self.out / "assets", dirs_exist_ok=True)
        (self.out / ".nojekyll").write_text("")
        body = '<section class="wrap hero"><h1>Page not found</h1><p><a href="/index.html">Back to the home page</a></p></section>'
        self.write("404.html", self.page(f"Not found · {self.config['person']['name']}", "Page not found", body, 0, "404.html", up="/"))
        urls = [""] + [f"decisions/{self.adr_page(d['id'])}" for d in self.config["decisions"] if d["id"] in self.adr_files]
        self.write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                   + "".join(f"<url><loc>{self.config['base_url']}/{u}</loc></url>\n" for u in urls) + "</urlset>\n")
        self.write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {self.config['base_url']}/sitemap.xml\n")

    def write(self, rel: str, content: str) -> None:
        target = self.out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def build(self) -> int:
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        for pick in self.config["decisions"]:
            self.build_decision(pick)
        self.build_index()
        self.build_static()
        for err in self.errors:
            print(f"error: {err}", file=sys.stderr)
        print(f"built {len(self.config['decisions'])} decisions, {len(self.copied)} diagrams into {self.out}")
        return 1 if self.errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, type=Path, help="path of a helper2.ai checkout")
    parser.add_argument("--ref", help="git ref to read the docs from (default: the working tree)")
    parser.add_argument("--out", default=ROOT / "_site", type=Path)
    args = parser.parse_args()
    config = json.loads((ROOT / "content/site.json").read_text(encoding="utf-8"))
    return Site(config, Source(args.source, args.ref), args.out).build()


if __name__ == "__main__":
    sys.exit(main())
