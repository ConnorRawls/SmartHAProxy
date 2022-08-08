'''
TODO: 
Fix detectServers()
List of server and task keys referenced by multiple dictionaries. Ensures each dict.
is using the same key.

-------------------------------------
Author: Connor Rawls
Email: connorrawls1996@gmail.com
Organization: University of Louisiana
-------------------------------------

Capture task-related events and determine which servers will be able to satisfy
task types based upon SLO requirements (1 second). Communicate this information with
the load balancer.

Three processes run concurrently:
  -taskEvent
  -cpuUsage
  -comms
Six objects are referenced globally:
  -profile_matrix
  -workload
  -cpu_usage
  -predicted_time
'''

import os
import sys
import csv
import subprocess
import re
import socket
import json
import time
import sys
import itertools
import random
from datetime import datetime
from multiprocessing import Process, Manager, Lock
import libvirt
import pandas as pd
import numpy as np
from pickle import load
from sklearn.ensemble import GradientBoostingRegressor

# Used for remote messaging locks
MSGLEN = 1
SRVCOUNT = 7
# Service Level Objective = 1 second = 1,000,000 (1e6) microseconds
SLO = 1.e6
CURR_PATH = os.getcwd()

# TaskType is an HTTP request possessing known characteristics
class TaskType:
    def __init__(self, method, url, query, content, avg_size, size_stdev, \
        avg_time, time_stdev):
        self.method = method
        self.url = url
        self.query = query
        self.content = content
        self.avg_size = avg_size
        self.size_stdev = size_stdev
        self.avg_time = avg_time
        self.time_stdev = time_stdev

# Instance is a member of a given TaskType
class Instance(TaskType):
    def __init__(self, task_type, server, workload, cpu_usage, predicted_time):
        super().__init__(
            task_type.method,
            task_type.url,
            task_type.query,
            task_type.content,
            task_type.avg_size,
            task_type.size_stdev,
            task_type.avg_time,
            task_type.time_stdev
        )
        self.server = server
        self.workload = workload
        self.cpu_usage = cpu_usage
        self.predicted_time = predicted_time

    def toList(self):
        list_str = (
            f'{self.method},{self.url},{self.query},{self.content},'
            f'{self.avg_size},{self.size_stdev},{self.avg_time},'
            f'{self.time_stdev},{self.server},{self.workload},'
            f'{self.predicted_time},{self.cpu_usage}'
        )
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
        # Key is task type and values are servers task is allowed to dispatch to
        whitelist = {}
        # Master Lock TM
        wl_lock = Lock()    # Workload
        pt_lock = Lock()    # Predicted Time
        cpu_lock = Lock()   # CPU Usage
        # GBDT model
        model_path = CURR_PATH + '/Model/GBDT_Scaled_Norm.sav'
        model = load(open(model_path, 'rb'))
        # Input scaler
        x_scaler_path = CURR_PATH + '/Model/xScaler.sav'
        x_scaler = load(open(x_scaler_path, 'rb'))
        # Output scaler
        y_scaler_path = CURR_PATH + '/Model/yScaler.sav'
        y_scaler = load(open(y_scaler_path, 'rb'))

        init(profile_matrix, workload, cpu_usage, predicted_time, whitelist, m)

        # ***
        # print('Initial whitelist')
        # for task in whitelist: print(f'\n{task}\n{whitelist[task]}\n')

        # Multiprocessing mumbo jumbo
        proc1 = Process(target = taskEvent, args = (profile_matrix, workload, \
            cpu_usage, predicted_time, wl_lock, pt_lock, cpu_lock))
        proc2 = Process(target = cpuUsage, args = (cpu_usage, cpu_lock))
        proc3 = Process(target = comms, args = (profile_matrix, workload, \
            cpu_usage, predicted_time, whitelist, wl_lock, pt_lock, cpu_lock, model, \
            x_scaler, y_scaler))

        # *** Debugging purposes
        # proc4 = Process(target = debugPrint, args = (cpu_usage, cpu_lock, \
        #     predicted_time, pt_lock, workload, wl_lock))

        start_time = datetime.now()
        print(f"Commencing Smartdrop [{start_time}].")

        proc1.start()       # Start listening for task events
        proc2.start()       # Start observing hardware metrics
        proc3.start()       # Start listening for LB messages
        # proc4.start() # ***
        proc1.join()
        proc2.join()
        proc3.join()
        # proc4.join() # ***
        proc1.terminate()   # Stop listening for task events
        proc2.terminate()   # Stop observing hardware metrics
        proc3.terminate()   # Stop listening for LB messages
        # proc4.terminate() # ***

