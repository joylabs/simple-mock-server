#!/usr/bin/env python

# -*- coding: utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

"""
Simple Mock Server
-------------------

Run as a regular python script:
$ ./server.py
"""

import argparse
import json
import logging
import os
import sys
import time
import typing

from http.server import HTTPServer, BaseHTTPRequestHandler

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)


class CallsRegistry:
    def __init__(self):
        self.__registry: list[dict] = []

    def add(self, method: str, path: str, body: typing.Optional[bytes]):
        if body is not None:
            body = body.decode()

        self.__registry.append({
            'method': method,
            'path': path,
            'body': body,
        })

    def list(self) -> list[dict]:
        return self.__registry

    def clear(self):
        self.__registry = []


REGISTRY = CallsRegistry()


class Configuration:
    def __init__(self, hostname, port, responses):
        self.hostname = hostname
        self.port = port
        self.head_response_map = {}
        self.get_response_map = {}
        self.post_response_map = {}
        self.put_response_map = {}
        self.delete_response_map = {}
        self._build_response_map(responses)

    def _build_response_map(self, responses):
        response_map = {
            "GET": self.get_response_map,
            "POST": self.post_response_map,
            "PUT": self.put_response_map,
            "DELETE": self.delete_response_map,
            "HEAD": self.head_response_map,
        }

        for response in responses:
            mocked_resp = MockedResponse(
                response.get("method"),
                response.get("path"),
                response.get("responseCode"),
                response.get("headers"),
                response.get("body"),
                response.get("delay"),
            )

            method_map = response_map[response.get("method").upper()]
            method_map[response.get("path")] = mocked_resp


class Response:
    def __init__(
        self,
        method=None,
        path=None,
        response_code=None,
        headers=None,
        body=None,
        delay=None,
    ):
        self.method = method if method else "GET"
        self.path = path if path else "/"
        self.response_code = response_code or 200
        self.headers = headers or []
        self.delay = delay or 0
        self.body = self.body_wrapper_cls()(body)

    def __repr__(self):
        return self.__str__()

    def body_wrapper_cls(self):
        raise NotImplementedError


class MockerResponse(Response):
    class Body:
        def __init__(self, body: typing.Optional[str] = None):
            self.body: str = body or ''

        def load(self) -> bytes:
            return self.body.encode()

        def __len__(self):
            return len(self.body)

        def __str__(self):
            return self.body

    def body_wrapper_cls(self):
        return self.Body


class MockedResponse(Response):

    def body_wrapper_cls(self):
        return self.MockedResponseBody

    class MockedResponseBody:
        def __init__(self, content=None):
            self._file_definition = "@file://"
            self.content = content if content else ""
            self.is_file = self._file_definition in self.content

        def load(self):
            if self.is_file:
                filename = self.content.replace(self._file_definition, "")
                try:
                    with open(filename) as file:
                        return file.read()
                except:
                    logger.error(
                        "File '%s' not found in filesystem.", filename
                    )
                    return None
            else:
                return self.content.encode('utf-8')

        def __len__(self):
            try:
                filename = self.content.replace(self._file_definition, "")
                length = os.stat(filename).st_size
            except:
                length = len("None")

            return length if self.is_file else len(self.content)

        def __str__(self):
            return f"is_file = [{self.is_file}], content = [{self.content}]"


def SimpleHandlerFactory(configuration):
    class SimpleHandler(BaseHTTPRequestHandler):
        response_map = {
            "HEAD": configuration.head_response_map.get,
            "GET": configuration.get_response_map.get,
            "POST": configuration.post_response_map.get,
            "PUT": configuration.put_response_map.get,
            "DELETE": configuration.delete_response_map.get,
        }

        def do_HEAD(self):
            response = self.retrieve_response(self.path, "HEAD")
            self.send(self.path, response)

        def do_GET(self):
            response = self.retrieve_response(self.path, "GET")
            self.send(self.path, response)

        def do_POST(self):
            response = self.retrieve_response(self.path, "POST")
            self.send(self.path, response)

        def do_DELETE(self):
            response = self.retrieve_response(self.path, "DELETE")
            self.send(self.path, response)

        def do_PUT(self):
            response = self.retrieve_response(self.path, "PUT")
            self.send(self.path, response)

        def send(self, path, response: Response):
            time.sleep(response.delay)

            self.send_response(response.response_code)

            for header in response.headers:
                self.send_header(list(header.keys())[0], list(header.values())[0])
            self.send_header("Content-length", str(len(response.body)))
            self.end_headers()
            self.wfile.write(response.body.load())

        def retrieve_response(self, path, method) -> Response:

            if path.startswith('/mocker'):
                response: Response
                match method:
                    case 'GET':
                        headers = [{"Content-Type": "application/json"}]
                        d = json.dumps(REGISTRY.list())
                        response = MockerResponse(method, path, 200, headers, d)
                    case 'DELETE':
                        REGISTRY.clear()
                        response = MockerResponse(method, path, 204, {}, '')
                    case _:
                        response = MockerResponse(method, path, 500, {}, 'Unknown method')
                return response

            else:
                content = None
                if self.headers.get('Content-Length') or 0 > 0:
                    content = self.rfile.read(int(self.headers.get('Content-Length')))

                REGISTRY.add(path, method, content)
                try:
                    response = self.response_map.get(method)(path)

                    if response is None:
                        body = json.dumps({"message": f"path '{path}' not found"})
                        headers = [{"Content-Type": "application/json"}]
                        response = MockedResponse(method, path, 404, headers, body)

                except Exception as err:
                    body = json.dumps({"message": f"An error happened with path '{path}': {err}"})
                    headers = [{"Content-Type": "application/json"}]
                    response = MockedResponse(method, path, 500, headers, body)

                return response

    return SimpleHandler


def load_configuration(config_file=None):
    default_host = os.environ.get("HOST", "0.0.0.0")
    default_port = int(os.environ.get("PORT", "8000"))
    default_responses = []
    if config_file:
        logger.info('Loading "%s"...', config_file)
        file_name = config_file
    else:
        logger.info("Loading default config.json...")
        file_name = "config.json"

    with open(file_name) as conf_file:
        json_config = json.loads(conf_file.read())

    configuration = Configuration(
        json_config.get("hostname", default_host),
        json_config.get("port", default_port),
        json_config.get("responses", default_responses),
    )

    return configuration


def main(config):
    httpd = HTTPServer(
        (config.hostname, config.port), SimpleHandlerFactory(config)
    )

    logger.info("Server Starts - %s:%s", config.hostname, config.port)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass

    httpd.server_close()
    logger.info("Server Stops - %s:%s", config.hostname, config.port)


def get_opts():
    env_var_msg = """ENVIRONMENT VARIABLES
    \tHOST
    \t  Sets the host interface the server will use. It's overwritten by the configuration file.
    \t  To use it, remove the key `host` from the configuration file.
    \tPORT
    \t  Sets the port the server will listen on. It's overwritten by the configuration file.
    \t  To use it, remove the key `port` from the configuration file.

    """
    parser = argparse.ArgumentParser(
        epilog=env_var_msg,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-f",
        "--file",
        metavar="file",
        help="Use custom JSON configuration file.",
        required=False,
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = get_opts()
    config = load_configuration(args.file)
    main(config)
