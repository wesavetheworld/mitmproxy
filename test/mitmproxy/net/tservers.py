import threading
import queue
import io
import OpenSSL

from mitmproxy.net import tcp
from mitmproxy.test import tutils


class _ServerThread(threading.Thread):

    def __init__(self, server):
        self.server = server
        threading.Thread.__init__(self)

    def run(self):
        self.server.serve_forever()


class _TServer(tcp.TCPServer):

    def __init__(self, ssl, q, handler_klass, addr, **kwargs):
        """
            ssl: A dictionary of SSL parameters:

                    cert, key, request_client_cert, cipher_list,
                    dhparams, v3_only
        """
        tcp.TCPServer.__init__(self, addr)

        if ssl is True:
            self.ssl = dict()
        elif isinstance(ssl, dict):
            self.ssl = ssl
        else:
            self.ssl = None

        self.q = q
        self.handler_klass = handler_klass
        if self.handler_klass is not None:
            self.handler_klass.kwargs = kwargs
        self.last_handler = None

    def handle_client_connection(self, request, client_address):
        h = self.handler_klass(request, client_address, self)
        self.last_handler = h
        if self.ssl is not None:
            cert = self.ssl.get(
                "cert",
                tutils.test_data.path("mitmproxy/net/data/server.crt"))
            raw_key = self.ssl.get(
                "key",
                tutils.test_data.path("mitmproxy/net/data/server.key"))
            with open(raw_key) as f:
                raw_key = f.read()
            key = OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM, raw_key)
            if self.ssl.get("v3_only", False):
                method = OpenSSL.SSL.SSLv3_METHOD
                options = OpenSSL.SSL.OP_NO_SSLv2 | OpenSSL.SSL.OP_NO_TLSv1
            else:
                method = OpenSSL.SSL.SSLv23_METHOD
                options = None
            h.convert_to_ssl(
                cert,
                key,
                method=method,
                options=options,
                handle_sni=getattr(h, "handle_sni", None),
                request_client_cert=self.ssl.get("request_client_cert", None),
                cipher_list=self.ssl.get("cipher_list", None),
                dhparams=self.ssl.get("dhparams", None),
                chain_file=self.ssl.get("chain_file", None),
                alpn_select=self.ssl.get("alpn_select", None)
            )
        h.handle()
        h.finish()

    def handle_error(self, connection, client_address, fp=None):
        s = io.StringIO()
        tcp.TCPServer.handle_error(self, connection, client_address, s)
        self.q.put(s.getvalue())


class ServerTestBase:
    ssl = None
    handler = None
    addr = ("127.0.0.1", 0)

    @classmethod
    def setup_class(cls, **kwargs):
        cls.q = queue.Queue()
        s = cls.makeserver(**kwargs)
        cls.port = s.address[1]
        cls.server = _ServerThread(s)
        cls.server.start()

    @classmethod
    def makeserver(cls, **kwargs):
        ssl = kwargs.pop('ssl', cls.ssl)
        return _TServer(ssl, cls.q, cls.handler, cls.addr, **kwargs)

    @classmethod
    def teardown_class(cls):
        cls.server.server.shutdown()

    def teardown(self):
        self.server.server.wait_for_silence()

    @property
    def last_handler(self):
        return self.server.server.last_handler