# Process 1
# -----------------------------------------------------------------------------
# Monitor task-related events
def taskEvent(profile_matrix, workload, cpu_usage, predicted_time, wl_lock, 
    pt_lock, cpu_lock):
    record = {}
    status_key = {'+' : 'new', '>' : 'complete', '-' : 'sent'}
    methods = ['GET', 'POST']
    error_count = 0

    # Clear logs
    task_event_path = '/var/log/apache_access.log'
    os.system(f'truncate -s 0 {task_event_path}')
    record_path = CURR_PATH + '/../logs/smartdrop.log'

    with open(record_path, 'a') as record_file:
        record_file.write(
            'method,url,query,content,avg_size,size_stdev,avg_time,time_stdev,'
            'server,workload,cpu_usage,predicted_time,actual_time\n'
        )

        with open(task_event_path, 'r') as task_events:
            lines = logRead(task_events)

            # MAIN LOOP: Parse log file
            for line in lines:
                new_instance = True
                status = None
                task_id = None
                method = None # Don't know why we can't method, query, ... = None
                url = None
                query = None
                content = None
                server = None
                error = None
                actual_time = None

                line = re.split(',|\s|\|', line)

                # Status
                try:
                    status = status_key[line[0][0].replace(' ', '')]

                    # # ***
                    # print(f'Status parsed: {status}')

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

                    # # ***
                    # print(f'Task ID parsed: {task_id}')

                    if task_id in record:
                        method = record[task_id].method
                        url = record[task_id].url
                        query = record[task_id].query
                        content = record[task_id].content
                        server = record[task_id].server
                        new_instance = False

                        # # ***
                        # print('Task ID found in record.')

                    else:
                        method, url, query, content, server, error = parseLine(line, \
                            profile_matrix)

                        if error == True:
                            error_count += 1
                            continue
                except IndexError:
                    error_count += 1
                    continue                

                # Response time (MICROSECONDS)
                if not new_instance:

                    # # ***
                    # print('Not a new instance.')

                    try:
                        actual_time = line[6].replace(' ', '')

                        # # ***
                        # print(f'Response time parsed: {actual_time}')

                        try: float(actual_time)
                        except ValueError:
                            actual_time = 'NULL'
                    except IndexError:
                        error_count += 1
                        continue

                # Insert task
                if status == 'new':

                    # # ***
                    # print('New status recognized.')

                    try:
                        key = f'{method},{url},{query},{content}'
                        task_type = profile_matrix[key]
                        wl_lock.acquire()
                        workload[server] += float(task_type.avg_time)
                        cpu_lock.acquire()

                        # # ***
                        # print(f'Current workload: {workload[server]}')
                        # print(f'Current CPU: {cpu_usage[server]}\n')

                        record[task_id] = Instance(task_type, server, \
                            workload[server], cpu_usage[server], \
                            predicted_time[key][server])
                        cpu_lock.release()
                        wl_lock.release()                        
                    except KeyError:
                        error_count += 1

                # Task completion
                else:

                    # # ***
                    # print('Completion status recognized.')

                    try:
                        record_entry = record[task_id].toList()
                        key = f'{method},{url},{query},{content}'
                        task_type = profile_matrix[key]
                        wl_lock.acquire()
                        workload[server] -= float(task_type.avg_time)
                        wl_lock.release()
                        record_file.write(f'{record_entry},{actual_time}\n')
                        del record[task_id]
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
def comms(profile_matrix, workload, cpu_usage, predicted_time, whitelist, \
    wl_lock, pt_lock, cpu_lock, model, x_scaler, y_scaler):
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
                pt_lock.acquire()

                # Calculate whitelist
                whiteAlg(profile_matrix, cpu_usage, workload, predicted_time, \
                    model, x_scaler, y_scaler, whitelist)

                # Release locks
                pt_lock.release()
                cpu_lock.release()
                wl_lock.release()

                # ***
                # for task in whitelist: print(f'\n{task}\n{whitelist[task]}\n')

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
def whiteAlg(profile_matrix, cpu_usage, workload, predicted_time, model, x_scaler, \
    y_scaler, whitelist):
    GBDT(profile_matrix, cpu_usage, workload, predicted_time, model, x_scaler, \
        y_scaler)

    # Iterate for all tasks
    for task in predicted_time.keys():
        # Iterate for all servers
        for server in predicted_time[task].keys():
            # If server can't satisfy task's deadline
            if server in whitelist[task] and \
                predicted_time[task][server] >= SLO:
                # Remove it from server's whitelist if it is there
                whitelist[task].remove(server)

                # ***
                # print(
                #     f"\n\n* Removing server {server} from task {task}"
                #     f"\n  (PRT: {predicted_time[task][server]})"
                # )

            elif server not in whitelist[task] and \
                predicted_time[task][server] < SLO:
                # Add the task to the server's whitelist
                whitelist[task].append(server)

        # ***
        for i in range(7):
            if str(i + 1) not in whitelist[task]:
                print(
                    f'Non-default whitelist detected.\n'
                    f'{task}:\n'
                    f'{whitelist[task]}\n'
                )
                break

