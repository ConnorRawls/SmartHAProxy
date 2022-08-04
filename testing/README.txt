Main command: $ ./jmeter -n -t <test-plan> -l wp-logtemp.csv
  Note, -J jmeterengine.force.system.exit=true might need to be appended to the command in order to get it to work.
  For example: $ ./jmeter -n -t <test-plan> -l wp-logtemp.csv -J jmeterengine.force.system.exit=true
  
<test-plan> is a .jmx file that describes the workload. Located in /workloads.
  ThreadGroup.num_threads = How many users.
  ThreadGroup.ramp_time = Time it will take to reach the number of threads.
