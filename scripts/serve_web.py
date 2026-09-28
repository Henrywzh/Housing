"""Static server for local preview of web/.

Python's http.server serves .html with no charset, so a browser falls back to
Latin-1 and every Chinese character comes out as mojibake. The published
artifact is wrapped with a charset meta and does not have this problem; this
only exists so local checking shows what the reader will see.
"""
import functools, http.server, pathlib, socketserver, sys

ROOT = pathlib.Path(__file__).resolve().parents[1] / "web"


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".html": "text/html; charset=utf-8",
                      ".json": "application/json; charset=utf-8",
                      ".geojson": "application/json; charset=utf-8"}

    def log_message(self, fmt, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), functools.partial(Handler, directory=str(ROOT))) as s:
        print(f"serving {ROOT} on http://localhost:{port}", flush=True)
        s.serve_forever()
