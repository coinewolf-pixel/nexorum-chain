#!/usr/bin/env python3
"""Add the "AYVIA network" button to the app's index.html (safe to run several times).

  python3 inject_link.py path/to/dist/index.html
"""
import sys

MARK = "<!-- ayvia-network-link -->"
SNIPPET = MARK + """
<a href="/network.html" id="ayvia-net-link" aria-label="Сеть AYVIA: кошелёк, перевод, стейкинг"
   style="position:fixed;right:20px;bottom:96px;z-index:80;display:flex;align-items:center;gap:8px;
          padding:10px 16px;border-radius:999px;text-decoration:none;font:600 14px Inter,system-ui,sans-serif;
          color:#fff;background:linear-gradient(135deg,#8b5cf6,#c026d3);box-shadow:0 6px 24px #8b5cf680">
  <span style="font-size:16px">⛓</span><span>Сеть AYVIA</span>
</a>
"""


def main(path):
    html = open(path, encoding="utf-8").read()
    if MARK in html:
        print("already patched:", path)
        return
    if "</body>" not in html:
        sys.exit("no </body> in " + path)
    open(path, "w", encoding="utf-8").write(html.replace("</body>", SNIPPET + "</body>", 1))
    print("patched:", path)


if __name__ == "__main__":
    main(sys.argv[1])
