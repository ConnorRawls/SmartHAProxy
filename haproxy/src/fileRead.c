#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <err.h>

#include <haproxy/fileRead.h>

#define MAXURL 100
#define MAXSRV 10

// char *fileRead(char *file_name)
// {
//     long int file_size;
//     char *file_content;
//     FILE *file_ptr;

//     file_ptr = fopen(file_name, "r");

//     if(file_ptr == NULL) err(1, "\nFile not found.\n.");

//     // Determine size of file
//     fseek(file_ptr, 0, SEEK_END);
//     file_size = ftell(file_ptr);
//     fseek(file_ptr, 0, SEEK_SET);

//     // Allocate memory to string
//     file_content = malloc(sizeof(char)*file_size);

//     // Dump file contents into string
//     if(fgets(file_content, file_size, file_ptr) == NULL) {
//         printf("\nError dumping file contents to string.\n");
//         return file_content;
//     }

//     fclose(file_ptr);

//     return file_content;
// }

// char *fileRead(char *file_name)
// {
//     FILE *file_ptr;
//     FileData data;
//     char c;

//     file_ptr = fopen(file_name, "r");
//     if(file_ptr == NULL) err(1, "\nFile not found.\n.");

//     data.lines = 0;
//     for(c = getc(file_ptr); c != EOF; c = getc(file_ptr)) {
//         if(c == '\n') data.lines++;
//     }

//     data.url = malloc(sizeof(char)*data.lines);
//     data.servers = malloc(sizeof(char)*data.lines);
//     for(int i = 0; i < data.lines; i++) {
//         data.url[i] = malloc(sizeof(char)*MAXURL);
//         data.servers[i] = malloc(sizeof(char)*MAXSRV);
//     }

//     rewind(file_ptr);
//     for(int i = 0; i < data.lines; i++) {
//         fscanf(file_ptr, "%[^,],%[^,]", data.url[i], data.servers[i]);
//     }

//     fclose(file_ptr);
//     return data;
// }