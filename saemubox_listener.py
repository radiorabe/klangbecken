from __future__ import print_function, unicode_literals, division

import os
import select
import socket
import time

KLANGBECKEN_STATUS = 1
LS_COMMAND = b'klangbecken.restart\n'

def main():
    mcast_if = os.environ.get('SAEMUBOX_MCAST_IF', '10.130.36.16')
    mcast_host = os.environ.get('SAEMUBOX_MCAST_GROUP', '239.200.0.1')
    mcast_port = os.environ.get('SAEMUBOX_MCAST_PORT', '48000')
    liquidsoap_sock = os.environ.get('LIQUIDSOAP_SOCK', '/var/run/klangbecken.sock')

    valid_ids = set(map(str, range(1, 7)))

    print("Starting ...")
    print("Forwarding changes from {}:{} to {}".format(mcast_host, mcast_port, liquidsoap_sock))

    try:
        sock = None
        status = None

        while True:
            if sock is None:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                sock.setsockopt(socket.SOL_IP, socket.IP_MULTICAST_TTL, 20)
                sock.setsockopt(socket.SOL_IP, socket.IP_MULTICAST_LOOP, 0)
                try:
                    sock.bind((mcast_host, int(mcast_port)))
                except socket.error:
                    print("ERROR: could not connect to {}:{}".format(mcast_host, mcast_port))
                    sock = None
                    time.sleep(10)
                    continue
                sock.setsockopt(socket.SOL_IP, socket.IP_MULTICAST_IF,
                             socket.inet_aton(mcast_if))
                sock.setsockopt(socket.SOL_IP, socket.IP_ADD_MEMBERSHIP,
                             socket.inet_aton(mcast_host) + socket.inet_aton(mcast_if))
                time.sleep(0.1)

            try:
                output = None

                # read from socket while there is something to read (non-blocking)
                while select.select([sock], [], [], 0)[0]:
                    data, addr = sock.recvfrom(1024)
                    ids = data.split()   # several saemubox ids might come in one packet
                    if ids:
                        if ids[-1] in valid_ids:  # only take last id
                            output = ids[-1]
                        else:
                            print("WARNING: received invalid data: %s" % data)
                if output is None:
                    print("ERROR: could not read current status.")
                    output = 0

                new_status = int(output)
                if status != new_status:
                    print('New status: {} (old: {})'.format(new_status, status))
                    if new_status == KLANGBECKEN_STATUS:
                        print('Restarting Klangbecken ...')
                        try:
                            ls_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                            ls_sock.connect(liquidsoap_sock)
                            ls_sock.sendall(LS_COMMAND)
                            print(ls_sock.recv(1000))
                            ls_sock.sendall(b'quit\n')
                            print(ls_sock.recv(1000))
                        except socket.error:
                            print('ERROR: cannot connect to liquidsoap server')
                status = int(output)
            except socket.error:
                try:
                    sock.close()
                except:
                    pass
                sock = None

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("Exiting ...")
        pass


if __name__ == '__main__':
    main()
