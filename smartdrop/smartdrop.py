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
import pandas as pd
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
        # Profiled information per task type
        profile_matrix = {}
        # Expected response time of backend servers
        # (Summation of PRTs)
        workload = m.dict()
        # CPU utilization stamp at time of instance dispatch
        cpu_usage = m.dict()
        # Rows = Task type
        # Columns = Server
        predicted_time = m.dict()
        # Key is task type and value are servers task is allowed to dispatch to
        whitelist = {}
        # Master Lock TM
        wl_lock = Lock()    # Workload
        pt_lock = Lock()    # Predicted Time
        cpu_lock = Lock()   # CPU Usage
        # GBDT model
        model = pickle.load(open('GBDT.sav', 'rb'))

        init(profile_matrix, workload, cpu_usage, predicted_time, whitelist, m)

        # Multiprocessing mumbo jumbo
        proc1 = Process(target = taskEvent, args = (profile_matrix, workload, \
            cpu_usage, predicted_time, wl_lock, pt_lock, cpu_lock))
        proc2 = Process(target = cpuUsage, args = (cpu_usage, cpu_lock))
        proc3 = Process(target = comms, args = (profile_matrix, workload, \
            cpu_usage, predicted_time, whitelist, wl_lock, pt_lock, cpu_lock, model))

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
def taskEvent(profile_matrix, workload, cpu_usage, predicted_time, wl_lock, 
    pt_lock, cpu_lock):
    method = query = url = server = None
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
                method = None # Don't know why we can't method, query, ... = None
                query = None
                url = None
                server = None
                error = None
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
                            profile_matrix)
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
                        key = f'{method},{url},{query}'
                        task_type = profile_matrix[key]
                        wl_lock.acquire()
                        workload[server] += task_type.ex_time
                        cpu_lock.acquire()
                        # Do we need to use workload.value & cpu_usage.value?
                        record[task_id] = Instance(method, url, query, task_type.ex_size, \
                            task_type.size_stdev, task_type.ex_time, task_type.time_stdev, server, \
                            workload[server], predicted_time[key][server], \
                            cpu_usage[server].value)
                        wl_lock.release()                        
                        cpu_lock.release()
                    except KeyError:
                        error_count += 1

                # Task completion
                else:
                    try:
                        key = f'{method},{url},{query}'
                        task_type = profile_matrix[key]
                        wl_lock.acquire()
                        workload[server] -= task_type.ex_time
                        wl_lock.release()
                        # *** WHAT ARE THE UNITS BEING LOGGED ***                       
                        record_file.write(record[task_id].toList() + \
                            f',{actual_time}\n')
                        del record[task_id]
                        total_response += int(actual_time)
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
            if server == '1': srv_name = 'WP-Host'
            else: srv_name = f'WP-Host-0{server}'
            domain = conn.lookupByName(srv_name)

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
def comms(profile_matrix, workload, cpu_usage, predicted_time, whitelist,
    wl_lock, pt_lock, cpu_lock, model):
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
                message = receiveMessage(conn)

                # Set locks
                wl_lock.acquire()
                cpu_lock.acquire()

                # Calculate whitelist
                whiteAlg(profile_matrix, cpu_usage, workload, predicted_time, \
                    model, whitelist)

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
def whiteAlg(profile_matrix, cpu_usage, workload, predicted_time, model, whitelist):
    # Service Level Objective = 1 second = 1,000,000 microseconds
    SLO = 1e6

    GBDT(profile_matrix, cpu_usage, workload, predicted_time, model)

    # Iterate for all tasks
    for task in predicted_time.keys():
        # Iterate for all servers
        for server in predicted_time[task].keys():
            # If server can't satisfy task's deadline
            if server in whitelist[task] and \
                predicted_time[task][server] >= SLO:
                # Remove it from server's whitelist if it is there
                whitelist[task].remove(server)
                print(f"Removing server {server} from task {task}"
                    f" (PRT: {predicted_time[task][server]})")

            elif server not in whitelist[task] and \
                predicted_time[task][server] < SLO:
                # Add the task to the server's whitelist
                whitelist[task].append(server)

