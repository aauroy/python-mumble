import argparse
import asyncio
import threading
import logging
import ssl

import mumble

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument('--username', required=True,
                        help='username to connect with')
arg_parser.add_argument('--password', help='password to connect with')
arg_parser.add_argument('--port', type=int, help='port to connect to',
                        default=64738)
arg_parser.add_argument('host', help='host to connect to')


if __name__ == '__main__':
    args = arg_parser.parse_args()

    loop = asyncio.get_event_loop()

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    logging.basicConfig(level=logging.DEBUG)
    c = mumble.Client()

    def do(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, c.loop).result()

    def run_console():
        locals = {'self': c, 'do': do}

        try:
            from IPython.terminal import embed
        except ImportError:
            import code
            interact = lambda: code.interact(local=locals)
        else:
            from IPython.core import magic

            @magic.magics_class
            class AsyncMagics(magic.Magics):
                @magic.line_magic
                def await(self, line):
                    return do(eval(line, self.shell.user_global_ns,
                                   self.shell.user_ns))

            shell = embed.InteractiveShellEmbed(user_ns=locals)
            shell.register_magics(AsyncMagics)
            interact = shell

        interact()
        c.loop.call_soon_threadsafe(c.loop.stop)

    loop.run_until_complete(
        c.connect(args.host, args.port, args.username, args.password, ssl_ctx))

    threading.Thread(target=run_console).start()

    loop.run_forever()
