// TODO
// Replace servers char array in Request_T with linked list.
// Develop collision handler (overflow bucket linked list).

#include <stdlib.h>
#include <stdio.h>
#include <stdbool.h>
#include <ctype.h>
#include <string.h>

#include <haproxy/sdsock.h>

#define CAPACITY 50 // Number of possible requests

// SDSock sdsock;

// Hashed item
typedef struct Request_T
{
    char *url;
    char *servers;
} Request;

// Hash table
typedef struct Whitelist_T
{
    Request **requests;
    int size;
    int count;
} Whitelist;

extern Whitelist whitelist;

int hashRequest(char *url);
void createWhitelist(int size);
Request *createRequest(char *url, char *servers);
void insertRequest(char *url, char *servers);
char *searchRequest(char *url);
void printRequest(char *url);
void printWhitelist();
void collision(Request *request);
void freeRequest(Request *request);
void freeWhitelist();

// -------------------------------------------------------------------------------

// int main() {

//     insertRequest("/wp-profiling/", "1,2,3");
//     insertRequest("/wp-profiling/cart/", "3,5,7");

//     printRequest("/wp-profiling/");
//     printRequest("/wp-profiling/cart/");

//     printWhitelist();

//     return 0;
// }

// -------------------------------------------------------------------------------

// Hashing algorithm
int hashRequest(char *url)
{
    int x = 0;

    for(int i = 0; url[i]; i++) {
        x += url[i];
    }

    return x % CAPACITY;
}

// Construct whitelist
void createWhitelist(int size)
{
    whitelist.size = size;
    whitelist.count = 0;
    whitelist.requests = calloc(whitelist.size, sizeof(Request*));

    for(int i = 0; i < whitelist.size; i++) whitelist.requests[i] = NULL;

    return;
}

// Create request item in whitelist
Request *createRequest(char *url, char *servers)
{
    Request *request = (Request*)malloc(sizeof(Request));

    request->url = (char*)malloc(strlen(url) + 1);
    request->servers = (char*)malloc(strlen(servers) + 1);

    strcpy(request->url, url);
    strcpy(request->servers, servers);

    return request;
}

// Insert request into whitelist
void insertRequest(char *url, char *servers)
{
    // Create item
    Request *request = createRequest(url, servers);

    // Compute index based on hashing algorithm
    int index = hashRequest(url);

    // Check if index is occupied by comparing urls
    Request* current = whitelist.requests[index];

    // If not
    if(current == NULL) {
        // If url doesn't exist
        if(whitelist.count == whitelist.size) {
            printf("Whitelist has reached capacity :(\n");
            freeRequest(request);
            return;
        }

        // Insert request
        whitelist.requests[index] = request;
        whitelist.count++;
    }

    // Otherwise
    else {
        // Scenario 1: Only update server list
        if(strcmp(current->url, url) == 0) {
            strcpy(whitelist.requests[index]->servers, servers);
            return;
        }

        // Scenario 2: Collision
        else {
            collision(request);
            return;
        }
    }
}

// Fill whitelist with new values
void updateWhitelist()
{
    char *server_reply = malloc(sizeof(char)*2000);
    char *srvrply_parted = malloc(sizeof(server_reply));
    char *servers;

    server_reply = SDSock_Get(server_reply);
    srvrply_parted = strtok(server_reply, "|");

    while(srvrply_parted != NULL) {
        char *url = srvrply_parted;

        srvrply_parted = strtok(NULL, "|");

        servers = srvrply_parted;

        insertRequest(url, servers);

        srvrply_parted = strtok(NULL, "|");
    }
}

// Find request's whitelist in table
char *searchRequest(char *url)
{
    int index = hashRequest(url);

    // Search table for url
    Request *request = whitelist.requests[index];

    // Move to non NULL item
    if(request != NULL) {
        if(strcmp(request->url, url) == 0) return request->servers;
    }

    return NULL;
}

// Display item statistics
void printRequest(char *url)
{
    char *servers;

    if((servers = searchRequest(url)) == NULL) {
        printf("URL: \"%s\" does not exist.\n", url);
        return;
    }

    else {
        printf("URL: \"%s, Servers: %s\n", url, servers);
    }
}

// Display contents of hash table
void printWhitelist()
{
    printf("\nWhitelist\n---------------------------------------------\n");

    for(int i = 0; i < whitelist.size; i++) {
        if(whitelist.requests[i]) {
            printf("Index: %d URL: \"%s\", Servers: %s\n", i, \
            whitelist.requests[i]->url, whitelist.requests[i]->servers);
        }
    }

    printf("---------------------------------------------\n");
}

// Handle hash table collisions
void collision(Request *request)
{
    printf("Hash table collision. URL: \"%s\"\n", request->url);
    return;
}

// Destruct request items
void freeRequest(Request *request)
{
    free(request->url);
    free(request->servers);
    free(request);
}

// Destruct whitelist
void freeWhitelist()
{
    for(int i = 0; i < whitelist.size; i++) {
        Request *request = whitelist.requests[i];
        if(request != NULL) freeRequest(request);
    }

    free(whitelist.requests);
}