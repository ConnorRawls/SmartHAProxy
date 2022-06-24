'''
TODO: 
Fix detectServers()
If task_id is found, immediately pull features from record rather than parsing log

-------------------------------------
Author: Connor Rawls
Email: connorrawls1996@gmail.com
Organization: University of Louisiana
-------------------------------------

Capture task-related events and determine which servers will be able to satisfy
task types based upon SLO requirements (1 sec). Communicate this information with
client through UNIX sockets.

Three processes run concurrently:
  -taskEvent
  -cpuUsage
  -comms
Six objects are referenced globally:
  -time_matrix
  -stdev_matrix
  -workload
  -cpu_usage
  -predicted_response
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
import itertools
from datetime import datetime
from multiprocessing import Process, Manager, Lock
import libvirt
import pickle
import numpy as np
from sklearn.ensemble import GradientBoostingRegressor

MSGLEN = 1
SRVCOUNT = 7

class Task:
    def __init__(self, method, url, query, ex_size, size_stdev, ex_time, time_stdev):
        self.method = method
        self.url = url
        self.query = query
        self.ex_size = ex_size
        self.size_stdev = size_stdev
        self.ex_time = ex_time
        self.time_stdev = time_stdev

def main():
    with Manager() as m:
        # Profiled Response Time per task type
        # (Used for workload calc.)
        time_matrix = m.dict()
        time_stdev = m.dict()
        size_matrix = m.dict()
        size_stdev = m.dict()
        # Expected response time of backend servers
        # (Summation of PRTs)
        workload = m.dict()
        # CPU utilization stamp at time of instance dispatch
        cpu_usage = m.dict()
        # Key is task type and value are servers task is allowed to dispatch to
        whitelist = m.dict()
        # Rows = Task type
        # Columns = Server
        predicted_response = m.dict()
        # Master Lock TM
        wl_lock = Lock()
        cpu_lock = Lock()
        # GBDT model
        model = pickle.load(open('GBDT.sav', 'rb'))

        init(time_matrix, time_stdev, size_matrix, size_stdev, workload, \
            cpu_usage, predicted_response, whitelist, m)

        # Multiprocessing mumbo jumbo
        proc1 = Process(target = taskEvent, args = (time_matrix, workload, \
            cpu_usage, predicted_response, wl_lock, cpu_lock))
        proc2 = Process(target = cpuUsage, args = (cpu_usage, cpu_lock))
        proc3 = Process(target = comms, args = (time_matrix, time_stdev, \
            size_matrix, size_stdev, cpu_usage, workload, predicted_response, \
            whitelist, wl_lock, cpu_lock, model))

        start_time = datetime.now()
        print(f"Commencing Smartdrop [{start_time}].")

        proc1.start()       # Start listening for task events
        proc2.start()       # Start observing hardware metrics
        proc3.start()       # Start listening for socket messages
        proc1.join()
        proc2.join()
        proc3.join()
        proc1.terminate()   # Stop listening for task events
        proc2.terminate()   # Stop observing hardware metrics
        proc3.terminate()   # Stop listening for socket messages

# Process 1
# -----------------------------------------------------------------------------
# Monitor task-related events
def taskEvent(time_matrix, workload, cpu_usage, predicted_response, wl_lock, cpu_lock):
    # URL, expected execution time, expected std. dev., expected response time,
    # server, CPU usage, actual response
    record = {}
    actual_time = ''
    status_key = {'+' : 'new', '>' : 'complete', '-' : 'sent'}
    methods = ['GET', 'POST']
    # Query search patterns
    q_patterns = '\?wc-ajax=add_to_cart|\?wc-ajax=get_refreshed_fragments'
    task_count = 0
    total_response = 0
    error_count = 0
    possible_srvs = []

    for server in workload.keys():
        possible_srvs.append(str(server))

    # Clear logs
    os.system("truncate -s 0 /var/log/apache_access.log")

    with open('records.csv', 'a') as record_file:
        record_file.write('method,url,query,server,predicted response time,' + \
            'actual response time\n')

        with open('/var/log/apache_access.log', 'r') as log_file:
            lines = logRead(log_file)

            # MAIN LOOP: Parse log file
            for line in lines:
                line = re.split(',|\s|\|', line)

                # Status
                try:
                    status = status_key[line[0][0].replace(' ', '')]
                    if status == 'sent': continue
                except IndexError:
                    error_count += 1
                    continue
                except KeyError:
                    error_count += 1
                    continue

                # Task ID
                try:
                    task_id = line[0][1:].replace(' ', '')
                except IndexError:
                    error_count += 1
                    continue

                # Method
                try:
                    method = line[1].replace.replace(' ', '')
                    if method not in methods:
                        method = unknownMethod(task_id,, record)
                        if method == 'UNKNOWN':
                            error_count += 1
                            continue
                except IndexError:
                    error_count += 1
                    continue

                # Query
                try:
                    found = False
                    query = re.search(q_patterns, line[2].replace(' ', ''))
                    try:
                        query = query.group()
                        line[2] = line[2].replace(query, '')
                    except AttributeError: query = ''
                    for key, value in time_matrix.items():
                        if type(key) in [list, tuple, dict] and query in key:
                            found = True
                            break
                    if found == False:
                        query = unknownQuery(task_id, record)
                        if query == 'UNKNOWN':
                            error_count += 1
                            continue
                except IndexError:
                    query = unknownQuery(task_id, record)
                    if query == 'UNKNOWN':
                        error_count += 1
                        continue

                # URL
                try:
                    found = False
                    url = line[2].replace(' ', '')
                    if (query != '' or url == '/wp-profiling/') \
                        and 'index.php' not in url:
                        url = url + 'index.php'
                    for key, value in time_matrix.items():
                        if type(key) in [list, tuple, dict] and url in key:
                            found = True
                            break
                    if found == False:
                        url = unknownURL(task_id, record)
                        if url == 'UNKNOWN':
                            error_count += 1
                            continue
                except IndexError:
                    url = unknownURL(task_id, record)
                    if url = 'UNKNOWN':
                        error_count += 1
                        continue

                # Server
                try:
                    server = line[2].replace(' ', '')
                    if server not in possible_srvs:
                        server = unknownServer(task_id, record)
                        if server == 'UNKNOWN':
                            error_count += 1
                            continue
                except IndexError:
                    error_count += 1
                    server = unknownServer(task_id, record)
                    if server == 'UNKNOWN':
                        continue

                # Response time
                try:
                    actual_response = line[3].replace(' ', '').replace('\n', '')
                    if not isfloat(actual_response):
                        if task_id in record.keys():
                            actual_response = total_response / task_count
                        else:
                            error_count += 1
                            continue
                except IndexError:
                    error_count += 1
                    if task_id in record.keys():
                        actual_response = total_response / task_count
                    else:
                        continue

                # Insert task
                if '-' in str(actual_response):
                    try:
                        wl_lock.acquire()
                        workload[server] += time_matrix[url]
                        wl_lock.release()
                        cpu_lock.acquire()
                        record[task_id] = url + ',' + str(time_matrix[url]) + ',' + \
                            str(stdev_matrix[url]) + ',' + str(workload) + \
                            ',' + str(server) + ',' + str(cpu_usage[server].value) + ','
                        cpu_lock.release()
                    except KeyError:
                        error_count += 1

                # Task completion
                else:
                    try:
                        if not task_id in record.keys(): continue
                        wl_lock.acquire()
                        workload[server] -= time_matrix[url]
                        wl_lock.release()
                        record[task_id] += str(float(actual_response) / 1e6)
                        record_file.write(record[task_id] + '\n')
                        del record[task_id]
                        total_response += int(actual_response)
                        task_count += 1
                    except KeyError:
                        error_count += 1

# Process 2
# -----------------------------------------------------------------------------
# Monitor CPU utilization of backend server
def cpuUsage(cpu_usage, cpu_lock): 
    conn = libvirt.openReadOnly("qemu+ssh://root@hpcccloud1.cmix.louisiana.edu/system")
    while True:
        for server in cpu_usage.keys():
            domain = conn.lookupByName(server)

            time1 = time.time()
            clock1 = int(domain.info()[4])
            time.sleep(1.25)
            time2 = time.time()
            clock2 = int(domain.info()[4])
            cores = int(domain.info()[3])

            cpu_lock.acquire()
            cpu_usage[server] = round((clock2 - clock1) * 100 / ((time2 - time1) * cores * 1e9), 2)
            if cpu_usage[server] > 100: cpu_usage[server] = 100
            cpu_lock.release()
                                
# Process 3
# -----------------------------------------------------------------------------
# Send whitelist to load balancer
def comms(time_matrix, stdev_matrix, cpu_usage, workload, predicted_response, \
    whitelist, wl_lock, cpu_lock, model):
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

                # Set locks
                wl_lock.acquire()
                cpu_lock.acquire()

                # Calculate whitelist
                whiteAlg(time_matrix, stdev_matrix, cpu_usage, workload, \
                    whitelist, predicted_response, model)

                # Release locks
                wl_lock.release()
                cpu_lock.release()

                # Offload whitelist data
                fileWrite(whitelist)

                # Send 1
                sendMessage(conn, b'1')

                # Receive 2
                message = receiveMessage(conn)

                # Send 2
                sendMessage(conn, b'2')

# Whitelist Algorithm
# -----------------------------------------------------------------------------
# Calculate task whitelists
def whiteAlg(time_matrix, stdev_matrix, cpu_usage, workload, whitelist, \
        predicted_response, model):
    # Service Level Objective = 1 second
    SLO = 1

    GBDT(time_matrix, stdev_matrix, cpu_usage, workload, predicted_response, \
        model)

    # Iterate for all tasks
    for task in predicted_response.keys():
        # Iterate for all servers
        for server in predicted_response[task].keys():
            # If server can't satisfy task's deadline
            if server in whitelist[task] and \
                predicted_response[task][server] >= SLO:
                # Remove it from server's whitelist if it is there
                whitelist[task].remove(server)

            elif server not in whitelist[task] and \
                predicted_response[task][server] < SLO:
                # Add the task to the server's whitelist
                whitelist[task].append(server)

# Gradient Boosted Decision Tree
# -----------------------------------------------------------------------------
# Predict task types' response time on each server
def GBDT(time_matrix, stdev_matrix, cpu_usage, workload, predicted_response, \
    model):
    # N channel metric matrix
    # N = Number of servers
    for server in cpu_usage.keys():
        # Convert static metrics into list format
        time_buff = []
        stdev_buff = []
        for task in time_matrix.keys():
            time_buff.append(time_matrix[task])
            stdev_buff.append(time_matrix[task])

        # Convert CPU and workload metrics into list format
        cpu_buff = []
        wl_buff = []
        for _ in range(len(time_buff)):
            cpu_buff.append(cpu_usage[server])
            wl_buff.append(workload[server])

        # Use each metric as a column in matrix
        input_data = np.column_stack((time_buff, stdev_buff, cpu_buff, wl_buff))

        # Perform ML inference
        output_data = []
        for row in input_data:
            output_data.append(abs(model.predict([row])))
        for (task, row) in zip(predicted_response.keys(), output_data):
            task = predicted_response[task]
            task[server] = row

# Utilities
# -----------------------------------------------------------------------------
# How many backend servers are running
def detectServers():
    SOCKET = 'TCP:haproxy:90'
    detect = subprocess.run('echo "show servers state" | socat {} stdio'.format(SOCKET), \
        shell = True, stdout = subprocess.PIPE).stdout.decode('utf-8')
    return detect.count('web_servers')

# Construct shared variables
def init(time_matrix, stdev_matrix, workload, cpu_usage, \
    predicted_response, whitelist, m):
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
            workload['WP-Host'] = 0.1
            cpu_usage['WP-Host'] = 0
        else:
            workload['WP-Host-0' + str(server + 1)] = 0.1
            cpu_usage['WP-Host-0' + str(server + 1)] = 0

    for url in whitelist.keys():
        for server in range(SRVCOUNT):
            if server == 0: whitelist[url].append('WP-Host')
            else: whitelist[url].append('WP-Host-0' + str(server + 1))

    for task in time_matrix.keys():
        predicted_response[task] = m.dict()
        for server in workload.keys():
            predicted_response[task][server] = 0

# Get latest update to logfile
def logRead(file):
    file.seek(0, 2)

    while True:
        line = file.readline()
        if not line: continue
        yield line

# Unrecognized URL handler
def unknownURL(url, time_matrix, task_id, record):
    for key in time_matrix.keys():
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
        t += str(url)
        t += ','
        if not whitelist[url]:
            t += '0,'
        else:
            for server in whitelist[url]:
                if server == 'WP-Host':
                    t += '1'
                else:
                    t += str(server[-1])
            t += ','

    t = t[:-1]
    t += '\0'

    # Offload data to file
    with open("/Whitelist/whitelist.csv", "r+") as file:
        file.truncate(0)
        file.write(t)

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

        chunks.append(chunk)

        bytes_received = bytes_received + len(chunk)

    return b''.join(chunks)

if __name__ == '__main__':
    main()
