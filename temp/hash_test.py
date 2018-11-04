
class A():
    def __init__(self, a, b):
        self.a = a
        self.b = b

    def __hash__(self):
        pass  

    def __eq__(self, other):
        return self.a == other.a

Aset = set()
instance1 = A(1, 2)
Aset.update([instance1])
instance2 = A(1, 3)
Aset.update([instance2])


print(Aset)