# Gradient Boosted Decision Tree
# -----------------------------------------------------------------------------
# Predict task types' response time on each server
def GBDT(profile_matrix, cpu_usage, workload, predicted_time, model):
    # N channel metric matrix, where N = Number of servers
    for server in cpu_usage.keys():
        # Convert task features into list format
        method_buff = []
        url_buff = []
        query_buff = []
        size_buff = []
        size_stdev_buff = []
        time_buff = []
        time_stdev_buff = []
        for task_key in profile_matrix:
            task = profile_matrix[task_key]
            method_buff.append(task.method)
            url_buff.append(task.url)
            query_buff.append(task.query)
            size_buff.append(task.ex_size)
            size_stdev_buff.append(task.size_stdev)
            time_buff.append(task.ex_time)
            time_stdev_buff.append(task.time_stdev)

        # Convert CPU and workload into list format
        cpu_buff = []
        wl_buff = []
        # Remove this line when we know for sure -->
        for _ in profile_matrix:
            cpu_buff.append(cpu_usage[server])
            wl_buff.append(workload[server])

        df = pd.DataFrame(list(zip(method_buff, url_buff, query_buff, size_buff, \
            size_stdev_buff, time_buff, time_stdev_buff, wl_buff, cpu_buff)), \
            columns = ['Method', 'URL', 'Query', 'Size', 'SizeStdev', 'Time', \
            'TimeStdev', 'Workload', 'CPU'])
        df = df.replace('NULL', '')
        df = pd.get_dummies(df, columns = ['Method', 'URL', 'Query'], sparse = True)
        df = df.drop(columns = ['Query_'])

        # Use each metric as a column in matrix
        input_data = df.to_numpy()

        # Perform ML inference
        output_data = []
        # Each row is a task type
        for row in input_data:
            output_data.append(abs(model.predict([row])))
        # *** Are they in order?
        for (task, time_on_server) in zip(predicted_time.keys(), output_data):
            predicted_time[task][server] = time_on_server

# Utilities
# -----------------------------------------------------------------------------
# How many backend servers are running
def detectServers():
    SOCKET = 'TCP:haproxy:90'
    detect = subprocess.run('echo "show servers state" | socat {} stdio'.format(SOCKET), \
        shell = True, stdout = subprocess.PIPE).stdout.decode('utf-8')
    return detect.count('web_servers')

def parseLine(line, profile_matrix):
    methods = ['GET', 'POST']
    # Query search patterns
    q_patterns = '\?wc-ajax=add_to_cart|\?wc-ajax=get_refreshed_fragments'
    method = None
    query = None
    url = None
    server = None
    error = None

    # Method
    try:
        method = line[1].replace(' ', '')
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
        except AttributeError: query = 'NULL'
        for key, value in profile_matrix.items():
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
        for key, value in profile_matrix.items():
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
def init(profile_matrix, workload, cpu_usage, predicted_time, whitelist, m):
    # Detect number of backend servers
    # srvCount = detectServers()
    # if srvCount < 1:
    #    sys.exit('\nInvalid server count. Are your servers running?')

    with open('tasks.csv', 'r') as file:
        reader = csv.reader(file)

        # Skip header
        next(reader)

        # Profile Matrix and Whitelist
        for url, query, method, ex_size, size_stdev, ex_time, \
            time_stdev in reader:
            if query == '': query = 'NULL'
            key = f'{method},{url},{query}'
            profile_matrix[key] = TaskType(method, url, query, ex_size, \
                size_stdev, ex_time, time_stdev)
            whitelist[key] = []

    # Workload and CPU Usage
    for server in range(SRVCOUNT):
        workload[f'{server + 1}'] = 0.1
        cpu_usage[f'{server + 1}'] = 0.

    # Whitelist cont.
    for task in whitelist:
        for server in range(SRVCOUNT):
            whitelist[task].append(f'{server + 1}')

    for task in profile_matrix:
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
    for task in whitelist:
        t += str(task)
        t += ','
        if not whitelist[task]:
            t += '0\n'
        else:
            for server in whitelist[task]:
                    t += server
            t += '\n'

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
        # if chunk == b'': return b''.join(chunks)

        chunks.append(chunk)

        bytes_received = bytes_received + len(chunk)

    return b''.join(chunks)

if __name__ == '__main__':
    main()
