import threading

class A(threading.Thread):
    def run(self):
        print("AAAAA")


a = A()
a.run()
