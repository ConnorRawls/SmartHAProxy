#include <stdlib.h>
#include <stdio.h>
#include <stdbool.h>
#include <ctype.h>
#include <string.h>
#include <err.h>

#include <haproxy/sdsock.h>
#include <haproxy/whitelist.h>
#include <haproxy/fileRead.h>

#define CAPACITY 50 // Number of possible requests
#define MAX_LINE 1024
#define MAX_COLUMN 512

Whitelist whitelist;

// Hashing algorithm
int hashRequest(char *key)
{
    int x = 0;

    for(int i = 0; key[i]; i++) {
        x += key[i];
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
Request *createRequest(char* method, char *url, char *query, char *servers)
{
    char key[MAX_LINE];
    Request *request;

    strcat(strcat(strcat(key, method), url), query);
    request = (Request*)malloc(sizeof(Request));

    request->key = (char*)malloc(strlen(key) + 1);
    request->method = (char*)malloc(strlen(method) + 1);
    request->url = (char*)malloc(strlen(url) + 1);
    request->query = (char*)malloc(strlen(query) + 1);
    request->servers = (char*)malloc(strlen(servers) + 1);

    strcpy(request->key, key);
    strcpy(request->method, method);
    strcpy(request->url, url);
    strcpy(request->query, query);
    strcpy(request->servers, servers);

    return request;
}

// Insert request into whitelist
void insertRequest(char* method, char *url, char* query, char *servers)
{
    char key[MAX_LINE];
    int index;
    Request *request;
    Request *current;

    // Create item
    request = createRequest(method, url, query, servers);

    // Compute index based on hashing algorithm
    strcat(strcat(strcat(key, method), url), query);
    index = hashRequest(key);

    // Check if index is occupied by comparing urls
    current = whitelist.requests[index];

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
        if(strcmp(current->key, key) == 0) {
            freeRequest(request);
            strcpy(whitelist.requests[index]->servers, servers);
            return;
        }

        // Scenario 2: Collision
        else {
            collision(request);
            freeRequest(request);
            return;
        }
    }
}

// Fill whitelist with new values
void updateWhitelist()
{
    FILE *file;
    char row[MAX_LINE];
    char method[MAX_COLUMN];
    char url[MAX_COLUMN];
    char query[MAX_COLUMN];
    char servers[MAX_COLUMN];
    char *tkn;

    // QUARANTINE //
    SDSock_Set(); // Lock for reading from /Whitelist/whitelist.csv

    file = fopen("/Whitelist/whitelist.csv", "r");
    if(file == NULL) err(1, "\nFile not found.\n");

    while(feof(file) != true) {
        // Receive row
        while(fgets(row, MAX_LINE, file)) {
            // Parse row
            tkn = strtok(row, ",");
            strcpy(method, tkn);
            tkn = strtok(NULL, ",");
            strcpy(url, tkn);
            tkn = strtok(NULL, ",");
            strcpy(query, tkn);
            tkn = strtok(NULL, ",");
            strcpy(servers, tkn);

            // Adjust whitelist entry
            insertRequest(method, url, query, servers);
        }
    }

    fclose(file);
    SDSock_Release();
    // QUARANTINE //

    return;
}

// Find request's whitelist in table
char *searchRequest(char *key)
{
    int index = hashRequest(key);

    // Search table for url
    Request *request = whitelist.requests[index];

    // Move to non NULL item
    if(request != NULL) {
        if(strcmp(request->key, key) == 0) return request->servers;
    }

    return NULL;
}

int onWhitelist(char *task_wl, char *server_id)
{
    char which_id = server_id[strlen(server_id) - 1];

    if(strchr(task_wl, which_id)) return 1;
    else return 0;
}

// Display item statistics
void printRequest(char *method, char *url, char *query)
{
    char key[MAX_LINE];
    char *servers;

    strcat(strcat(strcat(key, method), url), query);

    if((servers = searchRequest(key)) == NULL) {
        printf("Key: \"%s\" does not exist.\n", key);
        return;
    }

    else {
        printf("Key: \"%s, Servers: %s\n", key, servers);
    }
}

// Display contents of hash table
void printWhitelist()
{
    printf("\n\nWhitelist\n---------------------------------------------\n");

    for(int i = 0; i < whitelist.size; i++) {
        if(whitelist.requests[i]) {
            printf("Index: %d, Key: \"%s\", Servers: %s\n", i, \
            whitelist.requests[i]->key, whitelist.requests[i]->servers);
        }
    }

    printf("---------------------------------------------\n");
}

// Handle hash table collisions
void collision(Request *request)
{
    // printf("Hash table collision. URL: \"%s\"\n", request->url);
    return;
}

// Destruct request items
void freeRequest(Request *request)
{
    free(request->key);
    free(request->method);
    free(request->url);
    free(request->query);
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
