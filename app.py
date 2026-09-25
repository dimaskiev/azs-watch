"""WSGI entry for Vercel. Local launch still uses server.py via start.bat."""

from __future__ import annotations

from flask import Flask, jsonify, request, send_from_directory

import server as core

app = Flask(__name__)


@app.get("/api/state")
def api_state():
    return jsonify(core.public_state())


@app.get("/api/refresh")
def api_refresh():
    return jsonify(core.public_state(do_refresh=True))


def _discounts_local_only():
    return jsonify({"ok": False, "error": "Редактор знижок лише локально"}), 404


@app.get("/api/discounts")
def api_discounts_get():
    if core.is_hosted():
        return _discounts_local_only()
    return jsonify(core.discounts_editor())


@app.post("/api/discounts")
def api_discounts_save():
    if core.is_hosted():
        return _discounts_local_only()
    body = request.get_json(silent=True) or {}
    core.save_overrides(body.get("overrides") or {})
    return jsonify({"ok": True, "editor": core.discounts_editor(), "state": core.public_state(rebuild=True)})


@app.post("/api/discounts/reset")
def api_discounts_reset():
    if core.is_hosted():
        return _discounts_local_only()
    core.save_json(core.OVERRIDES, {"updated": core.now_iso(), "overrides": {}})
    return jsonify({"ok": True, "editor": core.discounts_editor(), "state": core.public_state(rebuild=True)})


@app.get("/")
def home():
    return send_from_directory(core.WEB, "index.html")


@app.get("/<path:filename>")
def static_file(filename: str):
    return send_from_directory(core.WEB, filename)
