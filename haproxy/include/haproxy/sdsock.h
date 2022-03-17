// Establishes socket connection with SD server
// The socket (sdsock) is referenced as an external object (bad)

#ifndef SDSOCK
#define SDSOCK

typedef struct SDSock_T
{
	int sock;
} SDSock;

extern SDSock sdsock;

// Construct smartdrop socket
void SDSock_Make();

// Acquire remote lock
void SDSock_Set();

// Release remote lock
void SDSock_Release();

// Destruct smartdrop socket
void SDSock_Destroy();

#endif
