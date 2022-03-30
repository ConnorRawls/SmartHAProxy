# QUESTIONS
# Does passing global Manager() objects to constructor without using Process()
# cause issues? (Does it actually change the objects on a global level?)

# Author: Connor Rawls
# Email: connorrawls1996@gmail.com
# Organization: University of Louisiana

# Capture actual task (http request) list of each backend server and determine which
# tasks each server will not be able to satisfy based upon SLO requirements (1 sec).
# Communicate this information with client through UNIX sockets.
# Four processes run concurrently:
#   -haproxyEvent
#   -apacheEvent
#   -whiteAlg
#   -comms
# Three objects are referenced globally:
#   -statMatrix
#   -dynMatrix
#   -whitelist

import os
import csv
import subprocess
import re
import socket
import json
import time
from sys import getsizeof
from multiprocessing import Process, Manager, Lock

INVALID_SERVER_COUNT = Exception('Invalid server count detected.\nAre your \
    servers running?')
SERVER_UNKNOWN_H = Exception('Unknown server name detected in HAProxy logs.\
    \nMust be of the format "vm#"')
SERVER_UNKNOWN_A = Exception('Unknown server name detected in Apache logs.\
    \nMust be of the format "vm#"')

MSGLEN = 1

def main():
    # Contains tuples of possible tasks (url) and their respective execution 
    # times (offline profiled)
    statMatrix = Manager().dict()
    # Contains lists of currently being executed tasks on each backend server
    dynMatrix = Manager().dict()
    # Contains URL (key) and servers (value) request should not be sent to
    whitelist = Manager().dict()

    constructGlobals(statMatrix, dynMatrix, whitelist)

    # Truncate logs
    os.system("truncate -s 0 /var/log/apache_access.log")
    os.system("truncate -s 0 /var/log/haproxy_access.log")

    # Master Lock TM
    lock = Lock()

    # Multiprocessing mumbo jumbo
    proc1 = Process(target = haproxyEvent, args = (dynMatrix, lock))
    proc2 = Process(target = apacheEvent, args = (dynMatrix, lock))
    proc3 = Process(target = whiteAlg, args = (statMatrix, dynMatrix, \
        whitelist, lock))
    proc4 = Process(target = comms, args = (whitelist, lock))

    print("Commencing Smartdrop.")

    proc3.start()       # Start blacklist algorithm
    proc4.start()       # Start listening to socket
    proc1.start()       # Start reading HAProxy events
    proc2.start()       # Start reading Apache events
    proc1.join()
    proc2.join()
    proc1.terminate()   # Stop reading HAProxy events
    proc2.terminate()   # Stop reading Apache events
    proc4.join()
    proc3.join()
    proc4.terminate()   # Stop listening to socket
    proc3.terminate()   # Stop blacklist algorithm

# -----------------------------------------------------------------------------
# Add task to dynamic matrix
# -----------------------------------------------------------------------------
def haproxyEvent(dynMatrix, lock):
    while True:
        with open('/var/log/haproxy_access.log', 'r') as file:
            reader = csv.reader(file)

            # Parse log file and add requests to dynMatrix
            for row in reader:
                if len(row) != 2: pass

                else:
                    server = row[0]
                    url = row[1]

                    if not re.match('^vm[0-9]+$', server):
                        print('Passing on server: ', server)
                        pass

                    whichVM = int(server[2])

                    lock.acquire()
                    dynMatrix[whichVM].append(url)
                    lock.release()

        # Truncate log
        os.system("truncate -s 0 /var/log/haproxy_access.log")

# -----------------------------------------------------------------------------
# Remove task from dynamic matrix
# -----------------------------------------------------------------------------
def apacheEvent(dynMatrix, lock):
    while True:
        # Log contains tuples of backend VM, url, execution time
        with open('/var/log/apache_access.log', 'r') as file:
            reader = csv.reader(file)

            # for server, url, actualTime in reader:
            for row in reader:
                if len(row) != 3: pass

                else:
                    server = row[0]
                    url = row[1]
                    actualTime = row[2]

                    # if not re.match('^hpcclab[0-9]+$', server): raise SERVER_UNKNOWN_A
                    if not re.match('^hpcclab[0-9]+$', server):
                        print(f"Passing on '{server}'")
                        pass

                    # Determine the VM that the tuple belongs to
                    whichVM = int(server[-1])

                    # If the url matches a request in the VM's tasklist
                    # if url in dynMatrix[whichVM].tasks:
                    if url in dynMatrix[whichVM]:
                        # Remove the first instance of that task found
                        lock.acquire()
                        dynMatrix[whichVM].remove(url)
                        lock.release()

        os.system("truncate -s 0 /var/log/apache_access.log")