# Gradient Boosted Decision Tree
# -----------------------------------------------------------------------------
# Predict task types' response time on each server
def GBDT(profile_matrix, cpu_usage, workload, predicted_time, model, x_scaler, \
    y_scaler):
    # N channel matrix, where N = Number of servers

    for server in cpu_usage.keys():
        # Convert task features into list format
        method_buff = []
        url_buff = []
        query_buff = []
        content_buff = []
        size_buff = []
        size_stdev_buff = []
        time_buff = []
        time_stdev_buff = []
        for task_key in profile_matrix:
            task = profile_matrix[task_key]
            method_buff.append(task.method)
            url_buff.append(task.url)
            query_buff.append(task.query)
            content_buff.append(task.content)
            size_buff.append(task.avg_size)
            size_stdev_buff.append(task.size_stdev)
            time_buff.append(task.avg_time)
            time_stdev_buff.append(task.time_stdev)

        # Convert CPU and workload into list format
        srv_buff = [] # Is this necessary?
        cpu_buff = []
        wl_buff = []
        # Remove this line when we know for sure -->
        for _ in profile_matrix:
            srv_buff.append(server)
            cpu_buff.append(cpu_usage[server])
            wl_buff.append(workload[server])

        df = pd.DataFrame(list(zip(method_buff, url_buff, query_buff, \
            content_buff, size_buff, size_stdev_buff, time_buff, time_stdev_buff, \
            srv_buff, wl_buff, cpu_buff)), columns = ['Method', 'URL', 'Query', \
            'Content', 'Size', 'SizeStdev', 'Time', 'TimeStdev', 'Server', \
            'Workload', 'CPU'])

        df = df.replace('NULL', '') # Not necessary

        # ***
        # headers = []
        # for column in df.columns:
        #     headers.append(column)
        # headers = ','.join(headers)
        # with open('/test_before.csv', 'w') as file: file.write(headers)

        df = pd.get_dummies(df, columns = ['Method', 'URL', 'Query', 'Content'], \
            sparse = True)

        # ***
        # headers = []
        # for column in df.columns:
        #     headers.append(column)
        # headers = ','.join(headers)
        # with open('/test_after.csv', 'w') as file: file.write(headers)
        # sys.exit()

        df = df.drop(columns = ['Query_'])

        # Use each metric as a column in matrix
        input_data = df.to_numpy()

        # Perform ML inference
        output_data = []
        # Each row is a task type
        for row in input_data:
            row = x_scaler.transform(row.reshape(1, -1)) # Single sample
            output_data.append(abs(model.predict(row)))
        for (task, time_on_server) in zip(predicted_time.keys(), output_data):
            time_on_server = y_scaler.inverse_transform(time_on_server)
            predicted_time[task][server] = time_on_server

