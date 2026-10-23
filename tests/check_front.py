"""Comprobaciones estáticas del front: ids, imports/exports y clases CSS.

Uso: python3 tests/check_front.py
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUB = os.path.join(ROOT, "public")

errors: list[str] = []


def read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


html = read(os.path.join(PUB, "index.html"))
css = read(os.path.join(PUB, "styles.css"))
js_files = {
    "app.js": read(os.path.join(PUB, "js", "app.js")),
    "net.js": read(os.path.join(PUB, "js", "net.js")),
    "cards.js": read(os.path.join(PUB, "js", "cards.js")),
    "table.js": read(os.path.join(PUB, "js", "table.js")),
}

# 1. ids del HTML
html_ids = set(re.findall(r'id="([^"]+)"', html))

# 2. ids que usa el JS
used_ids = set()
for name, code in js_files.items():
    used_ids |= set(re.findall(r'\$\("([^"]+)"\)', code))
    used_ids |= set(re.findall(r'getElementById\("([^"]+)"\)', code))
DYNAMIC_IDS = {"turnClock"}  # ids que crea el propio JS en caliente
for missing in sorted(used_ids - html_ids - DYNAMIC_IDS):
    errors.append(f"el JS usa el id #{missing} pero no existe en index.html")

# 3. ids del HTML que nunca se usan (aviso, no error)
unused = html_ids - used_ids
for extra in sorted(unused):
    print(f"  (aviso) el id #{extra} no se usa desde el JS")

# 4. imports / exports
exports = {}
for name, code in js_files.items():
    exports[name] = set(re.findall(r"export\s+(?:async\s+)?(?:function|const|class|let)\s+(\w+)", code))
    exports[name] |= set(re.findall(r"export\s*\{([^}]*)\}", code) and
                         [x.strip() for x in re.findall(r"export\s*\{([^}]*)\}", code)[0].split(",")])

for name, code in js_files.items():
    for symbols, modname in re.findall(r'import\s*\{([^}]*)\}\s*from\s*"\./(\w+\.js)"', code):
        for sym in [s.strip() for s in symbols.split(",") if s.strip()]:
            if modname not in exports:
                errors.append(f"{name} importa de {modname}, que no existe")
            elif sym not in exports[modname]:
                errors.append(f"{name} importa '{sym}' de {modname}, que no lo exporta")

# 5. clases usadas en el JS que no existen en el CSS
css_classes = set(re.findall(r"\.([a-zA-Z][\w-]*)", css))
for name, code in js_files.items():
    for cls in re.findall(r'className\s*=\s*`([^`$]+)`', code) + re.findall(r'class="([^"]+)"', code):
        for c in re.split(r"[\s${}]+", cls):
            c = c.strip()
            if not c or "$" in c:
                continue
            if c not in css_classes and not c.startswith("is-"):
                errors.append(f"clase CSS no definida: .{c} (usada en {name})")

# 6. funciones Referential en app.js
for fn in re.findall(r"function\s+(\w+)\s*\(", js_files["app.js"]):
    if not re.search(rf"\b{fn}\s*\(", js_files["app.js"]):
        errors.append(f"función sin usar en app.js: {fn}")

if errors:
    print("\n  ERRORES:")
    for e in errors:
        print("   -", e)
    sys.exit(1)
print("  Front OK: ids, imports/exports y clases CSS consistentes")
