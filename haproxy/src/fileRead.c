#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <err.h>

#include <haproxy/fileRead.h>

char *fileRead(char *file_name)
{
    long int file_size;
    char *file_content;
    FILE *file_ptr;

    file_ptr = fopen(file_name, "r");

    if(file_ptr == NULL) err(1, "\nFile not found.\n.");

    // Determine size of file
    fseek(file_ptr, 0, SEEK_END);
    file_size = ftell(file_ptr);
    fseek(file_ptr, 0, SEEK_SET);

    // Allocate memory to string
    file_content = malloc(sizeof(char)*file_size);

    // Dump file contents into string
    if(fgets(file_content, file_size, file_ptr) == NULL) {
        printf("\nError dumping file contents to string.\n");
        return file_content;
    }

    fclose(file_ptr);

    return file_content;
}
