from socket import *
from urllib.parse import urlparse
import threading
import sys; import signal
import argparse

def sig_handler(sig, frame):
    for cli in clients:
        cli.shutdown(socket.SHUT_RDWR)
        cli.close()
    sock.shutdown(socket.SHUT_RDWR)
    sock.close()
    sys.exit(0)

signal.signal(signal.SIGINT, sig_handler)

BUFSIZE = 2048
TIMEOUT = 5
HTTP_PORT = 80
CRLF = '\r\n'

parser = argparse.ArgumentParser()
# in argparse: argument without dash is a required argument to be parsed
parser.add_argument('port', type=int)
parser.add_argument('-mt', action='store_true')
parser.add_argument('-pc', action='store_true')
args = parser.parse_args()

cache = {} # dict[url] = HTTPPacket

# Dissect HTTP header into line(first line), header(second line to end), body
# works
def parseHTTP(data):
    data = data.decode()
    line, data = data[0:data.index(CRLF)], data[data.index(CRLF)+1:-1]
    data, body = data.split(CRLF+CRLF)
    data = data.split(CRLF)
    data = data[1:]

    header = dict()
    for field in data:
        idx = field.index(':')
        key = field[0:idx]
        value = field[idx+2:]
        header[key] = value

    #print("line: ", line)
    #print("header: ", header)
    #print("body: ", body)
    
    return HTTPPacket(line, header, body)


# Receive HTTP packet with socket
# It support seperated packet receive
def recvData(conn):
    # Set time out for error or persistent connection end
    conn.settimeout(TIMEOUT)
    data = conn.recv(BUFSIZE)
    while b'\r\n\r\n' not in data:
        data += conn.recv(BUFSIZE)
    packet = parseHTTP(data)
    body = packet.body
    
    # Chunked-Encoding
    if packet.isChunked():
        readed = 0
        while True:
            while b'\r\n' not in body[readed:len(body)]:
                d = conn.recv(BUFSIZE)
                body += d
            size_str = body[readed:len(body)].split(b'\r\n')[0]
            size = int(size_str, 16)
            readed += len(size_str) + 2
            while len(body) - readed < size + 2:
                d = conn.recv(BUFSIZE)
                body += d
            readed += size + 2
            if size == 0: break
    
    # Content-Length
    elif packet.getHeader('Content-Length'):
        received = 0
        expected = packet.getHeader('Content-Length')
        if expected == None:
            expected = '0'
        expected = int(expected)
        received += len(body)
        
        while received < expected:
            d = conn.recv(BUFSIZE)
            received += len(d)
            body += d
    
    packet.body = body
    return packet.pack()


# HTTP packet class
# Manage packet data and provide related functions
class HTTPPacket:
    # Constructer
    def __init__(self, line, header, body):
        self.line = line  # Packet first line(String)
        self.header = header  # Headers(Dict.{Field:Value})
        self.body = body  # Body(Bytes)
    
    # Make encoded packet data
    def pack(self):
        ret = self.line + CRLF
        for field in self.header:
            ret += field + ': ' + self.header[field] + CRLF
        ret += CRLF
        ret = ret.encode()
        ret += self.body
        return ret
    
    # Get HTTP header value
    # If not exist, return empty string
    def getHeader(self, field):
        return self.header.get(field, "")
    
    # Set HTTP header value
    # If not exist, add new field
    # If value is empty string, remove field
    def setHeader(self, field, value):
        self.header[field] = value
        if value == '':
            self.header.pop(field, None)
        pass
    
    # Get URL from request packet line
    # works
    def getURL(self):
        return self.line[self.line.index('GET')+4:]
    
    def isChunked(self):
        return 'chunked' in self.getHeader('Transfer-Encoding')


# Proxy handler thread class
class ProxyThread(threading.Thread):
    def __init__(self, conn, addr):
        super().__init__()
        self.conn = conn  # Client socket
        self.addr = addr  # Client address

    def __del__(self):
        self.conn.shutdown(socket.SHUT_RDWR)
        self.conn.close()
    
    # Thread Routine
    def run(self):
        while True:
            try:
                data = recvData(self.conn)
                req = parseHTTP(data)
                # note: there's also urlunparse(ParseResult)
                url = urlparse(req.getURL())
    
                # Remove proxy infomation when doing persistent connection
                # as there is a limit to number of persistent connection a client (in this case our proxy server)
                # can maintain at the same time

                if args.pc:
                    # TODO remove proxy information
                    pass

                # Server connect
                # and so on...
                svr = socket(AF_INET, SOCK_STREAM)
                svr.connect((url.netloc, HTTP_PORT))
    
                # send a client's request to the server
                # sendall repeatedly calls send untill buffer is empty or error occurs
                svr.sendall(req.pack())
    
                # receive data from the server
                data = recvData(svr)
                res = parseHTTP(data)
                cache[url] = res
                self.conn.sendall(res)

                # Set content length header
    
                # If support pc, how to do socket and keep-alive?

                if args.pc:
                    continue
                else:
                    raise Exception
    
            except KeyboardInterrupt:
                print("Keyboard Interrupt...")
            except socket.timeout:
                print("Socket Timeout...")
            except Exception as e:
                pass
            finally:
                self.conn.shutdown(socket.SHUT_RDWR)
                self.conn.close()
                return
    
def main():
    try:
        global sock
        sock = socket(AF_INET, SOCK_STREAM)
        sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        sock.bind(('0.0.0.0', args.port))
        sock.listen(20)
        print('Proxy Server started on port %d' % args.port)
        
        while True:
            # Client connect
            conn, addr = sock.accept()
            # Start Handling
            pt = ProxyThread(conn, addr)
            pt.start()
            if args.mt == False:
                pt.join()
    except Exception as e:
        print(e)
        pass


if __name__ == '__main__':
    main()
    #data = open('http_get.txt', 'rb')
    #data = data.read()

    #print(parseHTTP(data).getURL())
