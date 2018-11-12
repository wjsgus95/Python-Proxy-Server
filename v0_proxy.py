from socket import *
from urllib.parse import urlparse
import threading
import sys

BUFSIZE = 2048
TIMEOUT = 5
CRLF = '\r\n'

# Dissect HTTP header into line(first line), header(second line to end), body
# works
def parseHTTP(data):
    line, data = data[0:data.index(bCRLF)], data[data.index(bCRLF)+len(bCRLF):]
    data, body = data[0:data.index(bCRLF+bCRLF)], data[data.index(bCRLF+bCRLF)+len(bCRLF+bCRLF):]
    data = data.split(bCRLF)
    line = line.decode()

    header = dict()
    for field in [elt.decode() for elt in data]:
        idx = field.index(':')
        key = field[0:idx]
        value = field[idx+2:]
        header[key.lower()] = value.lower()

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
        pass
    
    # Set HTTP header value
    # If not exist, add new field
    # If value is empty string, remove field
    def setHeader(self, field, value):
        pass
    
    # Get URL from request packet line
    def getURL(self):
        pass
    
    def isChunked(self):
        return 'chunked' in self.getHeader('Transfer-Encoding')


# Proxy handler thread class
class ProxyThread(threading.Thread):
    def __init__(self, conn, addr):
        super().__init__()
        self.conn = conn  # Client socket
        self.addr = addr  # Client address
    
    # Thread Routine
    def run(self):
        while True:
            try:
                data = recvData(self.conn)
                req = parseHTTP(data)
                url = urlparse(req.getURL())
    
                # Do I have to do if it is not persistent connection?
    
                # Remove proxy infomation
    
                # Server connect
                svr = socket(AF_INET, SOCK_STREAM)
                # and so on...
    
                # send a client's request to the server
                svr.sendall(req.pack())
    
                # receive data from the server
                data = recvData(svr)
                res = parseHTTP(data)
    
                # Set content length header
    
                # If support pc, how to do socket and keep-alive?
            except Exception as e:
                pass
    
def main():
    try:
        sock = socket(AF_INET, SOCK_STREAM)
        sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(20)
        print('Proxy Server started on port %d' % port)
        
        while True:
            # Client connect
            conn, addr = sock.accept()
            # Start Handling
            pt = ProxyThread(conn, addr)
            pt.start()
    except:
        pass


if __name__ == '__main__':
    main()
