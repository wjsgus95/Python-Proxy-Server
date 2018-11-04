gl = 2

class A():
    def __init__(self, a):
        self.a = a

    def __del__(self):
        #print("destruct -> ", self.a)
        gl = 1


try:
    while True:
        a1 = A(1)
        a2 = A(2)
except KeyboardInterrupt as i:
    pass
finally:
    a1.__del__()
    a2.__del__()


