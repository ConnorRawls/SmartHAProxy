--- CONTENTS ---
haproxy- Source for haproxy v2.5.dev
smartdrop- Source for smartdrop module

--- HAPROXY ---
Compile from source and run. Refer to howToMake files for further instructions.
Receives information from SD module to make intelligent load balancing decisions.

Changes:
    -backend.c
    -haproxy.c
Additions:
    -howToMake.txt
    -howToMakeExternal.txt
    -blacklist.h
    -requests.h
    -sdsock.h

--- SMARTDROP ---
Run smartdrop.py after HAProxy is already running.

smartdrop.py- Computations
requests.csv- Offline profiled data for request execution times.

--- NETWORKING ---
Communication between HAProxy and Smartdrop containers rely on virtual network
instantiated by Docker.

'*' Denotes published ports.

haproxy@*80- HTTP requests
haproxy@8080:smartdrop@8080- Blacklist data transferring
haproxy@50513:smartdrop@50513- Rsyslog
haproxy@90:smartdrop@90- Socat api
apache@50513:smartdrop@*50513- Rsyslog