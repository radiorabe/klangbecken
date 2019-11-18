import os
import select
import socket
import time

LS_COMMAND = b'klangbecken.onair {}\n'

KLANGBECKEN_SAEMUBOX_ID = 1


def main():
    mcast_if = os.environ.get('SAEMUBOX_MCAST_IF', '10.130.36.16')
    mcast_host = os.environ.get('SAEMUBOX_MCAST_GROUP', '239.200.0.1')
    mcast_port = os.environ.get('SAEMUBOX_MCAST_PORT', '48000')
    liquidsoap_sock = os.environ.get('LIQUIDSOAP_SOCK',
                                     '/var/run/klangbecken.sock')

    valid_ids = set(map(str, range(1, 7)))

    print("Starting ...")
    print(f"Forwarding changes from {mcast_host}:{mcast_port} to "
          f"{liquidsoap_sock}")

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
                    print(f"ERROR: could not connect to {mcast_host}:"
                          f"{mcast_port}")
                    sock = None
                    time.sleep(10)
                    continue
                sock.setsockopt(socket.SOL_IP, socket.IP_MULTICAST_IF,
                                socket.inet_aton(mcast_if))
                sock.setsockopt(socket.SOL_IP, socket.IP_ADD_MEMBERSHIP,
                                socket.inet_aton(mcast_host)
                                + socket.inet_aton(mcast_if))
                time.sleep(0.1)

            try:
                output = None

                # read from socket while there is something to read
                # (non-blocking)
                while select.select([sock], [], [], 0)[0]:
                    data, addr = sock.recvfrom(1024)
                    ids = data.split()   # several ids might come in one packet
                    if ids:
                        if ids[-1] in valid_ids:  # only take last id
                            output = ids[-1]
                        else:
                            print("WARNING: received invalid data: %s" %
                                  repr(data))
                if output is None:
                    print("ERROR: could not read current status. "
                          "Reconnecting ...")
                    raise socket.error()

                new_status = int(output)
                if status != new_status:
                    print(f'New status: {new_status} (old: {status})')
                    onair = new_status == KLANGBECKEN_SAEMUBOX_ID
                    if onair:
                        print('Starting Klangbecken ...')
                    else:
                        print('Stopping Klangbecken ...')
                    try:
                        ls_sock = socket.socket(socket.AF_UNIX,
                                                socket.SOCK_STREAM)
                        ls_sock.connect(liquidsoap_sock)
                        ls_sock.sendall(LS_COMMAND.format(onair))
                        print(ls_sock.recv(1000))
                        ls_sock.sendall(b'quit\n')
                        print(ls_sock.recv(1000))
                        status = new_status
                    except socket.error:
                        print('ERROR: cannot connect to liquidsoap server')
            except socket.error:
                try:
                    sock.close()
                except:   # noqa: E722
                    pass
                sock = None

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("Exiting ...")
        pass


if __name__ == '__main__':
    main()
