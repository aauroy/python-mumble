import argparse
import asyncio
import logging
import ssl

import mumble

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument('--username', required=True,
                        help='username to connect with')
arg_parser.add_argument('--password', required=True,
                        help='password to connect with')
arg_parser.add_argument('host', help='host to connect to')
arg_parser.add_argument('port', type=int, help='port to connect to')


if __name__ == '__main__':
    args = arg_parser.parse_args()

    loop = asyncio.get_event_loop()

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    logging.basicConfig(level=logging.DEBUG)
    c = mumble.Client()
    loop.run_until_complete(
        c.connect(args.host, args.port, args.username, args.password, ssl_ctx))
    loop.run_forever()
