from __future__ import annotations

import os

from flask import Flask, jsonify, render_template

from ttn_noc.service import NocService


def create_app() -> Flask:
    app = Flask(__name__)
    service = NocService()
    app.config["NOC_SERVICE"] = service

    @app.after_request
    def add_security_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "connect-src 'self'; "
            "img-src 'self' https://tile.openstreetmap.org; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "base-uri 'self'; object-src 'none'"
        )
        return response

    @app.get("/")
    def index():
        # The NOC can be mounted at the domain root during local development
        # or below a path such as /noc behind the existing website.
        base_path = os.getenv("NOC_BASE_PATH", "").strip().rstrip("/")
        return render_template("index.html", base_path=base_path)

    @app.get("/api/status")
    def status():
        return jsonify(service.status())

    @app.get("/api/gateways")
    def gateways():
        return jsonify(service.status()["gateways"])

    @app.get("/api/sensors")
    def sensors():
        return jsonify(service.status()["sensors"])

    @app.get("/api/health")
    def health():
        snapshot = service.status()
        return jsonify({"status": "degraded" if snapshot["error"] else "ok", "mode": snapshot["mode"], "error": snapshot["error"]})

    return app


app = create_app()


if __name__ == "__main__":
    settings = app.config["NOC_SERVICE"].settings
    app.run(host="0.0.0.0", port=settings.port, debug=os.getenv("NOC_DEBUG", "false").lower() == "true")
