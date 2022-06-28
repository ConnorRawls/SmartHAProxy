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
  -predicted_time
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

class TaskType:
    def __init__(self, method, url, query, ex_size, size_stdev, ex_time, time_stdev):
        self.method = method
        self.url = url
        self.query = query
        self.ex_size = ex_size
        self.size_stdev = size_stdev
        self.ex_time = ex_time
        self.time_stdev = time_stdev

class Instance:
    def __init__(self, method, url, query, ex_size, size_stdev, ex_time, \
        time_stdev, server, workload, predicted_time, cpu_usage):
        self.method = method
        self.url = url
        self.query = query
        self.ex_size = ex_size
        self.size_stdev = size_stdev
        self.ex_time = ex_time
        self.time_stdev = time_stdev
        self.server = server
        self.workload = workload
        self.predicted_time
        self.cpu_usage = cpu_usage

    def toList():
        list_str = (f'{self.method},{self.url},{self.query},{self.ex_size},'
                    f'{self.size_stdev},{self.ex_time},{self.time_stdev},'
                    f'{self.server},{self.workload},{self.predicted_time},'
                    f'{self.cpu_usage}')
        return list_str

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
        predicted_time = m.dict()
        # Master Lock TM
        wl_lock = Lock()
        pt_lock = Lock()
        cpu_lock = Lock()
        # GBDT model
        model = pickle.load(open('GBDT.sav', 'rb'))

        init(time_matrix, time_stdev, size_matrix, size_stdev, workload, \
            cpu_usage, predicted_time, whitelist, m)

        # Multiprocessing mumbo jumbo
        proc1 = Process(target = taskEvent, args = (time_matrix, workload, \
            cpu_usage, predicted_time, wl_lock, pt_lock, cpu_lock))
        proc2 = Process(target = cpuUsage, args = (cpu_usage, cpu_lock))
        proc3 = Process(target = comms, args = (time_matrix, time_stdev, \
            size_matrix, size_stdev, cpu_usage, workload, predicted_time, \
            whitelist, wl_lock, pt_lock, cpu_lock, model))

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
def taskEvent(time_matrix, workload, cpu_usage, predicted_time, wl_lock, pt_lock, \
    cpu_lock):
    method, query, url, server = None
    record = {}
    status_key = {'+' : 'new', '>' : 'complete', '-' : 'sent'}
    task_count = 0
    total_response = 0
    error_count = 0

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
                method, query, url, server, error = None
                new_instance = True

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
                    if task_id in record:
                        method = record[task_id].method
                        url = record[task_id].url
                        query = record[task_id].query
                        server = record[task_id].server
                        new_instance = False
                    else:
                        method, query, url, server, error = parseLine(line, \
                            time_matrix)
                        if error == True:
                            error_count += 1
                            continue
                except IndexError:
                    error_count += 1
                    continue                

                # Response time
                if not new_instance:
                    try:
                        actual_time = line[3].replace(' ', '')
                        try: float(actual_time)
                        except ValueError:
                            actual_time = 'NULL'
                    except IndexError:
                        error_count += 1
                        continue

                # Insert task
                if status == 'new':
                    try:
                        key = [method,url,query]
                        task_type = profile_matrix[key]
                        wl_lock.acquire()
                        workload[server] += task_type.ex_time
                        cpu_lock.acquire()
                        record[task_id] = Instance(method, url, query, task.ex_size, \
                            task.size_stdev, task.ex_time, task.time_stdev, server, \
                            workload[server].value, predicted_time[][], \
                            cpu_usage[server].value)
                        wl_lock.release()                        
                        cpu_lock.release()
                    except KeyError:
                        error_count += 1

                # Task completion
                else:
                    try:
                        key = [method,url,query]
                        task_type = profile_matrix[key]
                        wl_lock.acquire()
                        workload[server] -= task_type.ex_time
                        wl_lock.release()
                        # *** WHAT ARE THE UNITS BEING LOGGED ***                       
                        record_file.write(record[task_id].toList() + \
                            f',{actual_response}\n')
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
def comms(time_matrix, stdev_matrix, cpu_usage, workload, predicted_time, \
    whitelist, wl_lock, pt_lock, cpu_lock, model):
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
                    whitelist, predicted_time, model)

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
        predicted_time, model):
    # Service Level Objective = 1 second
    SLO = 1

    GBDT(time_matrix, stdev_matrix, cpu_usage, workload, predicted_time, \
        model)

    # Iterate for all tasks
    for task in predicted_time.keys():
        # Iterate for all servers
        for server in predicted_time[task].keys():
            # If server can't satisfy task's deadline
            if server in whitelist[task] and \
                predicted_time[task][server] >= SLO:
                # Remove it from server's whitelist if it is there
                whitelist[task].remove(server)

            elif server not in whitelist[task] and \
                predicted_time[task][server] < SLO:
                # Add the task to the server's whitelist
                whitelist[task].append(server)

# Gradient Boosted Decision Tree
# -----------------------------------------------------------------------------
# Predict task types' response time on each server
def GBDT(time_matrix, stdev_matrix, cpu_usage, workload, predicted_time, \
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
        for (task, row) in zip(predicted_time.keys(), output_data):
            task = predicted_time[task]
            task[server] = row

# Utilities
# -----------------------------------------------------------------------------
# How many backend servers are running
def detectServers():
    SOCKET = 'TCP:haproxy:90'
    detect = subprocess.run('echo "show servers state" | socat {} stdio'.format(SOCKET), \
        shell = True, stdout = subprocess.PIPE).stdout.decode('utf-8')
    return detect.count('web_servers')

def parseLine(line, time_matrix):
    methods = ['GET', 'POST']
    # Query search patterns
    q_patterns = '\?wc-ajax=add_to_cart|\?wc-ajax=get_refreshed_fragments'
    method, query, url, server, error = None

    # Method
    try:
        method = line[1].replace.replace(' ', '')
        if method not in methods:
            error = True
            return method, query, url, server, error
    except IndexError:
        error = True
        return method, query, url, server, error

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
            error = True
            return method, query, url, server, error
    except IndexError:
        error = True
        return method, query, url, server, error

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
            error = True
            return method, query, url, server, error
    except IndexError:
        error = True
        return method, query, url, server, error

    # Server
    try:
        server = line[-1][-1].replace(' ', '').replace('\n', '')
        try: int(server)
        except ValueError:
            error = True
            return method, query, url, server, error
    except IndexError:
        error = True
        return method, query, url, server, error
    except KeyError:
        error = True
        return method, query, url, server, error

    return method, query, url, server, error

# Construct shared variables
def init(time_matrix, stdev_matrix, workload, cpu_usage, \
    predicted_time, whitelist, m):
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
        predicted_time[task] = m.dict()
        for server in workload.keys():
            predicted_time[task][server] = 0

# Get latest update to logfile
def logRead(file):
    file.seek(0, 2)

    while True:
        line = file.readline()
        if not line: continue
        yield line

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
