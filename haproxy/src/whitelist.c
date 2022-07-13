#include <stdlib.h>
#include <stdio.h>
#include <stdbool.h>
#include <ctype.h>
#include <string.h>
#include <err.h>

#include <haproxy/sdsock.h>
#include <haproxy/whitelist.h>
#include <haproxy/fileRead.h>

#define CAPACITY 100
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
    whitelist.requests = malloc(sizeof(Request*) * whitelist.size);

    for(int i = 0; i < whitelist.size; i++) whitelist.requests[i] = NULL;

    return;
}

// Create request item in whitelist
Request *createRequest(char* method, char *url, char *query, char *servers)
{
    Request *request;
    char key[MAX_LINE] = "";

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
    int index;
    Request *request;
    Request *current;
    char key[MAX_LINE] = "";

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
            strcpy(whitelist.requests[index]->servers, servers);
            freeRequest(request);
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

    // ***
    // printf("\nUpdating whitelist.\n");

    // QUARANTINE //
    SDSock_Set(); // Lock for reading from /Whitelist/whitelist.csv

    // ***
    // printf("\nSocket set.\n");

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

            // ***
            // printf("\n(whitelist.c) Method: %s", method);
            // printf("\n(whitelist.c) URL: %s", url);
            // printf("\n(whitelist.c) Query: %s", query);
            // printf("\n(whitelist.c) Servers: %s", servers);

            // Adjust whitelist entry
            insertRequest(method, url, query, servers);

            // ***
            // printRequest(method, url, query);
            // printf("(whitelist.c) Whitelist count: %d\n", whitelist.count);
        }
    }

    // ***
    // printf("\nWhitelist parsed.\n");

    fclose(file);
    SDSock_Release();
    // QUARANTINE //

    // ***
    // printf("\nSocket released.\n");

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
    char *servers;
    char key[MAX_LINE] = "";

    strcat(strcat(strcat(key, method), url), query);

    if((servers = searchRequest(key)) == NULL) {
        printf("(whitelist.c) Key: \"%s\" does not exist.", key);
        return;
    }

    else {
        printf("(whitelist.c) Key: \"%s\", Servers: %s", key, servers);
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
    printf("Hash table collision.\nKey: \"%s\"\n", request->key);
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

// // Hashing algorithm
// int hashRequest(char *key)
// {
//     int x = 0;

//     for(int i = 0; key[i]; i++) {
//         x += key[i];
//     }

//     return x % CAPACITY;
// }

// // Construct whitelist
// void createWhitelist(int size)
// {
//     whitelist.size = size;
//     whitelist.count = 0;
//     whitelist.requests = malloc(sizeof(Request*) * whitelist.size);

//     for(int i = 0; i < whitelist.size; i++) whitelist.requests[i] = NULL;

//     return;
// }

// // Create request item in whitelist
// Request *createRequest(char* method, char *url, char *query, char *servers)
// {
//     int mth_len;
//     int url_len;
//     int qry_len;
//     int key_len;
//     char *key;
//     Request *request;

//     mth_len = stringLength(method);
//     url_len = stringLength(url);
//     qry_len = stringLength(query);
//     key_len = mth_len + url_len + qry_len;

//     key = malloc(sizeof(char) * (key_len) + 1);
//     strcat(strcat(strcat(strcat(key, method), url), query), '\0');

//     request = (Request*)malloc(sizeof(Request));

//     request->key = (char*)malloc(strlen(key) + 1);
//     request->method = (char*)malloc(strlen(method) + 1);
//     request->url = (char*)malloc(strlen(url) + 1);
//     request->query = (char*)malloc(strlen(query) + 1);
//     request->servers = (char*)malloc(strlen(servers) + 1);

//     strcpy(request->key, key);
//     strcpy(request->method, method);
//     strcpy(request->url, url);
//     strcpy(request->query, query);
//     strcpy(request->servers, servers);

//     free(key);
//     return request;
// }

// // Insert request into whitelist
// void insertRequest(char* method, char *url, char* query, char *servers)
// {
//     int mth_len;
//     int url_len;
//     int qry_len;
//     int key_len;
//     char *key;
//     int index;
//     Request *request;
//     Request *current;

//     // Create item
//     request = createRequest(method, url, query, servers);

//     // Compute index based on hashing algorithm
//     mth_len = stringLength(method);
//     url_len = stringLength(url);
//     qry_len = stringLength(query);
//     key_len = mth_len + url_len + qry_len;

//     key = malloc(sizeof(char) * key_len);
//     strcat(strcat(strcat(key, method), url), query);

//     index = hashRequest(key);

//     // Check if index is occupied by comparing urls
//     current = whitelist.requests[index];

//     // If not
//     if(current == NULL) {
//         // If url doesn't exist
//         if(whitelist.count == whitelist.size) {
//             printf("Whitelist has reached capacity :(\n");
//             freeRequest(request);
//             free(key);
//             return;
//         }

//         // Insert request
//         whitelist.requests[index] = request;
//         whitelist.count++;
//     }

//     // Otherwise
//     else {
//         // Scenario 1: Only update server list
//         if(strcmp(current->key, key) == 0) {
//             strcpy(whitelist.requests[index]->servers, servers);
//             freeRequest(request);
//             free(key);
//             return;
//         }

//         // Scenario 2: Collision
//         else {
//             collision(request);
//             freeRequest(request);
//             free(key);
//             return;
//         }
//     }
// }

// // Fill whitelist with new values
// void updateWhitelist()
// {
//     FILE *file;
//     char row[MAX_LINE];
//     char method[MAX_COLUMN];
//     char url[MAX_COLUMN];
//     char query[MAX_COLUMN];
//     char servers[MAX_COLUMN];
//     char *tkn;

//     // ***
//     // printf("\nUpdating whitelist.\n");

//     // QUARANTINE //
//     SDSock_Set(); // Lock for reading from /Whitelist/whitelist.csv

//     // ***
//     // printf("\nSocket set.\n");

//     file = fopen("/Whitelist/whitelist.csv", "r");
//     if(file == NULL) err(1, "\nFile not found.\n");

//     while(feof(file) != true) {
//         // Receive row
//         while(fgets(row, MAX_LINE, file)) {
//             // Parse row
//             tkn = strtok(row, ",");
//             strcpy(method, tkn);
//             tkn = strtok(NULL, ",");
//             strcpy(url, tkn);
//             tkn = strtok(NULL, ",");
//             strcpy(query, tkn);
//             tkn = strtok(NULL, ",");
//             strcpy(servers, tkn);

//             // ***
//             printf("\n(whitelist.c) Method: %s", method);
//             printf("\n(whitelist.c) URL: %s", url);
//             printf("\n(whitelist.c) Query: %s", query);
//             printf("\n(whitelist.c) Servers: %s", servers);

//             // Adjust whitelist entry
//             insertRequest(method, url, query, servers);

//             // ***
//             printRequest(method, url, query);
//             printf("(whitelist.c) Whitelist count: %d\n", whitelist.count);
//         }
//     }

//     // ***
//     // printf("\nWhitelist parsed.\n");

//     fclose(file);
//     SDSock_Release();
//     // QUARANTINE //

//     // ***
//     // printf("\nSocket released.\n");

//     return;
// }

// // Find request's whitelist in table
// char *searchRequest(char *key)
// {
//     int index = hashRequest(key);

//     // Search table for url
//     Request *request = whitelist.requests[index];

//     // Move to non NULL item
//     if(request != NULL) {
//         if(strcmp(request->key, key) == 0) return request->servers;
//     }

//     return NULL;
// }

// int stringLength(char *string)
// {
//     char c;
//     int i = 0;

//     do {
//         c = string[i];
//         i++;
//     } while(c != '\0');

//     i--;
//     printf("(whitelist.c) String %s length: %d\n", string, i);
//     return i;
// }

// int onWhitelist(char *task_wl, char *server_id)
// {
//     char which_id = server_id[strlen(server_id) - 1];

//     if(strchr(task_wl, which_id)) return 1;
//     else return 0;
// }

// // Display item statistics
// void printRequest(char *method, char *url, char *query)
// {
//     int mth_len;
//     int url_len;
//     int qry_len;
//     int key_len;
//     char *servers;
//     char *key;

//     mth_len = stringLength(method);
//     url_len = stringLength(url);
//     qry_len = stringLength(query);
//     key_len = mth_len + url_len + qry_len;

//     key = malloc(sizeof(char) * key_len);
//     strcat(strcat(strcat(key, method), url), query);

//     if((servers = searchRequest(key)) == NULL) {
//         printf("(whitelist.c) Key: \"%s\" does not exist.", key);
//         free(key);
//         return;
//     }

//     else {
//         printf("(whitelist.c) Key: \"%s\", Servers: %s", key, servers);
//         free(key);
//     }
// }

// // Display contents of hash table
// void printWhitelist()
// {
//     printf("\n\nWhitelist\n---------------------------------------------\n");

//     for(int i = 0; i < whitelist.size; i++) {
//         if(whitelist.requests[i]) {
//             printf("Index: %d, Key: \"%s\", Servers: %s\n", i, whitelist.requests[i]->key, whitelist.requests[i]->servers);
//         }
//     }

//     printf("---------------------------------------------\n");
// }

// // Handle hash table collisions
// void collision(Request *request)
// {
//     printf("Hash table collision.\nKey: \"%s\"\n", request->key);
//     return;
// }

// // Destruct request items
// void freeRequest(Request *request)
// {
//     free(request->key);
//     free(request->method);
//     free(request->url);
//     free(request->query);
//     free(request->servers);
//     free(request);
// }

// // Destruct whitelist
// void freeWhitelist()
// {
//     for(int i = 0; i < whitelist.size; i++) {
//         Request *request = whitelist.requests[i];
//         if(request != NULL) freeRequest(request);
//     }

//     free(whitelist.requests);
// }
