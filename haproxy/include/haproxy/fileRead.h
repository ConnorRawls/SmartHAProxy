#ifndef FILEREAD
#define FILEREAD

typedef struct FileData_T
{
    char **url;
    char **servers;
    int lines;
} FileData;

char *fileRead(char *file_name);

#endif
