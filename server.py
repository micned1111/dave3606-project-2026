import json
import html
import psycopg
import gzip
import io
from flask import Flask, Response, request, make_response
from time import perf_counter

app = Flask(__name__)

DB_CONFIG = {
    "host": "localhost",
    "port": 9876,
    "dbname": "lego-db",
    "user": "lego",
    "password": "bricks",
}


@app.route("/")
def index():
    template = ""
    with open("templates/index.html") as f:
        template = f.read()
    return Response(template)


@app.route("/sets")
def sets():
    requested_encoding = request.args.get("encoding")
    print(f"User's requested encoding: {requested_encoding}")

    if requested_encoding is None or (requested_encoding != "utf-8" and requested_encoding != "utf-16"):
        requested_encoding = "utf-8"
    else:
        requested_encoding = requested_encoding.lower()

    template = ""
    with open("templates/sets.html") as f:
        template = f.read()

    rows = []

    start_time = perf_counter()
    conn = psycopg.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("select id, name from lego_set order by id")
            for row in cur.fetchall():
                html_safe_id = html.escape(row[0])
                html_safe_name = html.escape(row[1])
                rows.append(f'<tr><td><a href="/set?id={html_safe_id}">{html_safe_id}</a></td><td>{html_safe_name}</td></tr>\n')
        print(f"Time to render all sets: {perf_counter() - start_time}")
    finally:
        conn.close()

    page_html = template.replace("{ROWS}", "".join(rows))
    
    compressed_content = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed_content, mode="wb") as fgz:
        if requested_encoding == "utf-8":
            page_html = page_html.replace("{METATAG}", '<meta charset="UTF-8">')
            fgz.write(page_html.encode("utf-8"))
        else:
            page_html = page_html.replace("{METATAG}", "")
            fgz.write(page_html.encode("utf-16"))
    
    gzipped_bytes = compressed_content.getvalue()

    response = make_response(gzipped_bytes)
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = len(gzipped_bytes)
    response.headers["Content-Type"] = f"text/html; charset={requested_encoding}"

    return response

@app.route("/set")
def legoSet():  # We don't want to call the function `set`, since that would hide the `set` data type.
    template = "" 
    with open("templates/set.html") as f:
        template = f.read()
    return Response(template)


@app.route("/api/set")
def apiSet():
    set_id = request.args.get("id")
    result = {"set_id": set_id}
    json_result = json.dumps(result, indent=4)
    return Response(json_result, content_type="application/json")


if __name__ == "__main__":
    app.run(port=5000, debug=True)

# Note: If you define new routes, they have to go above the call to `app.run`.
