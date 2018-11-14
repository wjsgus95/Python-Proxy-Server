#!/usr/bin/python3

from socket import *
from urllib.parse import urlparse
import threading
import sys; import os
import argparse
import datetime
import gc
from threading import Lock

NOT_MODIFIED = 304
lock = Lock()

BUFSIZE = 8192
TIMEOUT = 1
HTTP_PORT = 80
PROXY_PORT = 3128
COLON = ':'
CRLF = '\r\n'
bCRLF = b'\r\n'

parser = argparse.ArgumentParser()
# in argparse: argument without dash is a positional argument
parser.add_argument('port', type=int)
parser.add_argument('-mt', action='store_true')
parser.add_argument('-pc', action='store_true')
parser.add_argument('-debug', action='store_true')
args = parser.parse_args()

CONNECTION_NR = 0

def sig_handler():
    sock.shutdown(SHUT_RDWR)
    sock.close()
    sys.exit(0)

class Unbuffered(object):
   def __init__(self, stream):
       self.stream = stream
   def write(self, data):
       self.stream.write(data)
       self.stream.flush()
   def writelines(self, datas):
       self.stream.writelines(datas)
       self.stream.flush()
   def __getattr__(self, attr):
       return getattr(self.stream, attr)

sys.stdout = Unbuffered(sys.stdout)

# Dissect HTTP header into line(first line), header(second line to end), body
# works
def parseHTTP(data):
    if not data : return None
    line, data = data[0:data.index(bCRLF)], data[data.index(bCRLF)+len(bCRLF):]
    data, body = data[0:data.index(bCRLF+bCRLF)], data[data.index(bCRLF+bCRLF)+len(bCRLF+bCRLF):]
    data = data.split(bCRLF)
    line = line.decode()

    header = dict()
    for field in [elt.decode() for elt in data]:
        idx = field.index(':')
        key = field[0:idx]
        value = field[idx+2:]
        header[key.lower()] = value

    return HTTPPacket(line, header, body)


# Receive HTTP packet with socket
# It support seperated packet receive
def recvData(conn):
    # Set time out for error or persistent connection end
    conn.settimeout(TIMEOUT)
    data = conn.recv(BUFSIZE)
    if not data: return None
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
        return self.header.get(field.lower(), "")
    
    # Set HTTP header value
    # If not exist, add new field
    # If value is empty string, remove field
    def setHeader(self, field, value):
        self.header[field.lower()] = value
        if value == '':
            self.header.pop(field.lower(), None)
    
    # Get URL from request packet line
    def getURL(self):
        return self.line.split(' ')[1]

    def getBodySize(self):
        return len(self.body)

    def getMethod(self):
        return self.line.split(' ')[0].upper()

    def getResponseCode(self):
        return int(self.line.split(' ')[1])

    # Remove hostname from request packet line
    def setURL(self, url):
        new_line = self.line.split(' ')
        new_line[1] = new_line[1].replace(url.netloc, '')
        self.line = ' '.join(new_line)
    
    def isChunked(self):
        return 'chunked' in self.getHeader('Transfer-Encoding')


