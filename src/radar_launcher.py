"""Start the project radar on its own loopback port and verify the homepage."""
import argparse
import socket
from threading import Event, Thread
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import webbrowser

import uvicorn


def reserve_port():
    for port in range(8011, 8021):
        listener = socket.socket()
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", port))
            return listener
        except OSError:
            listener.close()
    raise OSError("No free local port from 8011 to 8020.")


def open_when_ready(url, finished, launch_browser):
    opener = build_opener(ProxyHandler({}))
    for _ in range(40):
        if finished.wait(0.25):
            return
        try:
            with opener.open(url, timeout=1) as response:
                body = response.read()
                if b'id="view-radar"' not in body or b'id="view-news"' not in body:
                    continue
        except (URLError, OSError):
            continue
        print(f"Project Radar is ready: {url}", flush=True)
        if launch_browser:
            try:
                webbrowser.open(url)
            except (webbrowser.Error, OSError):
                print("Open the URL above in Edge or Chrome.", flush=True)
        return
    print(f"Could not verify the Project Radar homepage. Check the server log: {url}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-browser", action="store_true", help="Print the verified URL without opening a browser.")
    args = parser.parse_args()
    with reserve_port() as listener:
        port = listener.getsockname()[1]
        url = f"http://127.0.0.1:{port}/"
        finished = Event()
        server = uvicorn.Server(uvicorn.Config("src.matching.api:app", host="127.0.0.1", port=port))
        Thread(target=open_when_ready, args=(url, finished, not args.no_browser), daemon=True).start()
        try:
            server.run(sockets=[listener])
        finally:
            finished.set()
        if not server.started:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
