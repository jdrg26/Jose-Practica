
#!/usr/bin/env python3
"""Migración de entradas Markdown (Hugo) a SQLite de Chyrp Lite."""

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

from index import split_front_matter, parse_meta

SQL_DATETIME_ZERO = "1000-01-01 00:00:00"

# --- funciones puras --------------------------------------------------------

def slugify(texto):
    """'Árbol B' -> 'arbol-b'."""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sin_tildes.lower()).strip("-")

def fecha_chyrp(valor, por_defecto):
    """Convierte una fecha de Hugo al formato de Chyrp Lite."""
    m = re.match(
        r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2})(?::(\d{2}))?)?",
        str(valor)
    )
    if not m:
        return por_defecto

    dia, hora_min, seg = m.groups()
    return f"{dia} {hora_min or '00:00'}:{seg or '00'}"

def etiquetas_json(nombres):
    """Convierte las etiquetas al formato JSON de Tagginator."""
    if not nombres:
        return "[]"

    asociacion = {}

    for nombre in nombres:
        nombre = str(nombre)

        if nombre.isnumeric():
            clave = "\ufe0e" + nombre
            slug = hashlib.md5(clave.encode()).hexdigest()
        else:
            clave = nombre
            slug = slugify(nombre)

        asociacion[clave] = slug

    return json.dumps(
        asociacion,
        separators=(",", ":")
    ).replace("/", "\\/")

def leer_entrada(path):
    """Lee una entrada Markdown y conserva su contenido original."""
    front, cuerpo = split_front_matter(
        path.read_text(encoding="utf-8")
    )

    meta = parse_meta(front)
    tags = meta.get("tags", [])

    return {
        "slug": path.stem,
        "titulo": meta.get("title", path.stem),
        "cuerpo": cuerpo.strip(),
        "fecha": str(meta.get("date", "")),
        "tags": tags if isinstance(tags, list) else [tags],
        "draft": meta.get("draft", False) is True,
    }

def transformar(entrada, user_id, ahora):
    """Transforma una entrada Hugo en datos para Chyrp Lite."""
    slug = slugify(entrada["slug"])

    return {
        "post": {
            "feather": "text",
            "clean": slug,
            "url": slug,
            "pinned": 0,
            "status": "draft" if entrada["draft"] else "public",
            "user_id": user_id,
            "created_at": fecha_chyrp(entrada["fecha"], ahora),
            "updated_at": SQL_DATETIME_ZERO,
        },
        "attrs": {
            "title": entrada["titulo"],
            "body": entrada["cuerpo"],
            "tags": etiquetas_json(entrada["tags"]),
        },
    }

# --- efectos: disco y SQL ---------------------------------------------------

def extraer(origen):
    """Extrae las entradas Markdown del proyecto Hugo."""
    ficheros = (
        p for p in sorted(Path(origen).rglob("*.md"))
        if p.name != "_index.md"
    )

    return [leer_entrada(p) for p in ficheros]

def comprobar_destino(destino):
    """Comprueba que el destino sea una BD de Chyrp Lite."""
    if not Path(destino).is_file():
        sys.exit(
            f"migrar.py: no existe {destino} "
            "(instala Chyrp Lite antes)"
        )

    con = sqlite3.connect(destino)

    try:
        tablas = {
            fila[0]
            for fila in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        con.close()

    if not {"posts", "post_attributes", "users"} <= tablas:
        sys.exit(
            f"migrar.py: {destino} no parece "
            "una base de datos de Chyrp Lite"
        )

def buscar_autor(con, login):
    """Obtiene el ID del autor en Chyrp Lite."""
    if login:
        sql = "SELECT id FROM users WHERE login = ?"
        params = (login,)
    else:
        sql = "SELECT MIN(id) FROM users"
        params = ()

    fila = con.execute(sql, params).fetchone()

    if fila is None or fila[0] is None:
        sys.exit(
            "migrar.py: no encuentro ese autor en la tabla users"
        )

    return fila[0]

def existe(con, url):
    """Comprueba si una publicación ya fue migrada."""
    return con.execute(
        "SELECT 1 FROM posts WHERE url = ?",
        (url,)
    ).fetchone() is not None

def insertar(con, fila):
    """Inserta la publicación y sus atributos."""
    columnas = list(fila["post"])

    cur = con.execute(
        f"INSERT INTO posts({', '.join(columnas)}) "
        f"VALUES ({', '.join('?' * len(columnas))})",
        [fila["post"][c] for c in columnas]
    )

    post_id = cur.lastrowid

    con.executemany(
        "INSERT INTO post_attributes(post_id, name, value) "
        "VALUES (?, ?, ?)",
        [
            (post_id, nombre, valor)
            for nombre, valor in fila["attrs"].items()
        ]
    )

    return post_id

def cargar(destino, filas, simulacro=False):
    """Inserta lo que falta dentro de una sola transacción."""
    con = sqlite3.connect(destino)

    try:
        with con:
            resultado = []

            for fila in filas:
                url = fila["post"]["url"]

                if existe(con, url):
                    resultado.append(("omitida", url))
                    continue

                if not simulacro:
                    insertar(con, fila)

                estado = "simulada" if simulacro else "creada"
                resultado.append((estado, url))

            return resultado

    finally:
        con.close()

def main():
    ap = argparse.ArgumentParser(
        description="Markdown (P1.1) -> SQLite de Chyrp Lite"
    )

    ap.add_argument(
        "--origen",
        default="content/posts",
        help="carpeta con los archivos Markdown"
    )

    ap.add_argument(
        "--destino",
        required=True,
        help="fichero SQLite de Chyrp Lite (una copia)"
    )

    ap.add_argument(
        "--autor",
        help="login del autor en Chyrp Lite"
    )

    ap.add_argument(
        "--simulacro",
        action="store_true",
        help="muestra qué haría, sin escribir"
    )

    args = ap.parse_args()

    comprobar_destino(args.destino)

    entradas = extraer(args.origen)
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    con = sqlite3.connect(args.destino)

    try:
        user_id = buscar_autor(con, args.autor)
    finally:
        con.close()

    filas = [
        transformar(entrada, user_id, ahora)
        for entrada in entradas
    ]

    resultado = cargar(
        args.destino,
        filas,
        args.simulacro
    )

    for estado, url in resultado:
        print(f"{estado:9} {url}")

    nuevas = sum(
        1 for estado, _ in resultado
        if estado != "omitida"
    )

    print(
        f"migrar: {len(entradas)} entradas leídas, "
        f"{nuevas} nuevas, "
        f"{len(entradas) - nuevas} ya estaban"
    )

if __name__ == "__main__":
    main()
