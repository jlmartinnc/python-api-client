# The MIT License (MIT)
#
# Copyright (c) Frederic Guillot
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import json
import base64
import functools
import asyncio
import ssl
from typing import Dict, Optional
from urllib import request as http


DEFAULT_AUTH_HEADER = "Authorization"
ASYNC_FUNCNAME_MARKER = "_async"


class ClientError(Exception):
    pass


class Client:
    """
    Kanboard API client for interacting with the Kanboard JSON-RPC API.

    This client provides both synchronous and asynchronous access to all Kanboard API methods.
    Methods are dynamically resolved based on the Kanboard API method names, using snake_case for Python calls.

    Example usage:
        from kanboard import Client

        kb = Client(url="http://localhost/jsonrpc.php",
                    username="jsonrpc",
                    password="your_api_token")

        project_id = kb.create_project(name="My project")
    """

    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        auth_header: str = DEFAULT_AUTH_HEADER,
        cafile: Optional[str] = None,
        insecure: bool = False,
        ignore_hostname_verification: bool = False,
        user_agent: str = "Kanboard Python API Client",
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        """
        Initialize a new Kanboard API client instance.

        Args:
            url (str): The Kanboard JSON-RPC API endpoint URL (e.g.,
                'http://localhost/jsonrpc.php').
            username (str): Kanboard API username or real username.
            password (str): Kanboard API token or user password.
            auth_header (str, optional): HTTP header for authentication. Defaults to 'Authorization'.
            cafile (Optional[str], optional): Path to a custom CA certificate file. Defaults to None.
            insecure (bool, optional): If True, ignore SSL certificate errors and hostname mismatches.
                Defaults to False.
            ignore_hostname_verification (bool, optional): If True, skip SSL certificate hostname verification.
                Defaults to False.
            user_agent (str, optional): Custom User-Agent string for HTTP requests. Defaults to
                'Kanboard Python API Client'.
            loop (Optional[asyncio.AbstractEventLoop], optional): Asyncio event loop to use. If None, uses the
                current event loop or creates a new one.
        """
        self._url = url
        self._username = username
        self._password = password
        self._auth_header = auth_header
        self._cafile = cafile
        self._insecure = insecure
        self._user_agent = user_agent
        self._ignore_hostname_verification = ignore_hostname_verification

        if not loop:
            try:
                self._event_loop = asyncio.get_event_loop()
            except RuntimeError:
                self._event_loop = asyncio.new_event_loop()

    def __getattr__(self, name: str):
        if self.is_async_method_name(name):

            async def function(*args, **kwargs):
                return await self._event_loop.run_in_executor(
                    None,
                    functools.partial(
                        self.execute, method=self._to_camel_case(self.get_funcname_from_async_name(name)), **kwargs
                    ),
                )

            return function
        else:

            def function(*args, **kwargs):
                return self.execute(method=self._to_camel_case(name), **kwargs)

            return function

    @staticmethod
    def is_async_method_name(funcname: str) -> bool:
        return funcname.endswith(ASYNC_FUNCNAME_MARKER)

    @staticmethod
    def get_funcname_from_async_name(funcname: str) -> str:
        return funcname[: len(funcname) - len(ASYNC_FUNCNAME_MARKER)]

    @staticmethod
    def _to_camel_case(snake_str: str) -> str:
        components = snake_str.split("_")
        return components[0] + "".join(x.title() for x in components[1:])

    @staticmethod
    def _parse_response(response: bytes):
        if not response:
            raise ClientError("Empty response from server")
        try:
            body = json.loads(response.decode(errors="ignore"))

            if "error" in body:
                message = body.get("error").get("message")
                raise ClientError(message)

            return body.get("result")
        except ValueError as e:
            raise ClientError(f"Failed to parse JSON response: {e}")

    def _do_request(self, headers: Dict[str, str], body: Dict):
        try:
            request = http.Request(self._url, headers=headers, data=json.dumps(body).encode())

            ssl_context = ssl.create_default_context(cafile=self._cafile)
            if self._insecure:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

            if self._ignore_hostname_verification:
                ssl_context.check_hostname = False

            response = http.urlopen(request, context=ssl_context).read()
        except Exception as e:
            raise ClientError(str(e))
        return self._parse_response(response)

    def execute(self, method: str, **kwargs):
        """
        Call a remote Kanboard API procedure.

        Args:
            method (str): The Kanboard API method name in camelCase (e.g., 'createProject').
            **kwargs: Named arguments to pass to the API method.

        Returns:
            The result returned by the Kanboard API for the requested method.

        Raises:
            ClientError: If the API returns an error or if a network/HTTP error occurs.
        """
        payload = {"id": 1, "jsonrpc": "2.0", "method": method, "params": kwargs}

        credentials = base64.b64encode("{}:{}".format(self._username, self._password).encode())
        auth_header_prefix = "Basic " if self._auth_header == DEFAULT_AUTH_HEADER else ""
        headers = {
            self._auth_header: auth_header_prefix + credentials.decode(),
            "Content-Type": "application/json",
            "User-Agent": self._user_agent,
        }

        return self._do_request(headers, payload)
