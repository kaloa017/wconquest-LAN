"""Check the local game and optional tunnel without exposing their listeners."""
import argparse
import json
import os
from urllib.request import Request, urlopen


def check(host, port=5055, tunnel=False):
    request = Request(f'http://127.0.0.1:{port}/api/bootstrap', headers={'Host':host})
    with urlopen(request, timeout=15) as response:
        result = json.load(response)
    if not isinstance(result, dict) or not result.get('version') or not result.get('csrf'):
        raise RuntimeError('The local server did not return game configuration')
    if tunnel:
        with urlopen('http://127.0.0.1:20241/ready', timeout=5) as response:
            if response.status != 200:
                raise RuntimeError('Tunnel has no active edge connection')
    return result['version']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default=os.getenv('PUBLIC_HOST','localhost'))
    parser.add_argument('--port', type=int, default=int(os.getenv('PORT','5055')))
    parser.add_argument('--tunnel', action='store_true')
    args = parser.parse_args()
    try:
        version = check(args.host, args.port, args.tunnel)
    except Exception as error:
        parser.exit(1, f'Health check failed: {error}\n')
    print(f'Game {version} is responding'+('; tunnel connected' if args.tunnel else ''))


if __name__ == '__main__':
    main()
