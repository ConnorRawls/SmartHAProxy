'''
TODO: Fix detectServers()

-------------------------------------
Author: Connor Rawls
Email: connorrawls1996@gmail.com
Organization: University of Louisiana
-------------------------------------

Capture task-related events and determine which servers will be able to satisfy
task types based upon SLO requirements (1 sec). Communicate this information with
client through UNIX sockets.

Three processes run concurrently:
  -haproxyEvent
  -whiteAlg
  -comms
Four objects are referenced globally:
  -time_matrix
  -stdev_matrix
  -expected_response
  -whitelist
'''

import os
import csv
import subprocess
import re
import socket
import json
import time
import sys
from multiprocessing import Process, Manager, Lock

MSGLEN = 1
SRVCOUNT = 1

def main():
    with Manager() as m:
        # Expected execution time per task type
        time_matrix = m.dict()
        # Expected std. dev. of execution time per task type
        stdev_matrix = m.dict()
        # Expected response time of backend servers - task's expected execution
        # time
        expected_response = m.dict()
        # CPU utilization stamp at time of instance dispatch
        cpu_usage = m.dict()
        # Contains URL (key) and servers (value) tasks are allowed to dispatch to
        whitelist = m.dict()
        # Master Lock TM
        er_lock = Lock()
        cpu_lock = Lock()

        initGlobals(time_matrix, stdev_matrix, expected_response, cpu_usage, \
            whitelist, m)

        # Multiprocessing mumbo jumbo
        proc1 = Process(target = haproxyEvent, args = (time_matrix, stdev_matrix, \
            expected_response, cpu_usage, er_lock, cpu_lock))
        proc2 = Process(target = cpuUsage, args = (cpu_usage, cpu_lock))
        proc3 = Process(target = whiteAlg, args = (time_matrix, expected_response, \
            cpu_usage, whitelist, er_lock, cpu_lock))
        proc4 = Process(target = comms, args = (whitelist, er_lock, cpu_lock))

        print("Commencing Smartdrop.")

        proc1.start()       # Start listening for task events
        proc2.start()       # Start observing hardware metrics
        proc3.start()       # Start whitelist algorithm
        proc4.start()       # Start listening for socket messages
        proc1.join()
        proc2.join()
        proc3.join()
        proc4.join()
        proc1.terminate()   # Stop listening for task events
        proc2.terminate()   # Stop observing hardware metrics
        proc3.terminate()   # Stop whitelist algorithm
        proc4.terminate()   # Stop listening for socket messages

