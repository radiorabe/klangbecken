import socket
from datetime import datetime
from threading import Thread
from time import sleep


print('use this script if you have no Sämubox close to you')


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def send(num):
    while True:
        if stop:
            break
        sock.sendto(str(num).encode(), ('239.200.0.1', 48000))
        sleep(0.05)


num = input("Enter data: ")
while True:
    stop = False
    print(datetime.now().strftime("%H:%M:%S"), "sending {}".format(num))
    thread = Thread(target=send, args=(num,))
    thread.start()
    num = input("Enter data: ")
    stop = True
    thread.join()
