"""Сборка мини-приложения в два файла для нестабильного туннеля.

Источники лежат в miniapp/src/. На выходе:
  miniapp/index.html  — разметка + встроенный минифицированный CSS
  miniapp/app.min.js  — минифицированный JS (с версией в ссылке)

Почему так: бесплатный туннель обрывает слишком большие ответы. Один
HTML со стилями и один небольшой JS дают два запроса вместо трёх и
оставляют запас по размеру на телефонах с медленной связью.

Запуск: .venv\\Scripts\\python tools\\build_miniapp.py
"""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

import rcssmin
import rjsmin

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "miniapp" / "src"
OUT = ROOT / "miniapp"

STYLE_TAG = '<link rel="stylesheet" href="styles.css">'
SCRIPT_TAG = '<script src="app.js" defer></script>'

LOADER = """<div class="load-error" id="loadError" hidden>
  <p>Не удалось загрузить приложение. Проверь связь и попробуй ещё раз.</p>
  <button type="button" onclick="location.reload()">Повторить</button>
</div>
<noscript><div class="noscript">Для работы TimeBalance нужен JavaScript. Включи его в браузере.</div></noscript>
<script src="app.min.js?v={version}" defer></script>
<script>
(function () {{
  "use strict";
  var tries = 0;
  function banner() {{
    var el = document.getElementById("loadError");
    if (el) el.hidden = false;
  }}
  function retry() {{
    if (window.__tbReady) return;
    if (tries >= 2) {{ banner(); return; }}
    tries += 1;
    var s = document.createElement("script");
    s.src = "app.min.js?v={version}&r=" + tries;
    s.onload = function () {{ if (!window.__tbReady) banner(); }};
    s.onerror = retry;
    document.body.appendChild(s);
  }}
  window.addEventListener("load", function () {{
    window.setTimeout(function () {{ if (!window.__tbReady) retry(); }}, 1500);
  }});
}})();
</script>"""


def gz(data: bytes) -> int:
    return len(gzip.compress(data, 9))


def main() -> None:
    # utf-8-sig: BOM в начале styles.css ломает первый селектор :root при встраивании
    html = (SRC / "index.html").read_text(encoding="utf-8-sig")
    css = rcssmin.cssmin((SRC / "styles.css").read_text(encoding="utf-8-sig"))
    js = rjsmin.jsmin((SRC / "app.js").read_text(encoding="utf-8-sig"))

    if "</style" in css.lower() or "</script" in js.lower():
        raise SystemExit("В исходниках найден закрывающий тег, встраивание небезопасно")

    version = hashlib.sha256(js.encode("utf-8")).hexdigest()[:10]

    if STYLE_TAG not in html or SCRIPT_TAG not in html:
        raise SystemExit("В src/index.html нет ожидаемых ссылок на styles.css/app.js")

    html = html.replace(STYLE_TAG, f"<style>{css}</style>", 1)
    html = html.replace(SCRIPT_TAG, LOADER.format(version=version), 1)

    (OUT / "app.min.js").write_text(js, encoding="utf-8")
    (OUT / "index.html").write_text(html, encoding="utf-8")

    html_b = html.encode("utf-8")
    js_b = js.encode("utf-8")
    css_b = css.encode("utf-8")

    print(f"index.html  {len(html_b):>6} b  gzip {gz(html_b):>5} b")
    print(f"app.min.js  {len(js_b):>6} b  gzip {gz(js_b):>5} b")
    print(f"css inline  {len(css_b):>6} b  gzip {gz(css_b):>5} b (внутри index.html)")
    print(f"версия      {version}")


if __name__ == "__main__":
    main()
