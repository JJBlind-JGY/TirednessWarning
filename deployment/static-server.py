import argparse
import http.server
import mimetypes
import os
import posixpath
import shutil
import socketserver
import urllib.error
import urllib.parse
import urllib.request


def build_handler(web_root, face_target, api_target, eeg_target):
    web_root = os.path.abspath(web_root)

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_GET(self):
            self.route()

        def do_POST(self):
            self.route()

        def do_PUT(self):
            self.route()

        def do_DELETE(self):
            self.route()

        def do_OPTIONS(self):
            self.route()

        def route(self):
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            if path.startswith("/face-api/"):
                self.proxy(face_target, self.path.replace("/face-api", "", 1))
            elif path.startswith("/api/"):
                self.proxy(api_target, self.path.replace("/api", "", 1))
            elif path.startswith("/eeg/"):
                self.proxy(eeg_target, self.path)
            elif path.startswith("/wss"):
                self.proxy(face_target, self.path)
            else:
                self.serve_static(path)

        def serve_static(self, request_path):
            normalized = posixpath.normpath(urllib.parse.unquote(request_path)).lstrip("/")
            if not normalized or normalized == ".":
                normalized = "index.html"
            full_path = os.path.abspath(os.path.join(web_root, normalized))
            if not full_path.startswith(web_root):
                self.send_error(403)
                return
            if not os.path.isfile(full_path):
                full_path = os.path.join(web_root, "index.html")
            if not os.path.isfile(full_path):
                self.send_error(404, "index.html not found")
                return

            content_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"
            with open(full_path, "rb") as file:
                data = file.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)

        def proxy(self, target_base, target_path):
            self.close_connection = True
            target_url = target_base.rstrip("/") + target_path
            body = None
            length = self.headers.get("Content-Length")
            if length:
                body = self.rfile.read(int(length))

            headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in {"host", "connection", "content-length", "transfer-encoding"}
            }
            request = urllib.request.Request(target_url, data=body, headers=headers, method=self.command)
            try:
                with urllib.request.urlopen(request, timeout=600) as response:
                    self.send_response(response.status)
                    for key, value in response.headers.items():
                        if key.lower() in {"connection", "transfer-encoding"}:
                            continue
                        self.send_header(key, value)
                    self.send_header("Connection", "close")
                    self.end_headers()
                    if target_path.startswith("/eeg/stream"):
                        self.stream_sse(response)
                    else:
                        shutil.copyfileobj(response, self.wfile)
            except urllib.error.HTTPError as error:
                self.send_response(error.code)
                for key, value in error.headers.items():
                    if key.lower() in {"connection", "transfer-encoding"}:
                        continue
                    self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()
                shutil.copyfileobj(error, self.wfile)
            except Exception as error:
                message = f"Proxy target unavailable: {target_url}\n{error}".encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(message)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(message)

        def stream_sse(self, response):
            while True:
                line = response.readline()
                if not line:
                    break
                self.wfile.write(line)
                self.wfile.flush()

        def log_message(self, fmt, *args):
            print("%s - %s" % (self.address_string(), fmt % args))

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--web-root", required=True)
    parser.add_argument("--face-target", default="http://127.0.0.1:8081")
    parser.add_argument("--api-target", default="http://127.0.0.1:8081")
    parser.add_argument("--eeg-target", default="http://127.0.0.1:5000")
    args = parser.parse_args()

    handler = build_handler(args.web_root, args.face_target, args.api_target, args.eeg_target)
    with socketserver.ThreadingTCPServer(("127.0.0.1", args.port), handler) as server:
        server.allow_reuse_address = True
        print(f"Front server listening on http://127.0.0.1:{args.port}/")
        server.serve_forever()


if __name__ == "__main__":
    main()
