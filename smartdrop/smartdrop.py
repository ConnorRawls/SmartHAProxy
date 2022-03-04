# TODO
# Finish socket crap in comms
    # list().insert() does not work with Manager().list(). Find another way to prepend
    # our delimiter.
# Consider multiprocessing.Queue for dynMatrix.
# Clean way to stop the program
# Elegant error handling

# Author: Connor Rawls
# Email: connorrawls1996@gmail.com
# Organization: University of Louisiana

# Capture actual task (http request) list of each backend server and determine which
# tasks each server will not be able to satisfy based upon SLO requirements (1 sec).
# Communicate this information with client through UNIX sockets.
# Four processes run concurrently:
#   -haproxyEvent
#   -apacheEvent
#   -blackAlg
#   -comms
# Three objects are referenced globally:
#   -statMatrix
#   -dynMatrix
#   -blacklist

import os
import csv
import subprocess
import re
import socket
import json
from multiprocessing import Process, Manager, Lock

INVALID_SERVER_COUNT = Exception('Invalid server count detected.\nAre your servers running?')
SERVER_UNKNOWN_H = Exception('Unknown server name detected in HAProxy logs.\nMust be of the format "vm#"')
SERVER_UNKNOWN_A = Exception('Unknown server name detected in Apache logs.\nMust be of the format "vm#"')

whitelist = {}

def main():
    # Initialize static matrix
    # Contains tuples of possible tasks (uri) and their respective execution times
    # (offline profiled)
    statMatrix = Manager().dict()

    with open('requests.csv', 'r') as file:
        reader = csv.reader(file)

        # Skip header
        next(reader)

        for uri, time, dev in reader:
            statMatrix[uri] = time

    # Initialize dynamic matrix and blacklist
    # Contains lists of currently being executed tasks on each backend server and tasks
    # that are to be avoided on each server respectively
    dynMatrix = Manager().list()
    blacklist = Manager().list()
    
    # Detect number of backend servers
    # SOCKET = 'TCP:haproxy:90'
    # detect = subprocess.run('echo "show servers state" | socat {} stdio'.format(SOCKET), \
    #     shell = True, stdout = subprocess.PIPE).stdout.decode('utf-8')
    # srvCount = detect.count('web_servers')

    # if srvCount < 1: raise INVALID_SERVER_COUNT

    srvCount = 7

    for whichVM in range(srvCount):
        whichVM += 1

        name = 'vm' + str(whichVM)

        dynMatrix.append([])
        blacklist.append([])

    # Truncate logs
    os.system("truncate -s 0 /var/log/apache_access.log")
    os.system("truncate -s 0 /var/log/haproxy_access.log")

    # Master Lock TM
    lock = Lock()

    # Multiprocessing mumbo jumbo
    proc1 = Process(target = haproxyEvent, args = (dynMatrix, lock))
    proc2 = Process(target = apacheEvent, args = (dynMatrix, lock))
    proc3 = Process(target = blackAlg, args = (statMatrix, dynMatrix, blacklist, \
        lock))
    proc4 = Process(target = comms, args = (blacklist, lock, srvCount))

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

# ---------------------------------------------------------
# Add task to dynamic matrix
# ---------------------------------------------------------
def haproxyEvent(dynMatrix, lock):
    while True:
        with open('/var/log/haproxy_access.log', 'r') as file:
            reader = csv.reader(file)

            # Parse log file and add requests to dynMatrix
            for row in reader:
                if len(row) != 2: pass

                else:
                    server = row[0]
                    uri = row[1]

                    if not re.match('^vm[0-9]+$', server): raise SERVER_UNKNOWN_H

                    whichVM = int(server[2]) - 1

                    lock.acquire()
                    dynMatrix[whichVM].append(uri)
                    lock.release()

        # Truncate log
        os.system("truncate -s 0 /var/log/haproxy_access.log")

# ---------------------------------------------------------
# Remove task from dynamic matrix
# ---------------------------------------------------------
def apacheEvent(dynMatrix, lock):
    while True:
        # Log contains tuples of backend VM, uri, execution time
        with open('/var/log/apache_access.log', 'r') as file:
            reader = csv.reader(file)

            # for server, uri, actualTime in reader:
            for row in reader:
                if len(row) != 3: pass

                else:
                    server = row[0]
                    uri = row[1]
                    actualTime = row[2]

                    if not re.match('^hpcclab[0-9]+$', server): raise SERVER_UNKNOWN_A

                    # Determine the VM that the tuple belongs to
                    whichVM = int(server[7]) - 1

                    # If the uri matches a request in the VM's tasklist
                    # if uri in dynMatrix[whichVM].tasks:
                    if uri in dynMatrix[whichVM]:
                        # Remove the first instance of that task found
                        lock.acquire()
                        dynMatrix[whichVM].remove(uri)
                        lock.release()

        os.system("truncate -s 0 /var/log/apache_access.log")

# ---------------------------------------------------------
# Calculate which tasks belong on blacklist and update
# ---------------------------------------------------------
def blackAlg(statMatrix, dynMatrix, blacklist, lock):
    # Service Level Objective = 1 second
    SLO = 1

    while True:
        # Iterate for all backend servers
        whichVM = 0
        for server in dynMatrix:
            # Total summated execution times of current tasks
            sumTime = 0

            lock.acquire()
            # for uri in server.tasks:
            for uri in server:
                if uri in statMatrix:
                    # Find task's estimated ex. time and add to total
                    sumTime += int(statMatrix[uri])
            lock.release()

            for uri in statMatrix.keys():
                # Individual time of specific task
                time = int(statMatrix[uri])

                # If task will cause server to exceed SLO
                if uri not in blacklist[whichVM] and time + sumTime > SLO:
                    # Add the task to the server's blacklist
                    blacklist[whichVM].append(uri)

                    if uri in whitelist:
                        whitelist[uri].append(whichVM)
                    else:
                        whitelist[uri] = whichVM

                # Else remove it from server's blacklist if it is there
                elif uri in blacklist[whichVM] and time + sumTime < SLO:
                    blacklist[whichVM].remove(uri)

                    if uri in whitelist:
                        whitelist[uri].remove(whichVM)
                                
            whichVM += 1

# ---------------------------------------------------------
# Send blacklist data to clients
# ---------------------------------------------------------
def comms(blacklist, lock, srvCount):
    HOST = 'smartdrop'
    PORT = 8080

    while True: # Is this loop necessary?
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((HOST, PORT))

            s.listen()

            conn, addr = s.accept()

        with conn:
            print('Connected by: ', addr)

            while True:
                # If client requests blacklist
                data = conn.recv(1024)

                if not data:
                    break
                
                else: # Is this necessary?
                    lock.acquire()

                    # Iterate through blacklist and # prepend list with VM + number
                    # (our delimiter)
                    count = 0
                    for whichVM in range(srvCount):
                        t = blacklist[count]            # Must copy list first (lame)
                        t.insert(0, 'VM' + str(count))  # To make changes
                        blacklist[count] = t            # Then copy back

                        count += 1

                    t = []
                    for url in whitelist:
                        t.append('|')
                        t.append(url)
                        t.append('|')
                        t.append(whitelist[url])

                    # Conversion to transmittable format
                    # bl_bytes = json.dumps(blacklist._getvalue()).encode('utf-8')
                    bl_bytes = json.dumps(t).encode('utf-8')

                    # Send info
                    conn.sendall(bl_bytes)

                    lock.release()

if __name__ == '__main__':
    main()