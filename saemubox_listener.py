from __future__ import print_function, unicode_literals, division

import os
import socket

KLANGBECKEN_STATUS = 2

def main():
    host = os.environ.get('SAEMUBOX_HOST', 'localhost')
    port = os.environ.get('SAEMUBOX_PORT', '9999')
    liquidsoap_sock = os.environ.get('LIQUIDSOAP_SOCK', '/var/run/klangbecken.sock')

    try:
        sock = None
        status = None

        while True:
            if sock is None:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    sock.connect((host, int(port)))
                except socket.error:
                    # Log?
                    sock = None
                    continue

            try:
                b = sock.recv(1)
                if b == '':
                    sock.close()
                    sock = None
                else:
                    new_status = ord(b)
                    if status != new_status and new_status == KLANGBECKEN_STATUS:
                        # log
                        # send to liquidsoap instance
                        print('sending new status')
                        try:
                            ls_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                            #ls_sock.setblocking(0)
                            ls_sock.connect('/tmp/klangbecken.sock')
                            ls_sock.sendall(b'klangbecken.restart\n')
                            print(ls_sock.recv(1000))
                            ls_sock.sendall(b'quit\n')
                            print(ls_sock.recv(1000))
                            #ls_sock.close()
                        except socket.error:
                            print('ERROR: cannot connect to liquidsoap server')
                    status = ord(b)
            except socket.error:
                try:
                    sock.close()
                except:
                    pass
                sock = None

    except KeyboardInterrupt:
        # Exit
        pass


if __name__ == '__main__':
    main()
