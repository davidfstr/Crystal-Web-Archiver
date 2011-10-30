from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

def run(project):
    def request_handler_factory(*args, **kwargs):
        handler = _RequestHandler(*args, **kwargs)
        handler.project = project
        return handler
    
    port = 2797
    address = ('', port)
    server = HTTPServer(address, request_handler_factory)
    try:
        print 'Server started on port %s.' % port
        server.serve_forever()
    finally:
        server.server_close()

class _RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        request_host = self.headers.get('Host', 'localhost:%s' % self.server.server_port)
        request_url = 'http://%s%s' % (request_host, self.path)
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        
        self.wfile.write('You are <a href="%s">here</a>!' % request_url)
        
        print
        print self.headers
