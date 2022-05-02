// TODO
// Replace servers char array in Request_T with linked list.
// Develop collision handler (overflow bucket linked list).

// Hash table for whitelist. Contains various utility functions

#ifndef WHITELIST
#define WHITELIST

#include <time.h>
#include <pthread.h>

typedef struct Lock_T
{
    pthread_mutex_t lock;
} Lock;

extern Lock check;

// Hashed item
typedef struct Request_T
{
    char *url;
    char *servers;
} Request;

typedef struct ReqCount_T
{
    int count;
    clock_t time;
} ReqCount;

extern ReqCount reqCount;

// Hash table
typedef struct Whitelist_T
{
    Request **requests;
    int size;
    int count;
} Whitelist;

extern Whitelist whitelist;

// Hashing algorithm
int hashRequest(char *url);

// Construct whitelist
void createWhitelist(int size);

// Create request item in whitelist
Request *createRequest(char *url, char *servers);

// Insert request into whitelist
void insertRequest(char *url, char *servers);

// Fill whitelist with new values
void updateWhitelist();

// Remove unneeded chars from string
char *strBurn(char *srvrply_parted);

// Find request's whitelist in table
char *searchRequest(char *url);

// Malloc variable containing request's servers
char *allocateSrvSize(char *url, char *servers);

// Compare server ID to task's whitelist
int onWhitelist(char *task_wl, char *server_id);

// Display item statistics
void printRequest(char *url);

// Display contents of hash table
void printWhitelist();

// Handle hash table collisions
void collision(Request *request);

// Destruct request items
void freeRequest(Request *request);

// Destruct whitelist
void freeWhitelist();

#endif
