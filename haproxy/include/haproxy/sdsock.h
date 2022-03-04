#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <netdb.h>

typedef struct SDSock_T
{
	int sock;
} SDSock;

extern SDSock sdsock;

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
	puts("Socket created.\n");

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
	
	puts("Connected.\n");
	
	sdsock.sock = sock;

	return;
}

// Fetch data from smartdrop
char *SDSock_Get(char *server_reply)
{
	char *message = "Hello";

	//Send some data
	if (send(sdsock.sock, message, strlen(message), 0) < 0)
	{
		puts("Send failed");
		return "Error";
	}
	
	//Receive a reply from the server
	if (recv(sdsock.sock, server_reply, 2000, 0) < 0)
	{
		puts("recv failed");
	}

	return server_reply;
}

// Destruct smartdrop socket
void SDSock_Destroy()
{
	close(sdsock.sock);
}