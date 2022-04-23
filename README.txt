--- CONTENTS ---
haproxy- Source for haproxy v2.5.dev
smartdrop- Source for smartdrop module

To operate, run start both containers and run rsyslog on each. Smartdrop must be
running before haproxy starts.

--- HAPROXY ---
Compile from source and run. Refer to howToMake files for further instructions.
Receives information from SD module to make intelligent load balancing decisions.

Changes:
    -backend.c
    -haproxy.c
Additions:
    -howToMake.txt
    -howToMakeExternal.txt
    -whitelist.h
    -sdsock.h

--- SMARTDROP ---
smartdrop.py- Computations
requests.csv- Offline profiled data for request execution times.

--- NETWORKING ---
Communication between HAProxy and Smartdrop containers rely on virtual network
instantiated by Docker.

'*' Denotes published ports.

haproxy@*80- HTTP requests
haproxy@8080:smartdrop@8080- Whitelist data transferring
haproxy@90:smartdrop@90- Socat api