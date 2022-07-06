import os
import time
import glob
import argparse
from statistics import mean, stdev
from multiprocessing import Process, Manager, Lock, Value
from datetime import datetime

import libvirt
import pandas as pd

DEBUG = False
SRV_COUNT = 7
CURR_PATH = os.getcwd()

def main():
    start_time = datetime.now()
    print(f'Starting operation [{start_time}]')

    with Manager() as m:
        cpu_usage = m.dict()
        cpu_lock = m.Lock()

        init(cpu_usage)

        proc1 = Process(target = cpuUsage, args = (cpu_usage, cpu_lock, proc2))
        proc2 = Process(target = runTests, args = (cpu_usage, cpu_lock))

        proc1.start()
        proc2.start()
        proc2.join()
        proc2.terminate()
        proc1.join()
        proc1.terminate()

    end_time = datetime.now()
    print(f'Operation complete [{end_time}]')

def runTests(cpu_usage, cpu_lock):
    test_dir = CURR_PATH + '/workloads/'
    test_plans = glob.glob(test_dir + '*.jmx')
    cpu_avgs = {} # Average CPU util. across all servers during test plan

    for plan in test_plans:
        plan_name = plan.replace('.jmx', '')
        cpu_avgs[plan_name] = [] # List over 30 test runs

    for test_count in range(1, 31):
        for plan in test_plans:
            plan_name = plan.replace('.jmx', '')
            
            cpu_lock.acquire()
            for server in cpu_usage: cpu_usage[server].clear()
            cpu_lock.release()

            jmeter(plan, test_count)

            cpu_buff = []
            cpu_lock.acquire()
            for server in cpu_usage:
                cpu_buff.append(mean(cpu_usage[server]))
            cpu_avgs[plan_name].append(mean(cpu_buff))
            cpu_lock.release()

            if DEBUG == True: break

            time.wait(60)

        if DEBUG == True: break

    logResults(cpu_avgs)

    return

def cpuUsage(cpu_usage, cpu_lock, proc2):
    conn = libvirt.openReadOnly("qemu+ssh://root@hpcccloud1.cmix.louisiana.edu/system")
    while True:
        if not proc2.is_alive(): return
        for server in cpu_usage:
            domain = conn.lookupByName(server)

            time1 = time.time()
            clock1 = int(domain.info()[4])
            time.sleep(1.25)
            time2 = time.time()
            clock2 = int(domain.info()[4])
            cores = int(domain.info()[3])

            cpu_lock.acquire()
            cpu_buffer = round((clock2 - clock1) * 100 / ((time2 - time1) * cores * 1e9), 2)
            if cpu_buffer > 100: cpu_buffer = 100
            cpu_usage[server].append(cpu_buffer) 
            cpu_lock.release()

def jmeter(plan, test_count):
    jmeter_dir = CURR_PATH + '/apache-jmeter-5.4.1/bin/jmeter'
    log_dir = CURR_PATH + f'/results/{plan.replace(".jmx", "")}/'
    log_file = plan.replace('.jmx', f'-{test_count}.csv')

    os.system(f'{jmeter_dir} -n -t {plan} -l {log_dir + log_file} -J jmeterengine.force.system.exit=true')

def logResults(cpu_avgs):
    log_dirs = glob.glob(CURR_PATH + '/results/*')
    results = {} # Response time, Error rate, CPU utilization

    # Each workload (test) has its own directory
    for test_name in log_dirs:
        results[test_name] = {}
        time_buffer = []
        err_buffer= []

        # Each workload directory each 30 result files (test log)
        test_logs = glob.glob(CURR_PATH + f'/results/{test_name}/*')
        for test_log in test_logs:
            with open(test_log, 'r') as file:
                time = []
                err = 0
                row_count = 0

                # Each test log has numerous request results (rows)
                for row in file:
                    row_count += 1
                    time.append(float(row[1]) / 1000) # Microsecond to ms
                    if row[3] != '200' and row[3] != '302': err += 1

                time_buffer.append(mean(time))
                err_buffer.append(err / row_count)

        results[test_name]['time'] = mean(time_buffer)
        results[test_name]['time_stdev'] = stdev(time_buffer)
        results[test_name]['error'] = mean(err_buffer)
        results[test_name]['error_stdev'] = stdev(err_buffer)
        results[test_name]['cpu'] = mean(cpu_avgs)
        results[test_name]['cpu_stdev'] = stdev(cpu_avgs)

    # Columns = Metric, Indexes = Test plan, Values = Server average
    metrics = ['time', 'time_stdev', 'error', 'error_stdev', 'cpu', 'cpu_stdev']
    df = pd.DataFrame.from_dict(results, orient='index', columns = metrics)
    df.to_csv(CURR_PATH + '/results/averages.csv')

    return

def init(cpu_usage):
    global DEBUG
    parser = argparse.ArgumentParser()

    parser.add_argument('-d', '--debug', help = "run a short debug test", action = "store_true")
    args = parser.parse_args()

    if args.debug:
        DEBUG = True

    for srv_num in range(1, SRV_COUNT + 1): # Dirty way to iterate to 7 from 1
        if srv_num == '1': srv_name = 'WP-Host'
        else: srv_name = f'WP-Host-0{srv_num}'
        cpu_usage[srv_name] = []

if __name__=="__main__":
    main()