# -----------------------------------------------------------------------------
# Calculate which tasks belong on blacklist and update
# -----------------------------------------------------------------------------
def whiteAlg(statMatrix, dynMatrix, whitelist, lock):
    # Service Level Objective = 1 second
    SLO = 1

    while True:
        # Iterate for all backend servers
        for server in dynMatrix.keys():
            # Total summated execution times of current tasks
            sumTime = 0

            lock.acquire()
            # for tasks on server:
            for url in dynMatrix[server]:
                if url in statMatrix:
                    # Find task's estimated ex. time and add to total
                    sumTime += int(statMatrix[url])
            lock.release()

            for url in statMatrix.keys():
                # Individual time of specific task
                time = float(statMatrix[url])

                # If task will cause server to exceed SLO
                if str(server) not in whitelist[url] and time + sumTime > SLO:
                    print(f"Adding server {server} to URL \"{url}\"'s whitelist.")

                    # Add the task to the server's blacklist
                    whitelist[url] += server

                # Else remove it from server's blacklist if it is there
                elif str(server) in whitelist[url] and time + sumTime < SLO:
                    print(f"Removing server {server} from URL \"{url}\"'s whitelist.")

                    whitelist[url].replace(server, "")
                                
# -----------------------------------------------------------------------------
# Send blacklist data to clients
# -----------------------------------------------------------------------------
def comms(whitelist, lock):
    HOST = 'smartdrop'
    PORT = 8080

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, PORT))

        s.listen()

        conn, addr = s.accept()

        with conn:
            print('Connected by: ', addr)

            # Main loop
            while True:
                # Receive 1
                # print("Waiting for HAProxy...")
                message = receiveMessage(conn)
                # print(f"Message 1 received from HAProxy: {message}")

                # Set lock
                # print("HAProxy requests lock. Setting...")
                lock.acquire()

                # Offload whitelist data
                fileWrite(whitelist)

                # Send 1
                # print("Sending message 1 to HAProxy...")
                sendMessage(conn, b'1')
                # print("Message 1 sent to HAProxy.")

                # Receive 2
                # print("Waiting for HAProxy...")
                message = receiveMessage(conn)
                # print(f"Message 2 received from HAProxy: {message}")

                # Send 2
                # print("Sending message 2...")
                sendMessage(conn, b'2')
                # print("Message 2 sent to HAProxy.\nData transfer complete.")

                # Release lock
                lock.release()

# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------

def detectServers():
    SOCKET = 'TCP:haproxy:90'
    detect = subprocess.run('echo "show servers state" | socat {} stdio'.format(SOCKET), \
        shell = True, stdout = subprocess.PIPE).stdout.decode('utf-8')
    return detect.count('web_servers')

def constructGlobals(statMatrix, dynMatrix, whitelist):
    # Detect number of backend servers
    # srvCount = detectServers()
    # if srvCount < 1: raise INVALID_SERVER_COUNT

    srvCount = 7

    with open('requests.csv', 'r') as file:
        reader = csv.reader(file)

        # Skip header
        next(reader)

        for url, time, _ in reader:
            # Convert from microseconds to seconds
            statMatrix[url] = str((int(time) / 1e6))
            whitelist[url] = ""

        for server in range(srvCount):
            dynMatrix[server + 1] = []

def fileWrite(whitelist):
    t = '' # Simplify dict to list object
    for url in whitelist.keys():
        t += url
        t += ','
        if whitelist[url] == '': t += '0'
        else: t += whitelist[url]
        t += ','

    t = t[:-1]
    t += '\0'

    # Offload data to file
    # print("Writing to /Whitelist/whitelist.csv...")
    with open("/Whitelist/whitelist.csv", "r+") as file:
        file.truncate(0)
        file.write(t)
    # print("...done.")

def sendMessage(conn, message):
    total_sent = 0
    while total_sent < MSGLEN:
        sent = conn.send(message[total_sent:])

        if sent == 0: raise RuntimeError("Socket connection broken.")

        total_sent = total_sent + sent

    return

def receiveMessage(conn):
    chunks = []
    bytes_received = 0
    while bytes_received < MSGLEN:
        chunk = conn.recv(min(MSGLEN - bytes_received, 2048))

        if chunk == b'': raise RuntimeError("Socket connection broken.")

        # print(f"New chunk has arrived. Size: {len(chunk)}")

        chunks.append(chunk)

        bytes_received = bytes_received + len(chunk)

        # print(f"bytes_received: {bytes_received}")

    return b''.join(chunks)

if __name__ == '__main__':
    main()
