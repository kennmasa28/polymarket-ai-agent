"""Start the web app:  python -m webapp [--host 127.0.0.1] [--port 8000]"""

from __future__ import annotations

import argparse
import atexit

from . import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="PolyAgent web app")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--debug", action="store_true", help="Flask debug mode (development only)")
    args = parser.parse_args()

    app = create_app()
    # Write session_end and cancel unapproved orders when the server stops.
    atexit.register(app.extensions["agent_service"].close_all)
    print(f"PolyAgent: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
