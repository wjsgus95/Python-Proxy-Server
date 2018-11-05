#!/usr/bin/python3

from socket import *
from urllib.parse import urlparse
import threading
import sys
import argparse



BUFSIZE = 2048
TIMEOUT = 5
HTTP_PORT = 80
PROXY_PORT = 3128
CRLF = '\r\n'
bCRLF = b'\r\n'

parser = argparse.ArgumentParser()
# in argparse: argument without dash is a positional argument
parser.add_argument('port', type=int, default=PROXY_PORT)
parser.add_argument('-mt', action='store_true')
parser.add_argument('-pc', action='store_true')
args = parser.parse_args()


def sig_handler():
    sock.shutdown(SHUT_RDWR)
    sock.close()
    sys.exit(0)

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
    def getURL(self):
        return self.line.split(' ')[1]

    def getBodySize(self):
        return len(self.body)

    # Remove hostname from request packet line
    #def setURL(self):
    #    hostname = self.getHeader('Host')

    #    new_line = self.line.split(' ')
    #    new_line[1] = new_line[1][new_line[1].index(hostname)+len(hostname):]
    #    self.line = ' '.join(new_line)
    
    def isChunked(self):
        return 'chunked' in self.getHeader('Transfer-Encoding')


# Proxy handler thread class
class ProxyThread(threading.Thread):
    def __init__(self, conn, addr):
        super().__init__()
        self.conn = conn  # Client socket
        self.addr = addr  # Client address
        self.first_run = True

    def __del__(self):
        try:
            self.conn.shutdown(SHUT_RDWR)
            self.conn.close()
        except Exception:
            pass
    
    # Thread Routine
    def run(self):
        while True:
            try:
                import pdb; pdb.set_trace()
                data = recvData(self.conn)
                req = parseHTTP(data)

                # note: there's also urlunparse(ParseResult)
                url = urlparse(req.getURL())
    
                if req.getHeader('Connection').lower() == 'closed': 
                    print("Connection Closed")
                    return

                print("requset:")
                print(*[(k, v) for k, v in zip(req.header, req.header.values())], sep='\n')
                print('\n\n')

                # Remove proxy infomation when doing persistent connection
                # https://www.oreilly.com/library/view/http-the-definitive/1565925092/ch04s05.html
                if args.pc:
                    if req.getHeader('Connection').lower() != 'keep-alive':
                        if req.getHeader('Proxy-Connection').lower() == 'keep-alive':
                            req.setHeader('Connection', 'Keep-Alive')
                        req.setHeader('Proxy-Connection', '')
                    else:
                        req.setHeader('Proxy-Connection', '')
                else:
                    req.setHeader('Connection', '')

                # Server connect
                # and so on...
                if self.first_run:
                    svr = socket(AF_INET, SOCK_STREAM)
                    svr.connect((url.netloc, HTTP_PORT))
                    self.first_run = False
    
                # send a client's request to the server
                # sendall repeatedly calls send untill buffer is empty or error occurs
                svr.sendall(req.pack())
    
                # receive data from the server
                data = recvData(svr)
                res = parseHTTP(data)
                self.conn.sendall(res.pack())

                # Set content length header
                res.setHeader('Content-Length', f'{res.getBodySize()}')
    
                # If support pc, how to do socket and keep-alive?
    
            except KeyboardInterrupt:
                print("Child Thread Keyboard Interrupt...")
            except timeout:
                print("Socket Timeout. Closing Connection...")
            except Exception as e:
                print("Exception occured")
                print(e)
            if args.pc == False : break
        print("end of run return")
        return
            #finally:
            #    import pdb; pdb.set_trace()
            #    print("finally return")
            #    return
    
def main():
    try:
        global sock
        sock = socket(AF_INET, SOCK_STREAM)
        sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        sock.bind(('0.0.0.0', args.port))
        sock.listen(20)
        print('Proxy Server started on port %d' % args.port)
        n = 0
        
        while True:
            # Client connect
            conn, addr = sock.accept()
            # interpolation available in Python3.6+
            #print(f'new connection from {addr}')
            print("new connection from " + str(addr))
            # Start Handling
            pt = ProxyThread(conn, addr)
            pt.daemon = True
            pt.start()
            if args.mt == False:
                pt.join()
            n += 1
            print(f'{n} threads have been created')
    except Exception as e:
        print(e)
        pass
    except KeyboardInterrupt:
        print("Main Thread Keyboard Interrupt...")
        pass
    finally:
        sig_handler()


if __name__ == '__main__':
    main()
    #data = open('http_get.txt', 'rb')
    #data = data.read()

    #print(parseHTTP(data).getURL())
