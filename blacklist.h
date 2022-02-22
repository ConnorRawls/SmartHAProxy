#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <netdb.h>

#include <haproxy/request.h>

struct Blacklist {
    int sdsock;
    Requests* tasks[7];  // Magic 7 because we know a priori
};

extern struct Blacklist blacklist;
