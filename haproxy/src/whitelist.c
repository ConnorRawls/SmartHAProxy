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
#define MAXURL 100
#define MAXSRV 10

Whitelist whitelist;

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

// // Fill whitelist with new values
// void updateWhitelist()
// {
//     char *file_name, *buffer, *data_parsed, *url, *servers;

//     // printf("\nAcquiring access to shared volume...\n");

//     SDSock_Set(); // Lock for reading from /Whitelist/whitelist.csv

//     // printf("\nAccess granted. Reading file...\n");

//     file_name = "/Whitelist/whitelist.csv";

//     buffer = fileRead(file_name);

//     // printf("\nFinished reading file. Releasing lock...\n");

//     SDSock_Release();

//     // printf("\nData transfer complete.\n");

//     data_parsed = strtok(buffer, "\n");

//     while(data_parsed != NULL) {
//         data_parsed = strtok(NULL, ",");
//         url = strBurn(data_parsed);

//         data_parsed = strtok(NULL, ",");
//         servers = strBurn(data_parsed);

//         if(servers[strlen(servers) - 1] == '\0') break;

//         insertRequest(url, servers);

//         data_parsed = strtok(NULL, "\n");
//     }

//     free(buffer);

//     return;
// }

// Fill whitelist with new values
void updateWhitelist()
{
    FILE *file_ptr;
    char *buffer, *temp, url[1000], servers[1000];
    long int file_size;
    char *file_name;

    // QUARANTINE //
    SDSock_Set(); // Lock for reading from /Whitelist/whitelist.csv

    file_name = "/Whitelist/whitelist.csv";

    file_ptr = fopen(file_name, "r");
    if(file_ptr == NULL) err(1, "\nFile not found.\n");

    fseek(file_ptr, 0, SEEK_END);
    file_size = ftell(file_ptr);
    fseek(file_ptr, 0, SEEK_SET);

    buffer = malloc(sizeof(char)*file_size);

    if(fgets(buffer, file_size, file_ptr) == NULL) {
        printf("\nError dumping file contents to string.\n");
    }

    memset(url, 0, sizeof(url));
    memset(servers, 0, sizeof(servers));
    temp = strtok(buffer, ",");
    while(temp != NULL) {
        strcpy(url, temp);
        temp = strtok(NULL, ",");
        strcpy(servers, temp);
        temp = strtok(NULL, ",");
        insertRequest(url, servers);
        memset(url, 0, sizeof(url));
        memset(servers, 0, sizeof(servers));
    }

    fclose(file_ptr);
    free(buffer);
    free(temp);

    SDSock_Release();
    // QUARANTINE //

    return;
}

char *strBurn(char *srvrply_parted)
{
    char *tmp1, *tmp2;
    char *burn = "[] \"";

    for(tmp1 = srvrply_parted, tmp2 = srvrply_parted; *tmp2; ++tmp1) {
        if(!*tmp1 || !strchr(burn, *tmp1)) {
            if(tmp2 != tmp1) {
                *tmp2 = *tmp1;
            }
            if(*tmp1) ++tmp2;
        }
    }
    
    return srvrply_parted;
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

char *allocateSrvSize(char *url, char *servers)
{
    int index = hashRequest(url);

    Request *request = whitelist.requests[index];

    if(request != NULL) {
        servers = malloc(sizeof(request->servers));

        return servers;
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
    printf("\n\nWhitelist\n---------------------------------------------\n");

    for(int i = 0; i < whitelist.size; i++) {
        if(whitelist.requests[i]) {
            printf("Index: %d, URL: \"%s\", Servers: %s\n", i, \
            whitelist.requests[i]->url, whitelist.requests[i]->servers);
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
