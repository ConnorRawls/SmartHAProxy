#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <netdb.h>
#include <stdlib.h>
#include <err.h>
#include <errno.h>

#include <haproxy/sdsock.h>

SDSock sdsock;

// Construct smartdrop socket
void SDSock_Make()
{
	int sock, i;
    struct hostent *he;
    struct in_addr **addr_list;
	struct sockaddr_in server;
	// Determine ip from hostname
    char *hostname = "smartdrop";
    char ip[100];
	
	//Create socket
	sock = socket(AF_INET, SOCK_STREAM, 0);
	if (sock == -1)
	{
		printf("Could not create socket");
	}
	printf("\nSocket created.");

    if ((he = gethostbyname(hostname)) == NULL)
    {
        herror("getbyhostname");
        return;
    }

    addr_list = (struct in_addr **) he->h_addr_list;

    for (i = 0; addr_list[i] != NULL; i++)
    {
        strcpy(ip, inet_ntoa(*addr_list[i]));
    }

	server.sin_addr.s_addr = inet_addr(ip);
	server.sin_family = AF_INET;
	server.sin_port = htons( 8080 );

	//Connect to remote server
	if (connect(sock, (struct sockaddr *)&server,
		sizeof(server)) < 0)
	{
		perror("connect failed. Error");
		return;
	}
	
	sdsock.sock = sock;

	return;
}

void SDSock_Set()
{
	ssize_t bytes;
	char message[1], server_reply[1];

	// Send 1
	message[0] = '1';
	if(send(sdsock.sock, message, strlen(message), 0) < 0)
	{
		printf("\nMessage send 1 failed.");
		return;
	}

	// Receive 1
	bytes = recv(sdsock.sock, server_reply, 1, 0);
	if(bytes < 0)
	{
		fprintf(stderr, "recv: %s (%d)\n", strerror(errno), errno);
		printf("\nReceive 1 failed. bytes: %ld", bytes);
		return;
	}

	return;
}

void SDSock_Release()
{
	ssize_t bytes;
	char message[1], server_reply[1];

	// Send 2
	message[0] = '2';
	if(send(sdsock.sock, message, strlen(message), 0) < 0)
	{
		printf("\nMessage send 2 failed.");
		return;
	}

	// Receive 2
	bytes = recv(sdsock.sock, server_reply, 1, 0);
	if(bytes < 0)
	{
		fprintf(stderr, "recv: %s (%d)\n", strerror(errno), errno);
		printf("\nReceive 2 failed. recv: %ld", bytes);
		return;
	}

	return;
}

// Destruct smartdrop socket
void SDSock_Destroy()
{
	close(sdsock.sock);
}
