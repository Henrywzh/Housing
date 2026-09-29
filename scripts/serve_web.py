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
                      ".geojson": "application/json; charset=utf-8",
                      ".pmtiles": "application/octet-stream",
                      ".pbf": "application/x-protobuf"}

    def end_headers(self):
        # The page and its payload are rebuilt constantly; a cached data file
        # against a new page is a version mismatch that looks like a bug.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *a):
        pass


class Server(socketserver.ThreadingTCPServer):
    # The page asks for six files at once, one of them 14.7MB; a single-threaded
    # server makes that look like a slow page rather than a slow server.
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    with Server(("", port), functools.partial(Handler, directory=str(ROOT))) as s:
        print(f"serving {ROOT} on http://localhost:{port}", flush=True)
        s.serve_forever()
