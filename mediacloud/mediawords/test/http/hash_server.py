import base64
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
import multiprocessing
import os
import signal
from socketserver import ForkingMixIn
import tempfile
from typing import Union, Dict
from urllib.parse import urlparse, parse_qs

from mediawords.util.log import create_logger
from mediawords.util.network import tcp_port_is_open, wait_for_tcp_port_to_open, wait_for_tcp_port_to_close
from mediawords.util.perl import decode_object_from_bytes_if_needed


class McHashServerException(Exception):
    """HashServer exception."""
    pass


log = create_logger(__name__)


class HashServer(object):
    """Simple HTTP server that just serves a set of pages defined by a simple dictionary.

    It is intended to make it easy to startup a simple server seeded with programmer defined content."""

    # Default HTTP status code for redirects ("301 Moved Permanently")
    _DEFAULT_REDIRECT_STATUS_CODE = HTTPStatus.MOVED_PERMANENTLY

    __host = '127.0.0.1'
    __port = 0
    __pages = {}

    __http_server = None
    __http_server_thread = None

    class Request(object):
        """Request sent to callback."""

        def __init__(self, port: int, method: str, path: str, headers: Dict[str, str], content: str):
            self._port = port
            self._method = method
            self._path = path
            self._headers = headers
            self._content = content

        def method(self) -> str:
            """Return method (GET, POST, ...) of a request."""
            return self._method

        def url(self) -> str:
            """Return full URL of the request."""
            return 'http://localhost:%(port)d%(path)s' % {
                'port': self._port,
                'path': self._path,
            }

        def headers(self) -> Dict[str, str]:
            """Return all headers."""
            return self._headers

        def header(self, name: str) -> Union[str, None]:
            """Return header of a request."""

            name = decode_object_from_bytes_if_needed(name)

            if name in self._headers:
                return self._headers[name]
            else:
                return None

        def content_type(self) -> str:
            """Return Content-Type of a request."""
            return self.header('Content-Type')

        def content(self) -> Union[str, None]:
            """Return POST content of a request."""
            return self._content

        def cookies(self) -> Dict[str, str]:
            """Return cookie dictionary of a request."""
            cookies = {}
            for header_name in self._headers:
                header_value = self._headers[header_name]
                if header_name.lower() == 'cookie':
                    cookie_name, cookie_value = header_value.split('=', 1)
                    cookies[cookie_name] = cookie_value
            return cookies

        def query_params(self) -> Dict[str, str]:
            """Return URL query parameters of a request."""
            params = parse_qs(urlparse(self._path).query, keep_blank_values=True)
            for param_name in params:
                if isinstance(params[param_name], list) and len(params[param_name]) == 1:
                    # If parameter is present only once, return it as a string
                    params[param_name] = params[param_name][0]
            return params

    class _ForkingHTTPServer(ForkingMixIn, HTTPServer):

        # Set to underlying TCPServer
        allow_reuse_address = True

        # Some tests (e.g. feed scrape test) request many pages at pretty much the same time, so with the default queue
        # size some of those requests might time out
        request_queue_size = 64

        def __init__(self, server_address, request_handler_class, shutdown_canary_file: str):
            """Initialize HTTP server.

            Shutdown canary file is a temporary file that, when removed, will inform a forked HTTP server to kill all of
            its children and stop processing requests. A gruesome temporary file is used because timeouts don't work
            with long running callbacks.
            """
            if shutdown_canary_file is None:
                raise McHashServerException('Shutdown canary file is not set.')
            open(shutdown_canary_file, 'a').close()
            self.__shutdown_canary_file = shutdown_canary_file

            super().__init__(server_address, request_handler_class)

        def __set_shutdown(self):
            """Remove shutdown canary file."""
            if self.__shutdown_canary_file is None:
                raise McHashServerException('Shutdown canary file is not set.')
            if os.path.exists(self.__shutdown_canary_file):
                os.unlink(self.__shutdown_canary_file)

        def __shutdown_is_set(self):
            """Returns True if shutdown canary file is removed (and so the server should shut down)."""
            if self.__shutdown_canary_file is None:
                raise McHashServerException('Shutdown canary file is not set.')
            return not os.path.exists(self.__shutdown_canary_file)

        def serve_forever(self, _=0.5):
            try:
                while not self.__shutdown_is_set():
                    self._handle_request_noblock()

                self.service_actions()
            finally:
                self.__set_shutdown()

                # Kill all children with SIGTERM that might still be waiting for something
                if self.active_children is not None:
                    for pid in self.active_children.copy():
                        os.kill(pid, signal.SIGKILL)

        def shutdown(self):
            self.__set_shutdown()

    # noinspection PyPep8Naming
    class _HTTPHandler(BaseHTTPRequestHandler):

        def _set_port(self, port: int):
            self._port = port

        def _set_pages(self, pages: dict):
            self._pages = pages

        def __write_response_string(self, response_string: Union[str, bytes]) -> None:
            if isinstance(response_string, str):
                # If response is string, assume that it's UTF-8; otherwise, write plain bytes to support various
                # encodings
                response_string = response_string.encode('utf-8')
            self.wfile.write(response_string)

        def __request_passed_authentication(self, page: dict) -> bool:
            if b'auth' in page:
                page['auth'] = page[b'auth']

            if 'auth' not in page:
                return True

            page['auth'] = decode_object_from_bytes_if_needed(page['auth'])

            auth_header = self.headers.get('Authorization', None)
            if auth_header is None:
                return False

            if not auth_header.startswith('Basic '):
                log.warning('Invalid authentication header: %s' % auth_header)
                return False

            auth_header = auth_header.strip()
            auth_header_name, auth_header_value_base64 = auth_header.split(' ')
            if len(auth_header_value_base64) == 0:
                log.warning('Invalid authentication header: %s' % auth_header)
                return False

            auth_header_value = base64.b64decode(auth_header_value_base64).decode('utf-8')
            if auth_header_value != page['auth']:
                log.warning("Invalid authentication; expected: %s, actual: %s" % (page['auth'], auth_header_value))
                return False

            return True

        def send_response(self, code: Union[int, HTTPStatus], message=None):
            """Fill in HTTP status message if not set."""
            if message is None:
                if isinstance(code, HTTPStatus):
                    message = code.phrase
                    code = code.value
            BaseHTTPRequestHandler.send_response(self, code=code, message=message)

        def do_POST(self):
            """Respond to a POST request."""
            # Pretend it's a GET (most test pages return static content anyway)
            return self.__handle_request()

        def do_GET(self):
            """Respond to a GET request."""
            return self.__handle_request()

        def __handle_request(self):
            """Handle GET or POST request."""

            path = urlparse(self.path).path

            if path not in self._pages:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.__write_response_string("Not found :(")
                return

            page = self._pages[path]

            if isinstance(page, str) or isinstance(page, bytes):
                page = {'content': page}

            # HTTP auth
            if not self.__request_passed_authentication(page=page):
                self.send_response(HTTPStatus.UNAUTHORIZED)
                self.send_header("WWW-Authenticate", 'Basic realm="HashServer"')
                self.end_headers()
                return

            # MC_REWRITE_TO_PYTHON: Decode strings from Perl's bytes
            if b'redirect' in page:
                # noinspection PyTypeChecker
                page['redirect'] = decode_object_from_bytes_if_needed(page[b'redirect'])
            if b'http_status_code' in page:
                # noinspection PyTypeChecker
                page['http_status_code'] = page[b'http_status_code']
            if b'callback' in page:
                # noinspection PyTypeChecker
                page['callback'] = page[b'callback']
            if b'content' in page:
                # noinspection PyTypeChecker
                page['content'] = page[b'content']
            if b'header' in page:
                # noinspection PyTypeChecker
                page['header'] = decode_object_from_bytes_if_needed(page[b'header'])

            if 'redirect' in page:
                redirect_url = page['redirect']
                http_status_code = page.get('http_status_code', HashServer._DEFAULT_REDIRECT_STATUS_CODE)
                self.send_response(http_status_code)
                self.send_header("Content-Type", "text/html; charset=UTF-8")
                self.send_header('Location', redirect_url)
                self.end_headers()
                self.__write_response_string("Redirecting.")
                return

            elif 'callback' in page:
                callback_function = page['callback']

                post_data = None
                if self.command.lower() == 'post':
                    post_data = self.rfile.read(int(self.headers['Content-Length'])).decode('utf-8')

                request = HashServer.Request(
                    port=self._port,
                    method=self.command,
                    path=self.path,
                    headers=dict(self.headers.items()),
                    content=post_data,
                )

                response = callback_function(request)

                if isinstance(response, str):
                    response = str.encode(response)

                log.debug("Raw callback response: %s" % str(response))

                if b"\r\n\r\n" not in response:
                    raise McHashServerException("Response must include both HTTP headers and data, separated by CRLF.")

                response_headers, response_content = response.split(b"\r\n\r\n", 1)
                for response_header in response_headers.split(b"\r\n"):

                    if response_header.startswith(b'HTTP/'):
                        protocol, http_status_code, http_status_message = response_header.split(b' ', maxsplit=2)
                        self.send_response(
                            code=int(http_status_code.decode('utf-8')),
                            message=http_status_message.decode('utf-8')
                        )

                    else:
                        header_name, header_value = response_header.split(b':', 1)
                        header_value = header_value.strip()
                        self.send_header(header_name.decode('utf-8'), header_value.decode('utf-8'))

                self.end_headers()
                self.__write_response_string(response_content)

                return

            elif 'content' in page:
                content = page['content']

                headers = page.get('header', 'Content-Type: text/html; charset=UTF-8')
                if not isinstance(headers, list):
                    headers = [headers]
                http_status_code = page.get('http_status_code', HTTPStatus.OK)

                self.send_response(http_status_code)

                for header in headers:
                    header_name, header_value = header.split(':', 1)
                    header_value = header_value.strip()
                    self.send_header(header_name, header_value)

                self.end_headers()
                self.__write_response_string(content)

                return

            else:
                raise McHashServerException('Invalid page: %s' % str(page))

    def __init__(self, port: int, pages: dict):
        """HTTP server's constructor.

        Sample pages dictionary:

            def __sample_callback(request: HashServer.Request) -> Union[str, bytes]:
                response = ""
                response += "HTTP/1.0 200 OK\r\n"
                response += "Content-Type: text/plain\r\n"
                response += "\r\n"
                response += "This is callback."
                return response

            pages = {

                # Simple static pages (served as text/plain)
                '/': 'home',    # str
                '/foo': b'foo', # bytes

                # Static page with additional HTTP header entries
                '/bar': {
                    'content': '<html>bar</html>',
                    'header': 'Content-Type: text/html',
                },
                '/bar2': {
                    'content': '<html>bar</html>',
                    'header': [
                        'Content-Type: text/html',
                        'X-Media-Cloud: yes',
                    ]
                },

                # Redirects
                '/foo-bar': {
                    'redirect': '/bar',
                },
                '/localhost': {
                    'redirect': "http://localhost:$_port/",
                },
                '/127-foo': {
                    'redirect': "http://127.0.0.1:$_port/foo",
                    'http_status_code': 303,
                },

                # Callback page
                '/callback': {
                    'callback': __sample_callback,
                },

                # HTTP authentication
                '/auth': {
                    'auth': 'user:password',
                    'content': '...',
                },
            }
        """

        if not port:
            raise McHashServerException("Port is not set.")
        if len(pages) == 0:
            log.warning("Pages dictionary is empty.")

        # MC_REWRITE_TO_PYTHON: Decode page keys from bytes
        pages = {decode_object_from_bytes_if_needed(k): v for k, v in pages.items()}

        self.__port = port
        self.__pages = pages

        # FIXME there definitely is a more sane way to do IPC than creating temporary files
        self.__shutdown_canary_file = os.path.join(tempfile.mkdtemp(), 'shutdown-canary-file')

    def __del__(self):
        self.stop()

    @staticmethod
    def __make_http_handler_with_pages(port: int, pages: dict):
        class _HTTPHandlerWithPages(HashServer._HTTPHandler):
            def __init__(self, *args, **kwargs):
                self._set_port(port=port)
                self._set_pages(pages=pages)
                super(_HTTPHandlerWithPages, self).__init__(*args, **kwargs)

        return _HTTPHandlerWithPages

    def start(self):
        """Start the webserver."""

        if tcp_port_is_open(port=self.__port):
            raise McHashServerException("Port %d is already open." % self.__port)

        log.info('Starting test web server %s:%d on PID %d' % (self.__host, self.__port, os.getpid()))
        log.debug('Pages: %s' % str(self.__pages))
        server_address = (self.__host, self.__port,)

        handler_class = HashServer.__make_http_handler_with_pages(port=self.__port, pages=self.__pages)

        self.__http_server = self._ForkingHTTPServer(
            server_address=server_address,
            request_handler_class=handler_class,
            shutdown_canary_file=self.__shutdown_canary_file
        )

        # "threading.Thread()" doesn't work with Perl callers
        self.__http_server_thread = multiprocessing.Process(target=self.__http_server.serve_forever)
        self.__http_server_thread.daemon = True
        self.__http_server_thread.start()

        if not wait_for_tcp_port_to_open(port=self.__port, retries=20, delay=0.1):
            raise McHashServerException("Port %d is not open." % self.__port)

    def stop(self):
        """Stop the webserver."""

        if not tcp_port_is_open(port=self.__port):
            log.warning("Port %d is not open." % self.__port)
            return

        log.info('Stopping test web server %s:%d on PID %d' % (self.__host, self.__port, os.getpid()))

        self.__http_server.shutdown()

        self.__http_server.socket.close()

        if self.__http_server is None:
            log.warning("HTTP server is None.")
        elif self.__http_server_thread is None:
            log.warning("HTTP server process is None.")
        else:
            self.__http_server_thread.join(timeout=2)
            self.__http_server_thread.terminate()
            self.__http_server_thread = None

        if not wait_for_tcp_port_to_close(port=self.__port, retries=20, delay=0.1):
            raise McHashServerException("Port %d is still open." % self.__port)

    def page_url(self, path: str) -> str:
        """Return the URL for the given page on the test server or raise of the path does not exist."""

        path = decode_object_from_bytes_if_needed(path)

        if path is None:
            raise McHashServerException("'path' is None.")

        if not path.startswith('/'):
            path = '/' + path

        path = urlparse(path).path

        if path not in self.__pages:
            raise McHashServerException('No page for path "%s" among pages %s.' % (path, str(self.__pages)))

        return 'http://localhost:%d%s' % (self.__port, path)