# Utilities
# -----------------------------------------------------------------------------
# How many backend servers are running
def detectServers():
    SOCKET = 'TCP:haproxy:90'
    detect = subprocess.run('echo "show servers state" | socat {} stdio'.format(SOCKET), \
        shell = True, stdout = subprocess.PIPE).stdout.decode('utf-8')
    return detect.count('web_servers')

# Determine method, URL, etc. from task event
def parseLine(line, profile_matrix):
    methods = ['GET', 'POST']
    # Query search patterns
    q_patterns = '\?wc-ajax=add_to_cart|\?wc-ajax=get_refreshed_fragments'
    method = None
    query = None
    url = None
    content = None
    server = None
    error = None

    # Method
    try:
        method = line[1].replace(' ', '')
        if method not in methods:
            error = True
            return method, url, query, content, server, error
    except IndexError:
        error = True
        return method, url, query, content, server, error

    # Query
    try:
        found = False
        query = re.search(q_patterns, line[2].replace(' ', ''))
        try:
            query = query.group()
            line[2] = line[2].replace(query, '')
        except AttributeError: query = 'NULL'
        for key, value in profile_matrix.items():
            if query in key:
                found = True
                break
        if found == False:
            error = True
            return method, url, query, content, server, error
    except IndexError:
        error = True
        return method, url, query, content, server, error

    # URL
    try:
        found = False
        url = line[2].replace(' ', '')
        if (query != 'NULL' or url == '/wp-profiling/') \
            and 'index.php' not in url:
            url = url + 'index.php'
        for key, value in profile_matrix.items():
            if url in key:
                found = True
                break
        if found == False:
            error = True
            return method, url, query, content, server, error
    except IndexError:
        error = True
        return method, url, query, content, server, error

    # Content
    try:
        content_index = None
        for string in line:
            if 'file:' in string:
                content_index = line.index(string)
                break
        if content_index == None:
            error = True
            return method, url, query, content, server, error
        content = line[content_index].replace('file:', '').replace(' ', '')
    except IndexError:
        error = True
        return method, url, query, content, server, error

    # Server
    try:
        server = line[-2][-1].replace(' ', '').replace('\n', '')
        try: int(server)
        except ValueError:
            error = True
            return method, url, query, content, server, error
    except IndexError:
        error = True
        return method, url, query, content, server, error
    except KeyError:
        error = True
        return method, url, query, content, server, error

    return method, url, query, content, server, error

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
        for method, url, query, content, avg_size, size_stdev, avg_time, \
            time_stdev in reader:
            if query == '': query = 'NULL'
            key = f'{method},{url},{query},{content}'
            profile_matrix[key] = TaskType(method, url, query, content, avg_size, \
                size_stdev, avg_time, time_stdev)
            whitelist[key] = []

    # Workload and CPU Usage
    for server in range(SRVCOUNT):
        workload[f'{server + 1}'] = 0. # *** Should this be init. to 0.001?
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

def debugPrint(cpu_usage, cpu_lock, predicted_time, pt_lock, workload, wl_lock):
    while True:
        time.sleep(5)
        rnd_task = random.choice(list(predicted_time.keys()))
        cpu_lock.acquire()
        pt_lock.acquire()
        wl_lock.acquire()

        print('\n\n- SYSTEM DIAGNOSTICS -')
        for server in workload.keys():
            print(f'{server} CPU: {cpu_usage[server]} Workload: {workload[server]}')
        print('\n- TASK DIAGNOSTICS -')
        print(f'Randomly selected task: {rnd_task}')
        for server in predicted_time[rnd_task].keys():
            print(f'PRT for {server}: {predicted_time[rnd_task][server]}')

        cpu_lock.release()
        pt_lock.release()
        wl_lock.release()

if __name__ == '__main__': main()