# Proxy handler thread class
class ProxyThread(threading.Thread):
    def __init__(self, conn, addr, nr):
        super().__init__()
        self.conn = conn  # Client socket
        self.addr = addr  # Client address
        self.svr = socket(AF_INET, SOCK_STREAM)

        self.first_run = True
        self.nr = nr
        self.buffer = f"[{CONNECTION_NR}] {datetime.datetime.now()}\n"
        self.buffer += f'[{CONNECTION_NR}] > Connection from '+str(addr[0])+':'+str(addr[1])+'\n'

    def __del__(self):
        try:
            self.conn.shutdown(SHUT_RDWR)
            self.conn.close()
        except Exception as e:
            if args.debug: print("client shutdown exception in del")
            print(e)
        try:
            self.svr.close()
        except Exception as e:
            if args.debug: print("svr shutdown exception in del")
            print(e)
        finally:
            lock.acquire()
            print(self.buffer)
            lock.release()

    #remove this if not needed later 
    def sendConnectionEstablished(self):
        self.conn.sendall(bCRLF.join([
            b'HTTP/1.1 200 Connection Established',
            bCRLF
        ]))
    
    # Thread Routine
    def run(self):
        while True:
            try:
                if args.debug: print("before recvData")
                data = recvData(self.conn)
                if args.debug: print("after recvData")
                if not data:
                    if args.debug: print("Connection Closed")
                    return
                if args.debug: print("client -> proxy")
                req = parseHTTP(data)

                # note: there's also urlunparse(ParseResult)
                url = urlparse(req.getURL())
    
                if req.getHeader('Connection').lower() == 'closed': 
                    print("Connection Closed")
                    return

                if args.debug:
                    print("initial requset:")
                    print('>', req.line)
                    print(*[(k, v) for k, v in zip(req.header, req.header.values())], sep='\n')
                    print('\n')

                # Remove proxy infomation when doing persistent connection
                # https://www.oreilly.com/library/view/http-the-definitive/1565925092/ch04s05.html
                if args.pc:
                    req.setHeader('Proxy-Connection', '')
                    #req.setHeader('Connection', 'Keep-Alive')
                    #req.setHeader('Keep-Alive', f'timeout={TIMEOUT}, max=1000') 
                else:
                    req.setHeader('Proxy-Connection', '')
                    req.setHeader('Connection', 'Closed')
                #req.setURL(url)

                #print(f'[{self.nr}]', '>', req.line)
                self.buffer += f'[{self.nr}] > {req.line}\n'
                if args.debug:
                    print("requset:")
                    print(*[(k, v) for k, v in zip(req.header, req.header.values())], sep='\n')
                    print('\n')

                # Server connect
                # and so on...
                if self.first_run:
                    if req.getMethod() == 'CONNECT':
                        #host, port = url.path.split(COLON)
                        #port = int(port)
                        break
                    else:
                        host = url.netloc
                        port = HTTP_PORT
                    
                    self.svr.connect((host, port))
                    self.first_run = False
    
                # send a client's request to the server
                # sendall repeatedly calls send untill buffer is empty or error occurs
                if req.getMethod() != 'CONNECT':
                    self.svr.sendall(req.pack())
                if args.debug: print("proxy -> server")
    
                # receive data from the server
                data = recvData(self.svr)
                if args.debug: print("server -> proxy")
                res = parseHTTP(data)

                if args.debug:
                    print("initial response:")
                    print('<', res.line)
                    print(*[(k, v) for k, v in zip(res.header, res.header.values())], sep='\n')
                    print('\n')

                if req.getMethod() == 'CONNECT':
                    res = bCRLF.join([
                        b'HTTP/1.1 200 Connection Established',
                        b'Connection: Closed',
                        bCRLF])
                    res = parseHTTP(res)

                if args.pc:
                    if res.getHeader('Connection').lower() != 'closed':
                        res.setHeader('Connection', 'Keep-Alive')
                    elif req.getHeader('Connection').lower() == 'closed':
                        res.setHeader('Connection', 'Closed')
                else:
                    res.setHeader('Connection', 'Closed')

                # Set content length header
                res.setHeader('Content-Length', str(res.getBodySize()))

                self.conn.sendall(res.pack())
        
                # If support pc, how to do socket and keep-alive?
                #print(f'[{self.nr}]', '<', res.line)
                #print(f"[{self.nr}] < {res.getHeader('content-type')} {res.getHeader('content-length')} bytes")
                self.buffer += f'[{self.nr}] < {res.line}\n'
                self.buffer += f"[{self.nr}] < {res.getHeader('content-type')} {res.getHeader('content-length')} bytes\n"
                if args.debug:
                    print("response:")
                    print(*[(k, v) for k, v in zip(res.header, res.header.values())], sep='\n')
                    print('\n')
    
            except KeyboardInterrupt:
                if args.debug: print("Child Thread Keyboard Interrupt...")
                break
            except timeout:
                #if args.debug: print("Socket Timeout. Closing Connection...", flush=True)
                if args.debug: print("Socket Timeout. Closing Connection...")
                break
            except Exception as e:
                if args.debug: print("Exception occured")
                if args.debug: print(e)
                break
            else:
                pass
            if not args.pc: break
            if res.getHeader('connection').lower() == 'closed': break
            #if res.getResponseCode() == NOT_MODIFIED : break
        if args.debug: print("end of run return")
        return
    
def main():
    try:
        global sock
        global CONNECTION_NR

        if args.mt:
            print("* Multithreading [ON]")
        else:
            print("* Multithreading [OFF]")
        if args.pc:
            print("* Persistent Connection [ON]")
        else:
            print("* Persistent Connection [OFF]")

        sock = socket(AF_INET, SOCK_STREAM)
        sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        sock.bind(('0.0.0.0', args.port))
        sock.listen(20)
        print('Proxy Server started on port %d' % args.port, end='')
        print(f" at {str(datetime.datetime.now())}")
        
        # Client connect
        while True:
            # Client connect
            conn, addr = sock.accept()
            CONNECTION_NR += 1

            # Start Handling
            pt = ProxyThread(conn, addr, CONNECTION_NR)
            pt.daemon = True
            pt.start()
            if args.mt == False:
                pt.join()
            pt = None
            #gc.collect()
    except Exception as e:
        print("in main thread")
        print(e)
        pass
    except KeyboardInterrupt:
        if args.debug: print("Main Thread Keyboard Interrupt...")
        pass
    finally:
        sig_handler()


if __name__ == '__main__':
    main()
