import os
import glob
import time
import argparse
from datetime import datetime

DEBUG = False
CURR_PATH = os.getcwd()

def main():
    init()

    with open(f'{CURR_PATH}/../logs/testArch.log', 'w') as log_file:
        start_time = datetime.now()
        log_file.write(f'Start time: [{start_time}]\n')
        print(f'\n[{start_time}] Starting operation.\n')

        plan_path = CURR_PATH + '/workloads/*'
        test_plans = glob.glob(plan_path)

        # --- Debugging ---
        if DEBUG == True:
            plan = CURR_PATH + '/workloads/1-100.jmx'
            test_count = 1
            jmeter(plan, test_count)
            log_file.write(f'Test count: {test_count}    Plan: {plan}\n')
            end_time = datetime.now()
            log_file.write(f'End time: [{end_time}]')
            print(f'\n[{end_time}] Operation complete.\n')
            exit()

        for test_count in range(30):
            for plan in test_plans:
                jmeter(plan, test_count)
                log_file.write(f'Test count: {test_count}    Plan: {plan}\n')
                time.wait(60)

        end_time = datetime.now()
        log_file.write(f'End time: [{end_time}]')
        print(f'\n[{end_time}] Operation complete.\n')

def jmeter(plan, test_count):
    jmeter_path = CURR_PATH + '/apache-jmeter-5.4.1/bin/jmeter'
    plan_log = CURR_PATH + f'/data/{plan}-{test_count}.csv'

    os.system(f"{jmeter_path} -n -t {plan} -l {plan_log} -J jmeterengine.force.system.exit=true")

def init():
    global DEBUG
    parser = argparse.ArgumentParser()

    parser.add_argument('-d', '--debug', help = "run a short debug test", action = "store_true")
    args = parser.parse_args()

    if args.debug:
        DEBUG = True
        print('Running in debug mode.')

if __name__ == '__main__':
    main()