# Process 1
# -----------------------------------------------------------------------------
# Monitor task-related events
def haproxyEvent(time_matrix, stdev_matrix, expected_response, cpu_usage, \
    er_lock, cpu_lock):
    # Instance's actual response time
    actual_response = ''
    # Internal records for managing task instances
    # URL, expected execution time, expected std. dev., expected response time,
    # server, CPU usage, actual response
    record = {}
    # Error protocol variables
    task_count = 0
    total_response = 0
    error_count = 0

    # Clear log
    os.system("truncate -s 0 /var/log/haproxy_access.log")

    with open('records.csv', 'a') as record_file:
        record_file.write('task type,expected execution time,expected variance,' + \
            'expected response time,actual response time')

        with open('/var/log/haproxy_access.log', 'r') as log_file:
            lines = logRead(log_file)

            # MAIN LOOP: Parse log file
            for line in lines:
                line.replace(' ', '')
                line = line.split(',')

                # Task instance ID
                try:
                    task_id = line[0]
                    if not isint(task_id):
                        error_count += 1
                        print('\nTask ID is not an integer. Line:\n', line)
                        print('Error count: ', error_count)
                        continue
                    if not int(task_id) >= 0:
                        error_count += 1
                        print('\nTask ID is not positive. Line:\n', line)
                        print('Error count: ', error_count)
                        continue
                except IndexError:
                    error_count += 1
                    print('\nIndexError at ID value. Line:\n', line)
                    print('Error count: ', error_count)
                    continue

                # URL
                try:
                    url = line[1]
                    if url not in time_matrix.keys():
                        url = unknownURL(url, time_matrix, task_id, record)
                        if url == 'UNKNOWN':
                            error_count += 1
                            print('\nUnknown URL. Line:\n', line)
                            print('Error count: ', error_count)
                            continue
                except IndexError:
                    error_count += 1
                    print('\nIndexError at URL. Line:\n', line)
                    print('Error count: ', error_count)
                    url = unknownURL(url, time_matrix, task_id, record)
                    if url == 'UNKNOWN':
                        print('Could not recover :(')
                        continue

                # Server
                try:
                    server = line[2]
                    if not re.match('^WP-Host[1-7]$', server):
                        server = unknownServer(task_id, record)
                        if server == 'UNKNOWN':
                            error_count += 1
                            print('\nUnknown server. Line:\n', line)
                            print('Error count: ', error_count)
                            continue
                except IndexError:
                    error_count += 1
                    print('\nIndexError at server name. Line:\n', line)
                    print('Error count: ', error_count)
                    server = unknownServer(task_id, record)
                    if server == 'UNKNOWN':
                        print('Could not recover :(')
                        continue

                # Response time
                try:
                    actual_response = line[3]
                    if not isfloat(actual_response):
                        if task_id in record.keys():
                            actual_response = total_response / task_count
                        else:
                            error_count += 1
                            print('\nUnknown response. Line:\n', line)
                            print('Error count: ', error_count)
                            continue
                except IndexError:
                    error_count += 1
                    print('IndexError at response value. Line:\n ', line)
                    print('Error count: ', error_count)
                    if task_id in record.keys():
                        actual_response = total_response / task_count
                    else:
                        print('Could not recover :(')
                        continue

                # Insert task
                if '-' in str(actual_response):
                    try:
                        er_lock.acquire()
                        expected_response[server] += time_matrix[url]
                        er_lock.release()
                        cpu_lock.acquire()
                        record[task_id] = url + ',' + str(time_matrix[url]) + ',' + \
                            str(var_matrix[url]) + ',' + str(expected_response) + \
                            ',' + str(server) + ',' + str(cpu_usage[server].value) + ','
                        cpu_lock.release()
                    except KeyError:
                        error_count += 1
                        print('\nKeyError at inserting task. Line:\n', line)
                        print('Error count: ', error_count)

                # Task completion
                else:
                    try:
                        if not task_id in record.keys(): continue
                        er_lock.acquire()
                        expected_response[server] -= time_matrix[url]
                        er_lock.release()
                        record[task_id] += str(float(actual_response) / 1e6)
                        record_file.write(record[task_id] + '\n')
                        del record[task_id]
                        total_response += int(actual_response)
                        task_count += 1
                    except KeyError:
                        error_count += 1
                        print('\nKeyError at task completion. Line:\n', line)
                        print('Error count: ', error_count)

# Process 2
# -----------------------------------------------------------------------------
# Monitor CPU utilization of backend server
def cpuUsage(cpu_usage, cpu_lock): 
    conn = libvirt.openReadOnly("qemu+ssh://root@hpcccloud1.cmix.louisiana.edu/system")
    for server in cpu_usage.keys():
        cpu_lock.acquire()
        cpu_usage[server].value = 0
        cpu_lock.release()

    while True:
        for server in cpu_usage.keys():
            print('Domain name: ', server)
            domain = conn.lookupByName(server)

            time1 = time.time()
            clock1 = int(domain.info()[4])
            time.sleep(1.25)
            time2 = time.time()
            clock2 = int(domain.info()[4])
            cores = int(domain.info()[3])

            cpu_lock.acquire()
            cpu_usage[server].value = round((clock2 - clock1) * 100 / ((time2 - time1) * cores * 1e9), 2)
            if cpu_usage[server].value > 100: cpu_usage[server].value = 100
            cpu_lock.release()

