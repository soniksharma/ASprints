"""AccessSprint launcher."""

import argparse

from accesssprint.config import DEFAULT_HOST, DEFAULT_PORT


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local AccessSprint audit workspace.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Local bind address (default: loopback only).")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Local web port.")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "::1", "localhost"}:
        parser.error("AccessSprint only binds to a loopback address.")
    from accesssprint.server import create_server

    server = create_server(host=args.host, port=args.port)
    print(f"AccessSprint is ready at http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping AccessSprint…")
    finally:
        server.close_application()
        server.server_close()


if __name__ == "__main__":
    main()
