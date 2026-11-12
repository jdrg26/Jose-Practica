#!/usr/bin/env python3
"""tools/index.py — content/**/*.md → SQLite (solo en build) → JSON estático.

Filosofía Unix: hace UNA cosa. Lee Markdown, rellena build/site.db y la
consulta con SQL para exportar dos ficheros:

  static/search.json  → lo consume static/search.js en el navegador
  data/tags.json      → lo consume Hugo en layouts/index.html

La base de datos NO se despliega: public/ contiene solo ficheros estáticos.

Solo biblioteca estándar (sqlite3, json, re, pathlib). Estilo funcional:
funciones puras para parsear; los efectos (disco, SQL) quedan al final.

Límites (a propósito, KISS): front matter YAML con pares `clave: valor` y
listas en línea `tags: [a, b]`. Nada de TOML (+++) ni listas multilínea.

Docs: https://docs.python.org/3/library/sqlite3.html
      https://www.sqlite.org/json1.html
"""
import json
import re
import sqlite3
import sys
from functools import reduce
from pathlib import Path

CONTENT = Path("content")
DB = Path("build/site.db")
OUT_SEARCH = Path("static/search.json")
OUT_TAGS = Path("data/tags.json")

SCHEMA = """
CREATE TABLE posts (
  url     TEXT PRIMARY KEY,
  title   TEXT NOT NULL,
  date    TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  body    TEXT NOT NULL DEFAULT ''
);
CREATE TABLE tags (
  url TEXT NOT NULL REFERENCES posts(url),
  tag TEXT NOT NULL,
  PRIMARY KEY (url, tag)
);
"""

# SQL produce directamente el JSON (extensión json1 de SQLite).
Q_SEARCH = """
SELECT json_group_array(json_object(
  'url', url, 'title', title, 'date', date, 'summary', summary,
  'tags', json(tags), 'text', body))
FROM (
  SELECT p.*,
         (SELECT json_group_array(tag) FROM tags t WHERE t.url = p.url) AS tags
  FROM posts p
  ORDER BY date DESC, title
)
"""

# Agregación: cuántas páginas hay por etiqueta.
Q_TAGS = """
SELECT json_group_array(json_object('tag', tag, 'total', total))
FROM (
  SELECT tag, COUNT(*) AS total FROM tags GROUP BY tag ORDER BY total DESC, tag
)
"""

# --- funciones puras ---------------------------------------------------------

def split_front_matter(text):
    """'---\\nclave: valor\\n---\\ncuerpo' → (bloque_yaml, cuerpo)."""
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", text, re.S)
    return (m.group(1), m.group(2)) if m else ("", text)


def parse_scalar(raw):
    v = raw.strip()
    if v.startswith("[") and v.endswith("]"):
        return [parse_scalar(x) for x in v[1:-1].split(",") if x.strip()]
    if v in ("true", "false"):
        return v == "true"
    return re.sub(r"^(['\"])(.*)\1$", r"\2", v)  # quita comillas simétricas


def parse_meta(block):
    pairs = (line.split(":", 1) for line in block.splitlines()
             if ":" in line and not line.lstrip().startswith("#"))
    return {k.strip(): parse_scalar(v) for k, v in pairs}


# (patrón, reemplazo) aplicados en orden: Markdown → texto plano
CLEANERS = [
    (r"```.*?```", " "),                              # bloques de código
    (r"`([^`]*)`", r"\1"),                            # código en línea
    (r"!?\[([^\]]*)\]\([^)]*\)", r"\1"),              # enlaces/imágenes → texto
    (r"^[ \t]{0,3}(?:#{1,6}|>|[-*+]|\d+\.)[ \t]+", ""),  # marcas de bloque
    (r"\*{1,3}", ""),                                 # énfasis
    (r"\s+", " "),                                    # espacios
]


def plain(markdown):
    step = lambda s, pr: re.sub(pr[0], pr[1], s, flags=re.S | re.M)
    return reduce(step, CLEANERS, markdown).strip()


def shorten(text, n=160):
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


def url_of(path):
    """content/posts/x.md → /posts/x/  (como hace Hugo)."""
    parts = path.relative_to(CONTENT).with_suffix("").parts
    parts = parts[:-1] if parts[-1] == "index" else parts
    return "/" + "/".join(parts) + "/"


def read_page(path):
    front, body = split_front_matter(path.read_text(encoding="utf-8"))
    meta = parse_meta(front)
    text = plain(body)
    tags = meta.get("tags", [])
    return {
        "url": url_of(path),
        "title": meta.get("title", path.stem),
        "date": str(meta.get("date", "")),
        "summary": meta.get("description") or shorten(text),
        "tags": tags if isinstance(tags, list) else [tags],
        "draft": meta.get("draft", False) is True,
        "text": text,
    }


def read_all():
    files = (p for p in sorted(CONTENT.rglob("*.md")) if p.name != "_index.md")
    return [page for page in map(read_page, files) if not page["draft"]]


# --- efectos: disco y SQL ----------------------------------------------------

def build_db(pages):
    DB.parent.mkdir(parents=True, exist_ok=True)
    DB.unlink(missing_ok=True)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO posts(url, title, date, summary, body)"
        " VALUES (:url, :title, :date, :summary, :text)", pages)
    con.executemany(
        "INSERT OR IGNORE INTO tags(url, tag) VALUES (?, ?)",
        [(p["url"], t) for p in pages for t in p["tags"]])
    con.commit()
    return con


def export(con, query, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(con.execute(query).fetchone()[0] + "\n", encoding="utf-8")


def main():
    if not CONTENT.is_dir():
        sys.exit("index.py: ejecútalo desde la raíz del repo (make index)")
    pages = read_all()
    con = build_db(pages)
    export(con, Q_SEARCH, OUT_SEARCH)
    export(con, Q_TAGS, OUT_TAGS)
    con.close()
    print(f"index: {len(pages)} páginas → {OUT_SEARCH}, {OUT_TAGS}")


if __name__ == "__main__":
    main()