# Process 3
# -----------------------------------------------------------------------------
# Calculate task whitelists
def whiteAlg(time_matrix, expected_response, cpu_usage, whitelist, er_lock, \
    cpu_lock):
    # Service Level Objective = 1 second
    SLO = 1

    while True:
        # Iterate for all backend servers
        for server in expected_response.keys():
            # Iterate for all task types
            for url in whitelist.keys():
                er_lock.acquire()
                execution = float(time_matrix[url])
                response = float(expected_response[server])

                # If task will cause server to exceed SLO
                if server in whitelist[url] and execution + response >= SLO:
                    # Remove it from server's whitelist if it is there
                    print(f"Removing server {server} from URL \"{url}\"'s whitelist.")
                    whitelist[url].remove(server)

                elif server not in whitelist[url] and execution + response < SLO:
                    print(f"Adding server {server} to URL \"{url}\"'s whitelist.")
                    print('Whitelist: ', whitelist[url])
                    print('Server: ', server)
                    # Add the task to the server's whitelist
                    whitelist[url].append(server)

                er_lock.release()
                                
# Process 4
# -----------------------------------------------------------------------------
# Send whitelist to load balancer
def comms(whitelist, er_lock, cpu_lock):
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

                # Set er_lock
                # print("HAProxy requests er_lock. Setting...")
                er_lock.acquire()

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

                # Release er_lock
                er_lock.release()

# Utilities
# -----------------------------------------------------------------------------
# How many backend servers are running
def detectServers():
    SOCKET = 'TCP:haproxy:90'
    detect = subprocess.run('echo "show servers state" | socat {} stdio'.format(SOCKET), \
        shell = True, stdout = subprocess.PIPE).stdout.decode('utf-8')
    return detect.count('web_servers')

# Construct shared variables
def initGlobals(time_matrix, stdev_matrix, expected_response, cpu_usage, \
    whitelist, m):
    # Detect number of backend servers
    # srvCount = detectServers()
    # if srvCount < 1:
    #    sys.exit('\nInvalid server count. Are your servers running?')

    with open('requests.csv', 'r') as file:
        reader = csv.reader(file)

        # Skip header
        next(reader)

        for url, time, stdev in reader:
            # Convert from microseconds to seconds
            time_matrix[url] = float(time) / 1e6
            stdev_matrix[url] = float(stdev) / 1e6
            whitelist[url] = m.list()

        for server in range(SRVCOUNT):
            if server == 0:
                expected_response['WP-Host'] = 0
                cpu_usage['WP-Host'] = m.Value('d', 0.0)
            else:
                expected_response['WP-Host' + str(server + 1)] = 0
                cpu_usage['WP-Host' + str(server + 1)] = m.Value('d', 0.0)

        for url in whitelist.keys():
            for server in range(SRVCOUNT):
                if server == 0: whitelist[url].append('WP-Host')
                else: whitelist[url].append('WP-Host' + str(server + 1))

# Get latest update to logfile
def logRead(file):
    file.seek(0, 2)

    while True:
        line = file.readline()
        if not line: continue
        yield line

# Unrecognized URL handler
def unknownURL(url, time_matrix, task_id, record):
    for key in time_matrix:
        if key in url:
            return key

    if task_id in record.keys():
        buffer = record[task_id].split(',')
        return buffer[0]

    return 'UNKNOWN'

# Unknown server handler
def unknownServer(task_id, record):
    if task_id in record.keys():
        buffer = record[task_id].split(',')
        return buffer[4]

    return 'UNKNOWN'

# Is variable integer?
def isint(string):
    try:
        int(string)
        return True
    except ValueError:
        return False

# Is variable float?
def isfloat(string):
    try:
        float(string)
        return True
    except ValueError:
        return False

# Write data to file
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

# Socket send
def sendMessage(conn, message):
    total_sent = 0
    while total_sent < MSGLEN:
        sent = conn.send(message[total_sent:])

        if sent == 0: raise RuntimeError("Socket connection broken.")

        total_sent = total_sent + sent

    return

# Socket receive
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