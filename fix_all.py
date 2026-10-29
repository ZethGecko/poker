with open('server/app.py', 'r') as f:
    content = f.read()

# Replace the handle_static_request function completely
import re

# Find and replace the entire handle_static_request function
old_function_pattern = r'def handle_static_request\(environ, start_response\):\n    path = environ\.get\("PATH_INFO", ""\)\n\n    if path == "/":\n        path = "/index.html"\n    elif path\.startswith\(\"/js/\"\):\n            pass\n    elif path\.startswith\(\"/js/\"\):\n        pass\n    else:\n        return error_response\(start_response, 404, f"File not found: \{path\}"\)\n\n    static_path = os\.join\(PUBLIC_DIR, path\.lstrip\("\/"\)\)\n\n    try:\n        with open\(static_path, "rb"\) as f:\n            content = f\.read\(\)\n            content_type = "text/html"\n            if path\.endswith\("\.css"\):\n                content_type = "text/css"\n            elif path\.endswith\("\.js"\):\n                content_type = "application/javascript"\n\n            start_response\("200 OK", \["Content-Type", content_type\]\)\n            return \[content\]\n    except FileNotFoundError:\n        return error_response\(start_response, 404, f"File not found: \{path\}"\)'

new_function = '''def handle_static_request(environ, start_response):
    path = environ.get("PATH_INFO", "")

    if path == "/":
        path = "/index.html"
    elif path.startswith("/js/"):
        pass

    static_path = os.join(PUBLIC_DIR, path.lstrip("/"))

    try:
        with open(static_path, "rb") as f:
            content = f.read()
            content_type = "text/html"
            if path.endswith(".css"):
                content_type = "text/css"
            elif path.endswith(".js"):
                content_type = "application/javascript"

            start_response("200 OK", [("Content-Type", content_type)])
            return [content]
    except FileNotFoundError:
        return error_response(start_response, 404, f"File not found: {path}")
'''

content = re.sub(old_function_pattern, new_function, content, flags=re.MULTILINE)

# Also fix the first handle_static function in the Handler class
old_handler_pattern = r'def handle_static\(self, path\):\n        if path == "/":\n            path = "/index.html"\n        elif path == "/style\.css":\n            path = "/styles\.css"\n        elif path\.startswith\(\"/js/\"\):\n            pass\n        else:\n            self\.send_error\(404, "Archivo no encontrado"\)\n            return\n\n        static_path = os\.join\(PUBLIC_DIR, path\.lstrip\("\/"\)\)\n\n        try:\n            with open\(static_path, "rb"\) as f:\n                content_type = self\.guess_type\(path\)\n                self\.send_response\(200\)\n                self\.send_header\(\"Content-Type\", content_type\)\n                self\.end_headers\(\)\n                self\.wfile\.write\(f\.read\(\)\)\n        except FileNotFoundError:\n            self\.send_error\(404, f"Archivo no encontrado: \{path\}"\)'

new_handler = '''def handle_static(self, path):
        if path == "/":
            path = "/index.html"
        elif path.startswith("/js/"):
            pass

        static_path = os.join(PUBLIC_DIR, path.lstrip("/"))

        try:
            with open(static_path, "rb") as f:
                content_type = self.guess_type(path)
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(f.read())
        except FileNotFoundError:
            self.send_error(404, f"Archivo no encontrado: {path}")
'''

content = re.sub(old_handler_pattern, new_handler, content, flags=re.MULTILINE)

# Fix the third handle_static function in the second Handler class
# First, find the pattern
old_handler2_pattern = r'(def handle_static\(self, path\):\n        if path == "/":\n            path = "/index.html"\n        elif path == "/style\.css":\n            path = "/styles\.css"\n        elif path\.startswith\(\"/js/\"\):\n            pass\n        else:\n            self\.send_error\(404, "Archivo no encontrado"\)\n            return\n\n        static_path = os\.join\(PUBLIC_DIR, path\.lstrip\("\/"\)\)\n\n        try:\n            with open\(static_path, "rb"\) as f:\n                content_type = self\.guess_type\(path\)\n                self\.send_response\(200\)\n                self\.send_header\(\"Content-Type\", content_type\)\n                self\.end_headers\(\)\n                self\.wfile\.write\(f\.read\(\)\)\n        except FileNotFoundError:\n            self\.send_error\(404, f"Archivo no encontrado: \{path\}"\))'

new_handler2 = '''def handle_static(self, path):
        if path == "/":
            path = "/index.html"
        elif path.startswith("/js/"):
            pass

        static_path = os.join(PUBLIC_DIR, path.lstrip("/"))

        try:
            with open(static_path, "rb") as f:
                content_type = self.guess_type(path)
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(f.read())
        except FileNotFoundError:
            self.send_error(404, f"Archivo no encontrado: {path}")
'''

content = re.sub(old_handler2_pattern, new_handler2, content, flags=re.MULTILINE)

with open('server/app.py', 'w') as f:
    f.write(content)

print('Fixed all handle_static functions with comprehensive replacement')