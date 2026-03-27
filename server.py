import json
import html
import psycopg
import gzip
import io
import struct
from flask import Flask, Response, request, make_response
from time import perf_counter

from colors import colors

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
    response.cache_control.max_age = 60 # seconds
    response.cache_control.public = True

    return response


class Node:
    def __init__(self, id, data):
        self.id = id
        self.data = data  # stores json_result
        self.next = None  
        self.prev = None

head = None
tail = None


CURRENT_SETS = 0
MAX_SETS = 3
set_cache = {} # {setId: Node}

def addToCache(id, result):
    global CURRENT_SETS
    global set_cache
    global head
    global tail

    if CURRENT_SETS < MAX_SETS:
        CURRENT_SETS += 1
    else:
        print(f"Eviction policy removing set id: {tail.id}")
        set_cache.pop(tail.id)
        new_tail = tail.next
        tail.next.prev = None
        tail.next = None
        tail = new_tail
    

    node = Node(id, result)
    if tail == None:
        head = node
        tail = node
    else:
        head.next = node
        node.prev = head 
        head = node

    set_cache[id] = node # store in cache


def updateCache(id):
    global head
    global tail

    node = set_cache[id]

    if head == node:
        return
    elif tail == node:
        tail = node.next
        node.next.prev = None
        node.next = None
        head.next = node
        node.prev = head
        head = node
    else:
        node.prev.next = node.next
        node.next.prev = node.prev
        node.next = None
        head.next = node
        node.prev = head
        head = node


@app.route("/set")
def legoSet():  # We don't want to call the function `set`, since that would hide the `set` data type.
    template = "" 
    with open("templates/set.html") as f:
        template = f.read()
    return Response(template)


@app.route("/api/set")
def apiSet():
    start_time = perf_counter()
    set_id = request.args.get("id")

    if set_id in set_cache:
        updateCache(set_id)
        json_result = set_cache[set_id].data
        end_time = perf_counter() - start_time
        print(f"LEGO set with id: {set_id} was retrieved from cache, time to retrieve: {end_time * 1000} ms")
        return Response(json_result, content_type="application/json")

    name, bricks = load_set_data(set_id)

    res = {
        "set_id": set_id,
        "set_name": name,
        "bricks_data": bricks,
    }

    json_result = json.dumps(res, indent=4)
    addToCache(set_id, json_result) # check if available space and add to cache
    end_time = perf_counter() - start_time
    print(f"LEGO set with id: {set_id} was retrieved from database: {end_time * 1000} ms")

    return Response(json_result, content_type="application/json")


def load_set_data(set_id):
    name = ""
    bricks = []

    conn = psycopg.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM lego_set WHERE id = %s", (set_id,))
            name = html.escape(cur.fetchone()[0])

            cur.execute("SELECT brick_type_id, color_id, count FROM lego_inventory WHERE set_id = %s", (set_id,))
            for row in cur.fetchall():
                brick_id = html.escape(row[0])
                color_id = html.escape(str(row[1]))
                brick_count = html.escape(str(row[2]))

                cur.execute("SELECT name, preview_image_url FROM lego_brick WHERE brick_type_id = %s AND color_id = %s", (brick_id, color_id))
                name_and_img = cur.fetchone()
                brick_name = html.escape(name_and_img[0])
                brick_img_url = html.escape(name_and_img[1])

                bricks.append({
                    "img_url": brick_img_url,
                    "name": brick_name,
                    "color": colors.get(int(color_id), f"Color {color_id}"),
                    "count": brick_count
                })
    finally:
        conn.close()

    return name, bricks




def write(f, id, name, bricks):
    f.write(b"LEGOSET")
    f.write(struct.pack("B", 1))

    encoded_id = id.encode("utf-8")
    encoded_id_length = len(encoded_id)
    encoded_name = name.encode("utf-8")
    encoded_name_length = len(encoded_name)

    f.write(struct.pack(">H", encoded_id_length))
    f.write(encoded_id)
    f.write(struct.pack(">H", encoded_name_length))
    f.write(encoded_name)
    f.write(struct.pack(">I", len(bricks)))

    for brick in bricks:
        encoded_img_url = brick["img_url"].encode("utf-8")
        encoded_img_url_length = len(encoded_img_url)

        encoded_brick_name = brick["name"].encode("utf-8")
        encoded_brick_name_length = len(encoded_brick_name)

        encoded_color = brick["color"].encode("utf-8")
        encoded_color_length = len(encoded_color)

        f.write(struct.pack(">H", encoded_img_url_length))
        f.write(encoded_img_url)

        f.write(struct.pack(">H", encoded_brick_name_length))
        f.write(encoded_brick_name)

        f.write(struct.pack(">H", encoded_color_length))
        f.write(encoded_color)

        f.write(struct.pack(">H", int(brick["count"])))
        

def read(f):
    magic = f.read(7)
    if magic != b"LEGOSET":
        raise ValueError("Invalid file format")

    version = struct.unpack("B", f.read(1))[0]
    if version != 1:
        raise ValueError(f"Unsupported format version: {version}")

    encoded_id_length = struct.unpack(">H", f.read(2))[0]
    encoded_id = f.read(encoded_id_length)
    id = encoded_id.decode("utf-8")

    encoded_name_length = struct.unpack(">H", f.read(2))[0]
    encoded_name = f.read(encoded_name_length)
    name = encoded_name.decode("utf-8")

    print(f"set_id: {id}")
    print(f"set_name: {name}")

    brick_records = struct.unpack(">I", f.read(4))[0]

    for _ in range(brick_records):
        encoded_img_url_length = struct.unpack(">H", f.read(2))[0]
        encoded_img_url = f.read(encoded_img_url_length)
        img_url = encoded_img_url.decode("utf-8")

        encoded_brick_name_length = struct.unpack(">H", f.read(2))[0]
        encoded_brick_name = f.read(encoded_brick_name_length)
        brick_name = encoded_brick_name.decode("utf-8")

        encoded_color_length = struct.unpack(">H", f.read(2))[0]
        encoded_color = f.read(encoded_color_length)
        color = encoded_color.decode("utf-8")

        count = struct.unpack(">H", f.read(2))[0]

        print(f"Brick with img_url: {img_url}, brick_name: {brick_name}, color: {color}, count: {count}")


@app.route("/api/write/set")
def apiBinWriteSet():
    set_id = request.args.get("id")
    if not set_id:
        return Response("Missing id query parameter", status=400)

    name, bricks = load_set_data(set_id)

    buffer = io.BytesIO()
    write(buffer, set_id, name, bricks)
    binary_payload = buffer.getvalue()
    return Response(binary_payload, content_type="application/octet-stream")


if __name__ == "__main__":
    app.run(port=5002, debug=True)

# Note: If you define new routes, they have to go above the call to `app.run`.
